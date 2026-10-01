"""Events on one purchase."""

import uuid
from decimal import Decimal
from typing import Annotated, Literal, TypedDict

from pydantic import StringConstraints, with_config

from games.events.endpoint import EndpointPayload, opening_endpoint_events
from games.events.playersession import NoteText
from games.events.references import STRICT_SCHEMA, Reference
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, EventType, NewEvent
from timetracker.temporal import TemporalValue

#: Recorded spelling: the words `Purchase.kind` stores.
type PurchaseKindValue = Literal["game", "season_pass", "battle_pass", "upgrade"]
#: Two places, no sign, e.g. "12.50".
type AmountText = Annotated[str, StringConstraints(pattern=r"^\d{1,10}\.\d{2}$")]
#: Three upper-case letters, or blank.
type CurrencyText = Annotated[str, StringConstraints(pattern=r"^([A-Z]{3})?$")]


@with_config(STRICT_SCHEMA)
class PurchaseCreatedPayload(TypedDict):
    """First statement; the day is effective_time."""

    entry: Reference
    kind: PurchaseKindValue
    name: NoteText
    amount: AmountText | None
    currency: CurrencyText
    note: NoteText
    purchase_note: NoteText


@with_config(STRICT_SCHEMA)
class PurchaseKindChangedPayload(TypedDict):
    kind: PurchaseKindValue


@with_config(STRICT_SCHEMA)
class PurchaseNameChangedPayload(TypedDict):
    name: NoteText


@with_config(STRICT_SCHEMA)
class PurchaseNoteChangedPayload(TypedDict):
    note: NoteText


@with_config(STRICT_SCHEMA)
class PurchaseAmountChangedPayload(TypedDict):
    """Amount and currency are one fact."""

    amount: AmountText | None
    currency: CurrencyText


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
PURCHASE_AMOUNT_CHANGED = _spec(
    "library.purchase.amount_changed", PurchaseAmountChangedPayload
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


def amount_text(amount: Decimal | None) -> str | None:
    """Canonical text; `str()` may spell 1E+2."""
    return None if amount is None else f"{amount:.2f}"


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
            "amount": amount_text(amount),
            "currency": currency,
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


def purchase_amount_changed(
    purchase_id: uuid.UUID, *, amount: Decimal | None, currency: str
) -> NewEvent:
    return PURCHASE_AMOUNT_CHANGED.new(
        aggregate_id=purchase_id,
        payload={"amount": amount_text(amount), "currency": currency},
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
