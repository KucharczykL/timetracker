"""Commands on one purchase."""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, Final, NamedTuple, cast, get_args

from django.db import models

from games.commands.endpoint import (
    ActStatement,
    EndpointSentences,
    Rejection,
    certainly_reversed,
    correct_endpoint,
    correct_opening_endpoint,
    normalized,
    state_endpoint,
    void_endpoint,
)
from games.commands.libraryentry import EntryStatement, entry_creation_events
from games.commands.playersession import check_note, storable
from games.commands.scope import library_entry_row, library_purchase_row
from games.end_ways import EndWay
from games.endpoints import ENTRY_ACCESS_END, PURCHASE_DAY, PURCHASE_REFUND
from games.events.dispatch import Command, CommandContext, CommandName, CommandRejected
from games.events.libraryentry import (
    ENTRY_ACCESS_END_EVENTS,
    LibraryEntryAccessEndPayload,
)
from games.events.purchase import (
    NAME_LENGTH,
    PURCHASE_REFUND_EVENTS,
    PurchaseKindValue,
    purchase_created,
    purchase_entry_changed,
    purchase_kind_changed,
    purchase_name_changed,
    purchase_note_changed,
    purchase_price_changed,
    purchase_removed,
    purchase_restored,
)
from games.events.references import capture_reference
from games.events.vocabulary import EventSpec, NewEvent, Unchanged
from games.models import (
    CURRENCY_CODE,
    EntryAccess,
    LibraryEntry,
    Purchase,
    PurchaseKind,
    Release,
)
from games.reads.endpoints import stated
from games.reads.entries import EventSequence
from games.reads.purchases import latest_refund_act, refund_owns_the_end
from timetracker.temporal import TemporalValue

UNKNOWN_KIND = "Choose one of the listed purchase kinds."
LONG_NAME = f"Keep the name within {NAME_LENGTH} characters."
UNSTORABLE_NAME = "That name contains a character we cannot store."
NOT_AN_AMOUNT = "State the amount paid as a number."
SIGNED_AMOUNT = "State the amount paid without a sign."
TOO_PRECISE_AMOUNT = "State the amount in whole cents."
TOO_LARGE_AMOUNT = "That amount is too large to record."
AMOUNT_WITHOUT_CURRENCY = "State the currency as three letters, such as EUR."
CURRENCY_WITHOUT_AMOUNT = "State an amount beside the currency, or neither."
PURCHASE_REMOVED = (
    "That purchase was removed. Put it back before changing what it records."
)
ENTRY_REMOVED = "That copy was removed. Restore it before changing its purchases."
PLAYER_GAME_REMOVED = (
    "That game was removed from your library. Restore it before changing its purchases."
)
RELEASE_REMOVED = "That copy's release was removed from the catalog. Restore it first."
ENTRY_OF_ANOTHER_GAME = (
    "That copy belongs to another game. Choose a copy of this purchase's game."
)
SAME_DAY = "This correction states the day the purchase states."
REFUND_BEFORE_PURCHASE = (
    "This purchase was made after that day. Correct the purchase day first, "
    "or check the day it was refunded."
)
REFUND_BEFORE_ACQUISITION = (
    "This copy was acquired after that day. Correct the copy's acquired day "
    "first, or check the day the purchase was refunded."
)
PURCHASE_AFTER_REFUND = (
    "This purchase was refunded before that day. Correct the refund first, "
    "or check the day it was bought."
)
REFUNDED_BEFORE_BOUGHT = (
    "This purchase was refunded before it was bought. Check the days."
)
REFUND_OVERTAKEN = "This refund changed since; nothing was undone."
MOVE_A_REFUNDED_PURCHASE = (
    "This purchase was refunded. Take the refund back before moving it to another copy."
)

KIND_WORDS: frozenset[str] = frozenset(get_args(PurchaseKindValue.__value__))
_AMOUNT = cast(models.DecimalField, Purchase._meta.get_field("amount"))
#: One cent, at the column's scale.
CENT = Decimal(1).scaleb(-_AMOUNT.decimal_places)
#: The largest amount the column holds.
LARGEST_AMOUNT = (
    Decimal(10).scaleb(_AMOUNT.max_digits - _AMOUNT.decimal_places - 1) - CENT
)
_CURRENCY = re.compile(CURRENCY_CODE)


