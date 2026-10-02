"""A purchase's facts before a batch."""

import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from games.commands.endpoint import ActStatement
from games.commands.purchase import UNKNOWN_PRICE, StatedPrice
from games.events.purchase import (
    PURCHASE_CORRECTED,
    PURCHASE_CREATED,
    PURCHASE_KIND_CHANGED,
    PURCHASE_NOTE_CHANGED,
    PURCHASE_PRICE_CHANGED,
)
from games.models import LibraryEvent, PurchaseKind, UserLibrary
from games.reads.fact_change import (
    Fact,
    FactChange,
    PayloadKey,
    fact_change,
    payload_fact,
)


def _kind(value: object) -> PurchaseKind | None:
    return PurchaseKind(value) if value in PurchaseKind.values else None


def _note(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _price(value: object) -> StatedPrice | None:
    """Null is unknown; a malformed one None."""
    if value is None:
        return UNKNOWN_PRICE
    if not isinstance(value, dict):
        return None
    amount, currency = value.get("amount"), value.get("currency")
    if not isinstance(amount, str) or not isinstance(currency, str):
        return None
    try:
        return StatedPrice(Decimal(amount), currency)
    except InvalidOperation:
        return None


#: Where each event spells the day's note.
_CREATED_NOTE: Final[PayloadKey] = "purchase_note"
_CORRECTED_NOTE: Final[PayloadKey] = "note"


def _purchased(event: LibraryEvent) -> ActStatement | None:
    """The day is the envelope's."""
    created = event.event_type == PURCHASE_CREATED.event_type
    note = _note(event.payload.get(_CREATED_NOTE if created else _CORRECTED_NOTE))
    return None if note is None else ActStatement(event.effective_time, note)


_KIND = Fact(PURCHASE_CREATED, PURCHASE_KIND_CHANGED, payload_fact("kind", _kind))
_PRICE = Fact(PURCHASE_CREATED, PURCHASE_PRICE_CHANGED, payload_fact("price", _price))
_PURCHASED = Fact(PURCHASE_CREATED, PURCHASE_CORRECTED, _purchased)
_NOTE = Fact(PURCHASE_CREATED, PURCHASE_NOTE_CHANGED, payload_fact("note", _note))


@dataclass(frozen=True, slots=True)
class PurchaseFactChanges:
    """Each fact a batch changed, else None."""

    kind: FactChange[PurchaseKind] | None
    price: FactChange[StatedPrice] | None
    purchased: FactChange[ActStatement] | None
    note: FactChange[str] | None

    @property
    def changed_any(self) -> bool:
        return not (
            self.kind is None
            and self.price is None
            and self.purchased is None
            and self.note is None
        )


def purchase_fact_changes(
    library: UserLibrary, purchase_id: uuid.UUID, batch_id: uuid.UUID
) -> PurchaseFactChanges:
    return PurchaseFactChanges(
        kind=fact_change(_KIND, library, purchase_id, batch_id),
        price=fact_change(_PRICE, library, purchase_id, batch_id),
        purchased=fact_change(_PURCHASED, library, purchase_id, batch_id),
        note=fact_change(_NOTE, library, purchase_id, batch_id),
    )
