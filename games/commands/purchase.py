"""Commands on one purchase."""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from typing import ClassVar, NamedTuple, cast, get_args

from games.commands.endpoint import (
    ActStatement,
    correct_opening_endpoint,
    normalized,
)
from games.commands.libraryentry import EntryStatement, entry_creation_events
from games.commands.scope import library_entry_row, library_purchase_row
from games.endpoints import PURCHASE_DAY
from games.events.dispatch import Command, CommandContext, CommandName, CommandRejected
from games.events.purchase import (
    PurchaseKindValue,
    purchase_amount_changed,
    purchase_created,
    purchase_entry_changed,
    purchase_kind_changed,
    purchase_name_changed,
    purchase_note_changed,
    purchase_removed,
    purchase_restored,
)
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent, Unchanged
from games.models import LibraryEntry, Purchase

UNKNOWN_KIND = "Choose one of the listed purchase kinds."
ONE_COPY = "Name the copy this purchase paid for, or describe a new one."
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

KIND_WORDS: frozenset[str] = frozenset(get_args(PurchaseKindValue.__value__))
#: The largest amount `Purchase.amount` holds.
LARGEST_AMOUNT = Decimal("9999999999.99")
CENT = Decimal("0.01")
_CURRENCY = re.compile(r"[A-Z]{3}")


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


def check_price(price: StatedPrice) -> StatedPrice:
    """The stated price, or a refusal.

    Never quantises: a person states cents.
    """
    amount, currency = price
    if amount is None:
        if currency:
            raise CommandRejected(
                f"Currency {currency!r} is stated without an amount.",
                sentence=CURRENCY_WITHOUT_AMOUNT,
            )
        return price
    #: The fingerprint refuses a NaN first.
    if amount.is_signed():
        raise CommandRejected(f"Amount {amount} is signed.", sentence=SIGNED_AMOUNT)
    if amount != amount.quantize(CENT):
        raise CommandRejected(
            f"Amount {amount} holds more than two places.",
            sentence=TOO_PRECISE_AMOUNT,
        )
    if amount > LARGEST_AMOUNT:
        raise CommandRejected(
            f"Amount {amount} exceeds {LARGEST_AMOUNT}.", sentence=TOO_LARGE_AMOUNT
        )
    if not _CURRENCY.fullmatch(currency):
        raise CommandRejected(
            f"Amount {amount} is stated with currency {currency!r}.",
            sentence=AMOUNT_WITHOUT_CURRENCY,
        )
    return price


def _refuse_a_dead_entry(entry: LibraryEntry) -> None:
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


def _refuse_a_live_act(purchase: Purchase) -> None:
    """Refuse a removed purchase, copy or game."""
    if purchase.removed_at is not None:
        raise CommandRejected(
            f"This library removed purchase {purchase.pk}, so it states no "
            "further facts about it.",
            sentence=PURCHASE_REMOVED,
        )
    _refuse_a_dead_entry(purchase.entry)


def _named_entry(context: CommandContext, entry_id: uuid.UUID) -> LibraryEntry:
    """A live entry under a live game."""
    entry = library_entry_row(context, entry_id)
    _refuse_a_dead_entry(entry)
    return entry


@dataclass(frozen=True, slots=True)
class RecordPurchase(Command):
    """State a purchase of a copy, new or held."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_RECORD
    kind: str
    entry_id: uuid.UUID | None = None
    new_entry: EntryStatement | None = None
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
        if self.new_entry is not None:
            object.__setattr__(self, "new_entry", self.new_entry.normalized())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        kind = check_kind(self.kind)
        price = check_price(self.price)
        match self.entry_id, self.new_entry:
            case uuid.UUID() as entry_id, None:
                events: list[NewEvent] = []
                reference = capture_reference(_named_entry(context, entry_id))
            case None, EntryStatement() as statement:
                created = entry_creation_events(context, statement)
                events, reference = created.events, created.reference
            case _:
                raise CommandRejected(
                    "A purchase names entry_id or new_entry, exactly one.",
                    sentence=ONE_COPY,
                )
        events.append(
            purchase_created(
                reference,
                kind=kind,
                name=self.name,
                amount=price.amount,
                currency=price.currency,
                note=self.note,
                purchased=self.purchased.when,
                purchase_note=self.purchased.note,
            )
        )
        return events


@dataclass(frozen=True, slots=True)
class DescribePurchase(Command):
    """State kind, name, price, note, copy, or several."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_DESCRIBE
    purchase_id: uuid.UUID
    kind: str | None = None
    name: str | None = None
    price: StatedPrice | None = None
    note: str | None = None
    entry_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.name is not None:
            object.__setattr__(self, "name", self.name.strip())
        if self.note is not None:
            object.__setattr__(self, "note", self.note.strip())
        if self.price is not None:
            object.__setattr__(self, "price", self.price.normalized())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        kind = None if self.kind is None else check_kind(self.kind)
        price = None if self.price is None else check_price(self.price)
        purchase = library_purchase_row(context, self.purchase_id)
        events: list[NewEvent] = []
        if kind is not None and kind != purchase.kind:
            events.append(purchase_kind_changed(purchase.pk, kind))
        if self.name is not None and self.name != purchase.name:
            events.append(purchase_name_changed(purchase.pk, self.name))
        if price is not None and price != (purchase.amount, purchase.currency):
            events.append(
                purchase_amount_changed(
                    purchase.pk, amount=price.amount, currency=price.currency
                )
            )
        if self.note is not None and self.note != purchase.note:
            events.append(purchase_note_changed(purchase.pk, self.note))
        if self.entry_id is not None and self.entry_id != purchase.entry_id:
            entry = _named_entry(context, self.entry_id)
            if entry.player_game_id != purchase.entry.player_game_id:
                raise CommandRejected(
                    f"Entry {entry.pk} records player game {entry.player_game_id}, "
                    f"and purchase {purchase.pk} records player game "
                    f"{purchase.entry.player_game_id}.",
                    sentence=ENTRY_OF_ANOTHER_GAME,
                )
            events.append(purchase_entry_changed(purchase.pk, capture_reference(entry)))
        if not events:
            return Unchanged("This purchase already states that.")
        _refuse_a_live_act(purchase)
        return events


@dataclass(frozen=True, slots=True)
class CorrectPurchaseDay(Command):
    """Restate the day of the purchase."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_CORRECT_PURCHASE
    purchase_id: uuid.UUID
    statement: ActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        purchase = library_purchase_row(context, self.purchase_id)
        return correct_opening_endpoint(
            purchase,
            PURCHASE_DAY,
            self.statement,
            same_correction="This correction states the day the purchase states.",
            before_event=partial(_refuse_a_live_act, purchase),
        )


@dataclass(frozen=True, slots=True)
class RemovePurchase(Command):
    """Mark a purchase removed; the stream keeps it."""

    command_name: ClassVar[CommandName] = CommandName.PURCHASE_REMOVE
    purchase_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        purchase = library_purchase_row(context, self.purchase_id)
        if purchase.removed_at is not None:
            return Unchanged(f"This library already removed purchase {purchase.pk}.")
        _refuse_a_dead_entry(purchase.entry)
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
        _refuse_a_dead_entry(purchase.entry)
        return [purchase_restored(purchase.pk)]