class StatedPrice(NamedTuple):
    """Amount and currency; blank exactly when unknown."""

    amount: Decimal | None
    currency: str

    def normalized(self) -> StatedPrice:
        """One spelling, so restatements fingerprint alike."""
        return self._replace(currency=self.currency.strip().upper())


UNKNOWN_PRICE = StatedPrice(None, "")
#: A purchase with no stated day.
UNDATED_PURCHASE = ActStatement(None, "")


def check_kind(kind: str) -> PurchaseKindValue:
    """The payload's kind word, or a refusal."""
    if kind not in KIND_WORDS:
        raise CommandRejected(
            f"{kind!r} is not a purchase kind.", sentence=UNKNOWN_KIND
        )
    return cast(PurchaseKindValue, kind)


def check_name(name: str) -> str:
    """The name, or a refusal."""
    if not storable(name):
        raise CommandRejected(
            "This name holds a NUL byte or a lone surrogate, which JSONB cannot store.",
            sentence=UNSTORABLE_NAME,
        )
    if len(name) > NAME_LENGTH:
        raise CommandRejected(
            f"A name of {len(name)} characters exceeds {NAME_LENGTH}.",
            sentence=LONG_NAME,
        )
    return name


def check_price(price: StatedPrice) -> StatedPrice:
    """The stated price, or a refusal."""
    amount, currency = price
    if amount is None:
        if currency:
            raise CommandRejected(
                f"Currency {currency!r} is stated without an amount.",
                sentence=CURRENCY_WITHOUT_AMOUNT,
            )
        return price
    if not amount.is_finite():
        raise CommandRejected(f"Amount {amount} is no number.", sentence=NOT_AN_AMOUNT)
    if amount.is_signed():
        raise CommandRejected(f"Amount {amount} is signed.", sentence=SIGNED_AMOUNT)
    #: Before quantize, which overflows past 28 digits.
    if amount > LARGEST_AMOUNT:
        raise CommandRejected(
            f"Amount {amount} exceeds {LARGEST_AMOUNT}.", sentence=TOO_LARGE_AMOUNT
        )
    if amount != amount.quantize(CENT):
        raise CommandRejected(
            f"Amount {amount} holds more than two places.",
            sentence=TOO_PRECISE_AMOUNT,
        )
    if not _CURRENCY.fullmatch(currency):
        raise CommandRejected(
            f"Amount {amount} is stated with currency {currency!r}.",
            sentence=AMOUNT_WITHOUT_CURRENCY,
        )
    return price


def _refuse_under_a_removed_copy(entry: LibraryEntry) -> None:
    #: Under dispatch's lock; the marks cannot move.
    if entry.removed_at is not None:
        raise CommandRejected(
            f"This library removed entry {entry.pk}, so no purchase names it.",
            sentence=ENTRY_REMOVED,
        )
    if entry.player_game.removed_at is not None:
        raise CommandRejected(
            f"This library removed the game behind entry {entry.pk}, so no "
            "purchase names it.",
            sentence=PLAYER_GAME_REMOVED,
        )


def _refuse_a_hidden_copy(entry: LibraryEntry) -> None:
    """Refuse a copy no read shows."""
    _refuse_under_a_removed_copy(entry)
    if not Release.objects.alive().filter(pk=entry.release_id).exists():
        raise CommandRejected(
            f"Release {entry.release_id} or a parent is removed, so no "
            f"purchase names entry {entry.pk}.",
            sentence=RELEASE_REMOVED,
        )


def _refuse_a_removed_purchase(purchase: Purchase) -> None:
    if purchase.removed_at is not None:
        raise CommandRejected(
            f"This library removed purchase {purchase.pk}, so it states no "
            "further facts about it.",
            sentence=PURCHASE_REMOVED,
        )


def _refuse_a_live_act(purchase: Purchase) -> None:
    """Refuse a removed purchase, or hidden copy."""
    _refuse_a_removed_purchase(purchase)
    _refuse_a_hidden_copy(purchase.entry)


def _held_copy(context: CommandContext, entry_id: uuid.UUID) -> LibraryEntry:
    """A copy every read shows."""
    entry = library_entry_row(context, entry_id)
    _refuse_a_hidden_copy(entry)
    return entry


class RefundTakenBack(StrEnum):
    """A refund statement that voids it."""

    #: A string the fingerprint can encode.
    TAKEN_BACK = "taken_back"


