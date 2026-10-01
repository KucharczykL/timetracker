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
    RefundPurchase,
    RefundStatement,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
    VoidPurchaseRefund,
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
from games.reads.entries import EventSequence
from games.reads.events import dispatched_events
from games.writes.answers import SubjectNoun, answered
from games.writes.endpoint import KEEP, Keep, Restated
from games.writes.revaluation import appended_types, revalue_after

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
    if result.outcome is CommandOutcome.APPENDED:
        revalue_after(actor, frozenset(event_by_type))
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
    refund: Restated[ActStatement] = KEEP,
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
    event_types = appended_types(result)
    revalue_after(actor, event_types)
    return RestatedPurchase(appended=True, copy_end=_copy_end_of(event_types))


def _copy_end_of(event_types: frozenset[EventType]) -> CopyEnd | None:
    """What the dispatch's refund act did; None without one."""
    if event_types.isdisjoint(PURCHASE_REFUND_EVENTS.family):
        return None
    for event_type, copy_end in _COPY_END_BY_TYPE.items():
        if event_type in event_types:
            return copy_end
    return CopyEnd.LEFT


class RefundedPurchase(NamedTuple):
    """What a recorded refund answers."""

    #: The refund event's own.
    sequence: EventSequence
    copy_end: CopyEnd | None


def refund_purchase(
    actor: User,
    purchase: Purchase,
    statement: ActStatement,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
) -> RefundedPurchase | None:
    """State a refund; None when unchanged."""
    with answered(SUBJECT):
        result = _dispatch(
            RefundPurchase(purchase_id=purchase.pk, statement=statement),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    if result.outcome is CommandOutcome.UNCHANGED:
        return None
    #: The copy's end may follow.
    events = list(dispatched_events(result))
    refunded = next(
        (
            event
            for event in events
            if event.event_type == PURCHASE_REFUND_EVENTS.stated.event_type
        ),
        None,
    )
    if refunded is None:
        raise RuntimeError(
            f"Dispatch {result.stream_id} {result.sequences} appended no "
            f"{PURCHASE_REFUND_EVENTS.stated.event_type}."
        )
    return RefundedPurchase(
        sequence=refunded.sequence,
        copy_end=_copy_end_of(frozenset(event.event_type for event in events)),
    )


def _refund_statement(refund: Restated[ActStatement]) -> RefundStatement | None:
    """The command's spelling of the write's."""
    if isinstance(refund, Keep):
        return None
    if refund is None:
        return TAKE_REFUND_BACK
    return refund


def undo_refund(
    actor: User,
    purchase: Purchase,
    *,
    refunded_at: EventSequence,
    correlation_id: uuid.UUID,
) -> RestatedPurchase:
    """Void a refund still standing as latest."""
    with answered(SUBJECT):
        result = _dispatch(
            VoidPurchaseRefund(purchase_id=purchase.pk, refunded_at=refunded_at),
            actor=actor,
            correlation_id=correlation_id,
        )
    if result.outcome is not CommandOutcome.APPENDED:
        return RestatedPurchase(appended=False, copy_end=None)
    return RestatedPurchase(
        appended=True, copy_end=_copy_end_of(appended_types(result))
    )


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
        result = _dispatch(
            RestorePurchase(purchase_id=purchase.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    revalue_after(actor, appended_types(result))
    return result
