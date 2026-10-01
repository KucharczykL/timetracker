"""Commands on one purchase."""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, NamedTuple, cast, get_args

from django.db import models

from games.commands.endpoint import (
    ActStatement,
    correct_opening_endpoint,
    normalized,
)
from games.commands.libraryentry import (
    EntryStatement,
    entry_creation_events,
    refuse_a_removed_release,
)
from games.commands.scope import library_entry_row, library_purchase_row
from games.endpoints import PURCHASE_DAY
from games.events.dispatch import Command, CommandContext, CommandName, CommandRejected
from games.events.purchase import (
    NAME_LENGTH,
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
from games.events.vocabulary import NewEvent, Unchanged
from games.models import CURRENCY_CODE, LibraryEntry, Purchase

UNKNOWN_KIND = "Choose one of the listed purchase kinds."
LONG_NAME = f"Keep the name within {NAME_LENGTH} characters."
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
ENTRY_OF_ANOTHER_GAME = (
    "That copy belongs to another game. Choose a copy of this purchase's game."
)
SAME_DAY = "This correction states the day the purchase states."

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
    """Amount and currency; None amount unknown."""

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
    refuse_a_removed_release(entry.release)


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


def _day_correction(
    purchase: Purchase, statement: ActStatement
) -> Sequence[NewEvent] | Unchanged:
    return correct_opening_endpoint(
        purchase,
        PURCHASE_DAY,
        statement,
        same_correction=SAME_DAY,
        before_event=lambda: _refuse_a_live_act(purchase),
    )


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
        kind = check_kind(self.kind)
        name = check_name(self.name)
        price = check_price(self.price)
        match self.copy:
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
                kind=kind,
                name=name,
                amount=price.amount,
                currency=price.currency,
                note=self.note,
                purchased=self.purchased.when,
                purchase_note=self.purchased.note,
            ),
        ]


@dataclass(frozen=True, slots=True)
class DescribePurchase(Command):
    """State kind, name, price, note, copy, day."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_DESCRIBE
    purchase_id: uuid.UUID
    kind: PurchaseKindValue | None = None
    name: str | None = None
    price: StatedPrice | None = None
    note: str | None = None
    entry_id: uuid.UUID | None = None
    purchased: ActStatement | None = None

    def __post_init__(self) -> None:
        if self.name is not None:
            object.__setattr__(self, "name", self.name.strip())
        if self.note is not None:
            object.__setattr__(self, "note", self.note.strip())
        if self.price is not None:
            object.__setattr__(self, "price", self.price.normalized())
        if self.purchased is not None:
            object.__setattr__(self, "purchased", normalized(self.purchased))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        kind = None if self.kind is None else check_kind(self.kind)
        name = None if self.name is None else check_name(self.name)
        price = None if self.price is None else check_price(self.price)
        purchase = library_purchase_row(context, self.purchase_id)
        events: list[NewEvent] = []
        if kind is not None and kind != purchase.kind:
            events.append(purchase_kind_changed(purchase.pk, kind))
        if name is not None and name != purchase.name:
            events.append(purchase_name_changed(purchase.pk, name))
        if price is not None and price != (purchase.amount, purchase.currency):
            events.append(
                purchase_price_changed(
                    purchase.pk, amount=price.amount, currency=price.currency
                )
            )
        if self.note is not None and self.note != purchase.note:
            events.append(purchase_note_changed(purchase.pk, self.note))
        if self.entry_id is not None and self.entry_id != purchase.entry_id:
            #: The purchase's own sentence names the remedy.
            _refuse_a_live_act(purchase)
            entry = _held_copy(context, self.entry_id)
            if entry.player_game_id != purchase.entry.player_game_id:
                raise CommandRejected(
                    f"Entry {entry.pk} records player game {entry.player_game_id}, "
                    f"and purchase {purchase.pk} records player game "
                    f"{purchase.entry.player_game_id}.",
                    sentence=ENTRY_OF_ANOTHER_GAME,
                )
            events.append(purchase_entry_changed(purchase.pk, capture_reference(entry)))
        if self.purchased is not None:
            correction = _day_correction(purchase, self.purchased)
            if not isinstance(correction, Unchanged):
                events.extend(correction)
        if not events:
            return Unchanged("This purchase already states that.")
        _refuse_a_live_act(purchase)
        return events


@dataclass(frozen=True, slots=True)
class CorrectPurchase(Command):
    """Restate the day of the purchase."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_CORRECT_PURCHASE
    purchase_id: uuid.UUID
    statement: ActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        purchase = library_purchase_row(context, self.purchase_id)
        return _day_correction(purchase, self.statement)


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