TAKE_REFUND_BACK: Final = RefundTakenBack.TAKEN_BACK
type RefundStatement = ActStatement | RefundTakenBack


class StandingRefund(NamedTuple):
    """The refund a statement leaves standing."""

    when: TemporalValue | None
    #: The statement states it, not the row.
    is_new: bool


def _standing_refund(
    purchase: Purchase, refund: RefundStatement | None
) -> StandingRefund | None:
    held = stated(purchase, PURCHASE_REFUND)
    match refund:
        case RefundTakenBack():
            return None
        case ActStatement():
            return StandingRefund(
                refund.when, is_new=held is None or held.when != refund.when
            )
        case None if held is None:
            return None
        case None:
            return StandingRefund(held.when, is_new=False)


def _refuse_a_reversed_refund(
    purchase: Purchase,
    *,
    purchased: TemporalValue | None,
    purchase_day_is_new: bool,
    refund: StandingRefund | None,
) -> None:
    """Refuse a purchase refunded before bought."""
    if refund is None or not (purchase_day_is_new or refund.is_new):
        return
    if not certainly_reversed(earlier=purchased, later=refund.when):
        return
    if purchase_day_is_new and refund.is_new:
        sentence = REFUNDED_BEFORE_BOUGHT
    elif refund.is_new:
        sentence = REFUND_BEFORE_PURCHASE
    else:
        sentence = PURCHASE_AFTER_REFUND
    raise CommandRejected(
        f"The statement about purchase {purchase.pk} refunds it before it was bought.",
        sentence=sentence,
    )


def _refuse_a_new_refund_before_purchase(
    purchase: Purchase,
    *,
    refunded: TemporalValue | None,
    purchased: TemporalValue | None,
) -> None:
    _refuse_a_reversed_refund(
        purchase,
        purchased=purchased,
        purchase_day_is_new=False,
        refund=StandingRefund(refunded, is_new=True),
    )


def _refuse_an_end_before_the_acquisition(
    purchase: Purchase, copy: LibraryEntry, *, refunded: TemporalValue | None
) -> None:
    if certainly_reversed(earlier=copy.acquired, later=refunded):
        raise CommandRejected(
            f"Entry {copy.pk} was acquired after the refund of purchase "
            f"{purchase.pk}, which would end its access before it begins.",
            sentence=REFUND_BEFORE_ACQUISITION,
        )


def _day_correction(
    purchase: Purchase, statement: ActStatement, *, refund: StandingRefund | None
) -> Sequence[NewEvent] | Unchanged:
    def before_event() -> None:
        _refuse_a_live_act(purchase)
        _refuse_a_reversed_refund(
            purchase,
            purchased=statement.when,
            purchase_day_is_new=True,
            refund=refund,
        )

    return correct_opening_endpoint(
        purchase,
        PURCHASE_DAY,
        statement,
        same_correction=SAME_DAY,
        before_event=before_event,
    )


def _refund_sentences(purchase_id: uuid.UUID) -> EndpointSentences:
    return EndpointSentences(
        already_stated=Rejection(
            f"Purchase {purchase_id} already states a refund. "
            "CorrectPurchaseRefund states a better one.",
            "This purchase already has a refund recorded. Correct the one it "
            "has instead of adding another.",
        ),
        nothing_to_correct=Rejection(
            f"Purchase {purchase_id} states no refund, so there is nothing to "
            "correct. A first statement is RefundPurchase.",
            "This purchase has no refund to correct. Record the refund first.",
        ),
        same_statement="This purchase already states that refund.",
        same_correction="This correction states the refund the purchase states.",
        nothing_to_void=f"Purchase {purchase_id} states no refund to take back.",
    )


def refund_ends(kind: str, access: str, *, ended: bool) -> bool:
    """A game's refund ends an owned, held copy."""
    return kind == PurchaseKind.GAME and access == EntryAccess.OWNED and not ended


def refund_ends_the_copy(kind: PurchaseKindValue, entry: LibraryEntry) -> bool:
    """The refund rule, read off a copy."""
    return refund_ends(
        kind, entry.access, ended=stated(entry, ENTRY_ACCESS_END) is not None
    )


