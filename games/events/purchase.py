"""Events on one purchase."""

import uuid
from decimal import Decimal
from typing import Annotated, Literal, TypedDict, cast

from pydantic import AfterValidator, StringConstraints, with_config

from games.events.endpoint import EndpointPayload, opening_endpoint_events
from games.events.playersession import NoteText, stated_note_text
from games.events.references import STRICT_SCHEMA, Reference
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, EventType, NewEvent
from games.models import CURRENCY_CODE, Purchase
from timetracker.temporal import TemporalValue

#: Recorded spelling: the words `Purchase.kind` stores.
type PurchaseKindValue = Literal["game", "season_pass", "battle_pass", "upgrade"]
_AMOUNT = Purchase._meta.get_field("amount")
#: Two places, no sign, e.g. "12.50".
type AmountText = Annotated[
    str,
    StringConstraints(
        pattern=(
            rf"^\d{{1,{_AMOUNT.max_digits - _AMOUNT.decimal_places}}}"
            rf"\.\d{{{_AMOUNT.decimal_places}}}$"
        )
    ),
]
type CurrencyText = Annotated[str, StringConstraints(pattern=f"^{CURRENCY_CODE}$")]
#: The column's length bounds a name.
NAME_LENGTH = cast(int, Purchase._meta.get_field("name").max_length)
type NameText = Annotated[
    str,
    AfterValidator(stated_note_text),
    StringConstraints(max_length=NAME_LENGTH),
]


@with_config(STRICT_SCHEMA)
class PricePayload(TypedDict):
    """A known amount and its currency."""

    amount: AmountText
    currency: CurrencyText


@with_config(STRICT_SCHEMA)
class PurchaseCreatedPayload(TypedDict):
    """First statement; the day is effective_time."""

    entry: Reference
    kind: PurchaseKindValue
    name: NameText
    #: Null is an unknown price.
    price: PricePayload | None
    note: NoteText
    purchase_note: NoteText


@with_config(STRICT_SCHEMA)
class PurchaseKindChangedPayload(TypedDict):
    kind: PurchaseKindValue


@with_config(STRICT_SCHEMA)
class PurchaseNameChangedPayload(TypedDict):
    name: NameText


@with_config(STRICT_SCHEMA)
class PurchaseNoteChangedPayload(TypedDict):
    note: NoteText


@with_config(STRICT_SCHEMA)
class PurchasePriceChangedPayload(TypedDict):
    price: PricePayload | None


@with_config(STRICT_SCHEMA)
class PurchaseEntryChangedPayload(TypedDict):
    entry: Reference


@with_config(STRICT_SCHEMA)
class PurchaseMarkPayload(TypedDict):
    """Removed and restored state nothing more."""


def _spec[PayloadT](
    event_type: EventType, payload: type[PayloadT]
) -> EventSpec[PayloadT]:
    spec = EventSpec(event_type, aggregate_type="purchase", payload=payload)
    DEFAULT_EVENT_TYPES.register(spec)
    return spec


PURCHASE_CREATED = _spec("library.purchase.created", PurchaseCreatedPayload)
PURCHASE_KIND_CHANGED = _spec(
    "library.purchase.kind_changed", PurchaseKindChangedPayload
)
PURCHASE_NAME_CHANGED = _spec(
    "library.purchase.name_changed", PurchaseNameChangedPayload
)
PURCHASE_NOTE_CHANGED = _spec(
    "library.purchase.note_changed", PurchaseNoteChangedPayload
)
PURCHASE_PRICE_CHANGED = _spec(
    "library.purchase.price_changed", PurchasePriceChangedPayload
)
PURCHASE_ENTRY_CHANGED = _spec(
    "library.purchase.entry_changed", PurchaseEntryChangedPayload
)
PURCHASE_REMOVED = _spec("library.purchase.removed", PurchaseMarkPayload)
PURCHASE_RESTORED = _spec("library.purchase.restored", PurchaseMarkPayload)

PURCHASE_DAY_EVENTS = opening_endpoint_events(
    "purchase",
    corrected="library.purchase.purchase_corrected",
    payload=EndpointPayload,
)
PURCHASE_CORRECTED = PURCHASE_DAY_EVENTS.corrected


def amount_text(amount: Decimal) -> str:
    """Canonical text; `str()` may spell 1E+2."""
    return f"{amount:.{_AMOUNT.decimal_places}f}"


def price_payload(amount: Decimal | None, currency: str) -> PricePayload | None:
    """The payload's price; None unknown."""
    if amount is None:
        return None
    return {"amount": amount_text(amount), "currency": currency}


def purchase_created(
    entry: Reference,
    *,
    kind: PurchaseKindValue,
    name: str,
    amount: Decimal | None,
    currency: str,
    note: str,
    purchased: TemporalValue | None,
    purchase_note: str,
    purchase_id: uuid.UUID | None = None,
) -> NewEvent:
    """A new purchase; key minted unless given."""
    return PURCHASE_CREATED.new(
        aggregate_id=uuid.uuid7() if purchase_id is None else purchase_id,
        effective_time=purchased,
        payload={
            "entry": entry,
            "kind": kind,
            "name": name,
            "price": price_payload(amount, currency),
            "note": note,
            "purchase_note": purchase_note,
        },
    )


def purchase_kind_changed(purchase_id: uuid.UUID, kind: PurchaseKindValue) -> NewEvent:
    return PURCHASE_KIND_CHANGED.new(aggregate_id=purchase_id, payload={"kind": kind})


def purchase_name_changed(purchase_id: uuid.UUID, name: str) -> NewEvent:
    return PURCHASE_NAME_CHANGED.new(aggregate_id=purchase_id, payload={"name": name})


def purchase_note_changed(purchase_id: uuid.UUID, note: str) -> NewEvent:
    return PURCHASE_NOTE_CHANGED.new(aggregate_id=purchase_id, payload={"note": note})


def purchase_price_changed(
    purchase_id: uuid.UUID, *, amount: Decimal | None, currency: str
) -> NewEvent:
    return PURCHASE_PRICE_CHANGED.new(
        aggregate_id=purchase_id, payload={"price": price_payload(amount, currency)}
    )


def purchase_entry_changed(purchase_id: uuid.UUID, entry: Reference) -> NewEvent:
    return PURCHASE_ENTRY_CHANGED.new(
        aggregate_id=purchase_id, payload={"entry": entry}
    )


def purchase_corrected(
    purchase_id: uuid.UUID, *, when: TemporalValue | None, note: str
) -> NewEvent:
    return PURCHASE_CORRECTED.new(
        aggregate_id=purchase_id, effective_time=when, payload={"note": note}
    )


def purchase_removed(purchase_id: uuid.UUID) -> NewEvent:
    return PURCHASE_REMOVED.new(aggregate_id=purchase_id, payload={})


def purchase_restored(purchase_id: uuid.UUID) -> NewEvent:
    return PURCHASE_RESTORED.new(aggregate_id=purchase_id, payload={})
