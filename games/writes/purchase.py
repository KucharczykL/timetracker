"""Purchase writes; refusals become answers."""

import uuid
from enum import StrEnum
from typing import NamedTuple

from django.contrib.auth.models import User

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement
from games.commands.purchase import (
    TAKE_REFUND_BACK,
    DescribePurchase,
    RecordPurchase,
    RefundStatement,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
)
from games.events.dispatch import Command, CommandOutcome, CommandResult, dispatch
from games.events.idempotency import IdempotencyKey
from games.events.libraryentry import ENTRY_ACCESS_END_EVENTS, LIBRARYENTRY_CREATED
from games.events.playergame import PLAYERGAME_CREATED
from games.events.purchase import (
    PURCHASE_CREATED,
    PURCHASE_REFUND_EVENTS,
    PurchaseKindValue,
)
from games.events.vocabulary import EventType
from games.models import Purchase
from games.reads.events import dispatched_events
from games.writes.answers import SubjectNoun, answered
from games.writes.endpoint import KEEP, Keep

SUBJECT: SubjectNoun = "purchase"


class PurchaseDraft(NamedTuple):
    """What a creation states."""

    #: A held copy's key, or a new copy.
    copy: uuid.UUID | EntryStatement
    kind: PurchaseKindValue
    name: str
    price: StatedPrice
    note: str
    purchased: ActStatement


class RecordedPurchase(NamedTuple):
    """What a creation answers."""

    purchase_id: uuid.UUID
    entry_id: uuid.UUID
    #: The dispatch recorded a new copy.
    created_the_entry: bool
    #: The dispatch tracked an untracked game.
    tracked_the_game: bool
    #: A repeated key answered the first dispatch.
    replayed: bool


def _dispatch(
    command: Command,
    *,
    actor: User,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> CommandResult:
    return dispatch(
        command,
        actor=actor,
        library=actor.library,
        #: Caller's key else fresh; blank refused.
        idempotency_key=(
            str(uuid.uuid7()) if idempotency_key is None else idempotency_key
        ),
        correlation_id=correlation_id,
    )


def record_purchase(
    actor: User,
    draft: PurchaseDraft,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> RecordedPurchase:
    """State a purchase; answer its ids."""
    with answered(SUBJECT):
        result = _dispatch(
            RecordPurchase(
                copy=draft.copy,
                kind=draft.kind,
                name=draft.name,
                price=draft.price,
                note=draft.note,
                purchased=draft.purchased,
            ),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    event_by_type = {event.event_type: event for event in dispatched_events(result)}
    created = event_by_type.get(PURCHASE_CREATED.event_type)
    if created is None:
        raise RuntimeError(
            f"Dispatch {result.stream_id} {result.sequences} appended no "
            f"{PURCHASE_CREATED.event_type}."
        )
    return RecordedPurchase(
        purchase_id=created.aggregate_id,
        entry_id=uuid.UUID(created.payload["entry"]["id"]),
        created_the_entry=LIBRARYENTRY_CREATED.event_type in event_by_type,
        tracked_the_game=PLAYERGAME_CREATED.event_type in event_by_type,
        replayed=result.outcome is CommandOutcome.REPLAYED,
    )


class CopyEnd(StrEnum):
    """What a refund act did to the copy's end."""

    ENDED = "ended"
    MOVED = "moved"
    TAKEN_BACK = "taken_back"
    #: Not the refund's, or not due.
    LEFT = "left"


_COPY_END_BY_TYPE: dict[EventType, CopyEnd] = {
    ENTRY_ACCESS_END_EVENTS.stated.event_type: CopyEnd.ENDED,
    ENTRY_ACCESS_END_EVENTS.corrected.event_type: CopyEnd.MOVED,
    ENTRY_ACCESS_END_EVENTS.voided.event_type: CopyEnd.TAKEN_BACK,
}
_REFUND_ACTS = frozenset(
    (
        PURCHASE_REFUND_EVENTS.stated.event_type,
        PURCHASE_REFUND_EVENTS.corrected.event_type,
        PURCHASE_REFUND_EVENTS.voided.event_type,
    )
)


class RestatedPurchase(NamedTuple):
    """What a restatement answers."""

    appended: bool
    #: None where no refund act was appended.
    copy_end: CopyEnd | None


def restate_purchase(
    actor: User,
    purchase: Purchase,
    *,
    kind: PurchaseKindValue | None = None,
    name: str | None = None,
    price: StatedPrice | None = None,
    note: str | None = None,
    entry_id: uuid.UUID | None = None,
    purchased: ActStatement | None = None,
    refund: ActStatement | None | Keep = KEEP,
    correlation_id: uuid.UUID,
) -> RestatedPurchase:
    """One dispatch; KEEP keeps, None voids."""
    with answered(SUBJECT):
        result = _dispatch(
            DescribePurchase(
                purchase_id=purchase.pk,
                kind=kind,
                name=name,
                price=price,
                note=note,
                entry_id=entry_id,
                purchased=purchased,
                refund=_refund_statement(refund),
            ),
            actor=actor,
            correlation_id=correlation_id,
        )
    if result.outcome is not CommandOutcome.APPENDED:
        return RestatedPurchase(appended=False, copy_end=None)
    types = {event.event_type for event in dispatched_events(result)}
    if not types & _REFUND_ACTS:
        return RestatedPurchase(appended=True, copy_end=None)
    copy_ends = [_COPY_END_BY_TYPE[name] for name in types & _COPY_END_BY_TYPE.keys()]
    return RestatedPurchase(
        appended=True, copy_end=copy_ends[0] if copy_ends else CopyEnd.LEFT
    )


def _refund_statement(refund: ActStatement | None | Keep) -> RefundStatement | None:
    """The command's spelling of the write's."""
    match refund:
        case Keep():
            return None
        case None:
            return TAKE_REFUND_BACK
    return refund


def remove_purchase(
    actor: User,
    purchase: Purchase,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> CommandResult:
    """Take a purchase out of the library."""
    with answered(SUBJECT):
        return _dispatch(
            RemovePurchase(purchase_id=purchase.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )


def restore_purchase(
    actor: User,
    purchase: Purchase,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> CommandResult:
    """Put a removed purchase back."""
    with answered(SUBJECT):
        return _dispatch(
            RestorePurchase(purchase_id=purchase.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