def _copy_end(
    spec: EventSpec[LibraryEntryAccessEndPayload],
    copy_id: uuid.UUID,
    when: TemporalValue | None,
) -> NewEvent:
    """The copy's end: way refunded, refund's day.

    It stands in for EndEntryAccess, CorrectEntryAccessEnd and
    VoidEntryAccessEnd; a rule added there belongs here too.
    """
    return spec.new(
        aggregate_id=copy_id,
        effective_time=when,
        payload={"way": EndWay.REFUNDED.value, "note": ""},
    )


def _refund_statement(
    purchase: Purchase,
    statement: ActStatement,
    *,
    kind: PurchaseKindValue,
    copy: LibraryEntry,
    purchased: TemporalValue | None,
) -> Sequence[NewEvent] | Unchanged:
    """The first refund; a game's copy ends."""
    ends_the_copy = refund_ends_the_copy(kind, copy)

    def before_event() -> None:
        _refuse_a_live_act(purchase)
        _refuse_a_new_refund_before_purchase(
            purchase, refunded=statement.when, purchased=purchased
        )
        if ends_the_copy:
            _refuse_an_end_before_the_acquisition(
                purchase, copy, refunded=statement.when
            )

    events = state_endpoint(
        purchase,
        PURCHASE_REFUND,
        statement,
        sentences=_refund_sentences(purchase.pk),
        before_event=before_event,
    )
    if isinstance(events, Unchanged) or not ends_the_copy:
        return events
    return [
        *events,
        _copy_end(ENTRY_ACCESS_END_EVENTS.stated, copy.pk, statement.when),
    ]


def _refund_correction(
    context: CommandContext,
    purchase: Purchase,
    statement: ActStatement,
    *,
    purchased: TemporalValue | None,
) -> Sequence[NewEvent] | Unchanged:
    """A better refund; a new day moves its end."""
    moves_the_end = statement.when != purchase.refunded and refund_owns_the_end(
        context.library, purchase
    )

    def before_event() -> None:
        _refuse_a_live_act(purchase)
        _refuse_a_new_refund_before_purchase(
            purchase, refunded=statement.when, purchased=purchased
        )
        if moves_the_end:
            _refuse_an_end_before_the_acquisition(
                purchase, purchase.entry, refunded=statement.when
            )

    events = correct_endpoint(
        purchase,
        PURCHASE_REFUND,
        statement,
        sentences=_refund_sentences(purchase.pk),
        before_event=before_event,
    )
    if isinstance(events, Unchanged) or not moves_the_end:
        return events
    return [
        *events,
        _copy_end(ENTRY_ACCESS_END_EVENTS.corrected, purchase.entry_id, statement.when),
    ]


def _refund_void(
    context: CommandContext, purchase: Purchase
) -> Sequence[NewEvent] | Unchanged:
    """The refund taken back, and its end."""
    takes_the_end = refund_owns_the_end(context.library, purchase)

    def before_event() -> None:
        #: A removed Release never blocks it.
        _refuse_a_removed_purchase(purchase)
        _refuse_under_a_removed_copy(purchase.entry)

    events = void_endpoint(
        purchase,
        PURCHASE_REFUND,
        sentences=_refund_sentences(purchase.pk),
        before_event=before_event,
    )
    if isinstance(events, Unchanged) or not takes_the_end:
        return events
    return [
        *events,
        ENTRY_ACCESS_END_EVENTS.voided.new(aggregate_id=purchase.entry_id, payload={}),
    ]


def _restated_refund(
    context: CommandContext,
    purchase: Purchase,
    refund: RefundStatement,
    *,
    kind: PurchaseKindValue,
    copy: LibraryEntry,
    purchased: TemporalValue | None,
) -> Sequence[NewEvent] | Unchanged:
    """The act, chosen under the lock by presence."""
    match refund:
        case RefundTakenBack():
            return _refund_void(context, purchase)
        case ActStatement() if stated(purchase, PURCHASE_REFUND) is None:
            return _refund_statement(
                purchase, refund, kind=kind, copy=copy, purchased=purchased
            )
        case ActStatement():
            return _refund_correction(context, purchase, refund, purchased=purchased)
        case unknown:
            raise TypeError(f"{unknown!r} states no refund.")


@dataclass(frozen=True, slots=True)
class RecordPurchase(Command):
    """State a purchase of a copy, new or held."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_RECORD
    #: A held copy's key, or a new copy.
    copy: uuid.UUID | EntryStatement
    kind: PurchaseKindValue
    name: str = ""
    price: StatedPrice = UNKNOWN_PRICE
    note: str = ""
    purchased: ActStatement = UNDATED_PURCHASE

    def __post_init__(self) -> None:
        #: One spelling, so restatements fingerprint alike.
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "note", self.note.strip())
        object.__setattr__(self, "price", self.price.normalized())
        object.__setattr__(self, "purchased", normalized(self.purchased))
        if isinstance(self.copy, EntryStatement):
            object.__setattr__(self, "copy", self.copy.normalized())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        return purchase_creation_events(
            context,
            copy=self.copy,
            kind=self.kind,
            name=self.name,
            price=self.price,
            note=self.note,
            purchased=self.purchased,
        )


def purchase_creation_events(
    context: CommandContext,
    *,
    copy: uuid.UUID | EntryStatement,
    kind: PurchaseKindValue,
    name: str = "",
    price: StatedPrice = UNKNOWN_PRICE,
    note: str = "",
    purchased: ActStatement = UNDATED_PURCHASE,
    purchase_id: uuid.UUID | None = None,
) -> list[NewEvent]:
    """A purchase's creation, every check included."""
    checked_kind = check_kind(kind)
    checked_name = check_name(name)
    checked_price = check_price(price)
    check_note(note)
    check_note(purchased.note)
    match copy:
        case EntryStatement() as statement:
            events, reference = entry_creation_events(context, statement)
        case uuid.UUID() as entry_id:
            events = ()
            reference = capture_reference(_held_copy(context, entry_id))
        case unknown:
            raise TypeError(f"{unknown!r} names no copy.")
    return [
        *events,
        purchase_created(
            reference,
            kind=checked_kind,
            name=checked_name,
            amount=checked_price.amount,
            currency=checked_price.currency,
            note=note,
            purchased=purchased.when,
            purchase_note=purchased.note,
            purchase_id=purchase_id,
        ),
    ]


@dataclass(frozen=True, slots=True)
class DescribePurchase(Command):
    """State kind, name, price, note, copy, day, refund."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_DESCRIBE
    purchase_id: uuid.UUID
    kind: PurchaseKindValue | None = None
    name: str | None = None
    price: StatedPrice | None = None
    note: str | None = None
    entry_id: uuid.UUID | None = None
    purchased: ActStatement | None = None
    refund: RefundStatement | None = None

    def __post_init__(self) -> None:
        if self.name is not None:
            object.__setattr__(self, "name", self.name.strip())
        if self.note is not None:
            object.__setattr__(self, "note", self.note.strip())
        if self.price is not None:
            object.__setattr__(self, "price", self.price.normalized())
        if self.purchased is not None:
            object.__setattr__(self, "purchased", normalized(self.purchased))
        if isinstance(self.refund, ActStatement):
            object.__setattr__(self, "refund", normalized(self.refund))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        kind = None if self.kind is None else check_kind(self.kind)
        name = None if self.name is None else check_name(self.name)
        price = None if self.price is None else check_price(self.price)
        if self.note is not None:
            check_note(self.note)
        if self.purchased is not None:
            check_note(self.purchased.note)
        if isinstance(self.refund, ActStatement):
            check_note(self.refund.note)
        purchase = library_purchase_row(context, self.purchase_id)
        #: The facts once this statement lands.
        final_kind = cast(PurchaseKindValue, purchase.kind) if kind is None else kind
        final_purchased = (
            purchase.purchased if self.purchased is None else self.purchased.when
        )
        events: list[NewEvent] = []
        if kind is not None and kind != purchase.kind:
            events.append(purchase_kind_changed(purchase.pk, kind))
        if name is not None and name != purchase.name:
            events.append(purchase_name_changed(purchase.pk, name))
        if price is not None and price != StatedPrice(
            purchase.amount, purchase.currency
        ):
            events.append(
                purchase_price_changed(
                    purchase.pk, amount=price.amount, currency=price.currency
                )
            )
        if self.note is not None and self.note != purchase.note:
            events.append(purchase_note_changed(purchase.pk, self.note))
        copy = purchase.entry
        if self.entry_id is not None and self.entry_id != purchase.entry_id:
            #: The purchase's own sentence names the remedy.
            _refuse_a_live_act(purchase)
            if stated(purchase, PURCHASE_REFUND) is not None and not isinstance(
                self.refund, RefundTakenBack
            ):
                raise CommandRejected(
                    f"Purchase {purchase.pk} states a refund, whose end stays "
                    f"on entry {purchase.entry_id}.",
                    sentence=MOVE_A_REFUNDED_PURCHASE,
                )
            copy = _held_copy(context, self.entry_id)
            if copy.player_game_id != purchase.entry.player_game_id:
                raise CommandRejected(
                    f"Entry {copy.pk} records player game {copy.player_game_id}, "
                    f"and purchase {purchase.pk} records player game "
                    f"{purchase.entry.player_game_id}.",
                    sentence=ENTRY_OF_ANOTHER_GAME,
                )
            events.append(purchase_entry_changed(purchase.pk, capture_reference(copy)))
        if self.purchased is not None:
            correction = _day_correction(
                purchase,
                self.purchased,
                refund=_standing_refund(purchase, self.refund),
            )
            if not isinstance(correction, Unchanged):
                events.extend(correction)
        if events:
            _refuse_a_live_act(purchase)
        if self.refund is not None:
            refund = _restated_refund(
                context,
                purchase,
                self.refund,
                kind=final_kind,
                copy=copy,
                purchased=final_purchased,
            )
            if not isinstance(refund, Unchanged):
                events.extend(refund)
        if not events:
            return Unchanged("This purchase already states that.")
        return events


@dataclass(frozen=True, slots=True)
class RemovePurchase(Command):
    """Mark a purchase removed; the stream keeps it."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_REMOVE
    purchase_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        purchase = library_purchase_row(context, self.purchase_id)
        if purchase.removed_at is not None:
            return Unchanged(f"This library already removed purchase {purchase.pk}.")
        _refuse_under_a_removed_copy(purchase.entry)
        return [purchase_removed(purchase.pk)]


@dataclass(frozen=True, slots=True)
class RestorePurchase(Command):
    """Put a removed purchase back."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_RESTORE
    purchase_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        purchase = library_purchase_row(context, self.purchase_id)
        if purchase.removed_at is None:
            return Unchanged(f"Purchase {purchase.pk} is already in this library.")
        #: Restored under a removed release, nothing shows.
        _refuse_a_hidden_copy(purchase.entry)
        return [purchase_restored(purchase.pk)]


@dataclass(frozen=True, slots=True)
class RefundPurchase(Command):
    """Refunded; a game's owned, held copy ends."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_REFUND
    purchase_id: uuid.UUID
    statement: ActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        check_note(self.statement.note)
        purchase = library_purchase_row(context, self.purchase_id)
        return _refund_statement(
            purchase,
            self.statement,
            kind=cast(PurchaseKindValue, purchase.kind),
            copy=purchase.entry,
            purchased=purchase.purchased,
        )


@dataclass(frozen=True, slots=True)
class CorrectPurchaseRefund(Command):
    """Restate a refund; a new day moves its end."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_CORRECT_REFUND
    purchase_id: uuid.UUID
    statement: ActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        check_note(self.statement.note)
        purchase = library_purchase_row(context, self.purchase_id)
        return _refund_correction(
            context, purchase, self.statement, purchased=purchase.purchased
        )


@dataclass(frozen=True, slots=True)
class VoidPurchaseRefund(Command):
    """Take back a refund, and its own end."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_VOID_REFUND
    purchase_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        return _refund_void(context, library_purchase_row(context, self.purchase_id))


@dataclass(frozen=True, slots=True)
class UndoPurchaseRefund(Command):
    """Void a refund still standing as latest."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_UNDO_REFUND
    purchase_id: uuid.UUID
    #: The refund event this Undo takes back.
    refunded_at: EventSequence

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        purchase = library_purchase_row(context, self.purchase_id)
        _refuse_an_overtaken_refund(context, purchase, self.refunded_at)
        return _refund_void(context, purchase)


def _refuse_an_overtaken_refund(
    context: CommandContext, purchase: Purchase, refunded_at: EventSequence
) -> None:
    latest = latest_refund_act(context.library, purchase.pk)
    if (
        latest is None
        or latest.sequence != refunded_at
        or latest.event_type != PURCHASE_REFUND_EVENTS.stated.event_type
    ):
        raise CommandRejected(
            f"Purchase {purchase.pk}'s latest refund act is not the refund "
            f"at sequence {refunded_at}.",
            sentence=REFUND_OVERTAKEN,
        )
