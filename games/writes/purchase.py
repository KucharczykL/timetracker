"""Purchase writes; refusals become answers."""

import uuid
from typing import NamedTuple

from django.contrib.auth.models import User

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement
from games.commands.purchase import (
    CorrectPurchaseDay,
    DescribePurchase,
    RecordPurchase,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
)
from games.events.dispatch import Command, CommandOutcome, CommandResult, dispatch
from games.events.idempotency import IdempotencyKey
from games.events.libraryentry import LIBRARYENTRY_CREATED
from games.events.playergame import PLAYERGAME_CREATED
from games.events.purchase import PURCHASE_CREATED
from games.models import Purchase
from games.reads.events import dispatched_events
from games.writes.answers import SubjectNoun, answered
from games.writes.libraryentry import KEEP, EntryDraft, Keep

SUBJECT: SubjectNoun = "purchase"


class PurchaseDraft(NamedTuple):
    """What a creation states."""

    #: A held copy's key, or a new copy.
    copy: uuid.UUID | EntryDraft
    kind: str
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
    entry_id: uuid.UUID | None = None
    new_entry: EntryStatement | None = None
    match draft.copy:
        case EntryDraft() as entry:
            new_entry = entry.statement()
        case held:
            entry_id = held
    with answered(SUBJECT):
        result = _dispatch(
            RecordPurchase(
                kind=draft.kind,
                entry_id=entry_id,
                new_entry=new_entry,
                name=draft.name,
                price=draft.price,
                note=draft.note,
                purchased=draft.purchased,
            ),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    events = dispatched_events(result)
    id_by_type = {event.event_type: event.aggregate_id for event in events}
    created = next(
        event for event in events if event.event_type == PURCHASE_CREATED.event_type
    )
    return RecordedPurchase(
        purchase_id=created.aggregate_id,
        entry_id=uuid.UUID(created.payload["entry"]["id"]),
        created_the_entry=LIBRARYENTRY_CREATED.event_type in id_by_type,
        tracked_the_game=PLAYERGAME_CREATED.event_type in id_by_type,
    )


def restate_purchase(
    actor: User,
    purchase: Purchase,
    *,
    kind: str | None = None,
    name: str | None = None,
    price: StatedPrice | None = None,
    note: str | None = None,
    entry_id: uuid.UUID | None = None,
    purchased: ActStatement | Keep = KEEP,
    correlation_id: uuid.UUID,
) -> bool:
    """Describe, then correct; answers whether appended."""
    commands: list[Command] = []
    if any(fact is not None for fact in (kind, name, price, note, entry_id)):
        commands.append(
            DescribePurchase(
                purchase_id=purchase.pk,
                kind=kind,
                name=name,
                price=price,
                note=note,
                entry_id=entry_id,
            )
        )
    if not isinstance(purchased, Keep):
        commands.append(
            CorrectPurchaseDay(purchase_id=purchase.pk, statement=purchased)
        )
    changed = False
    for command in commands:
        with answered(SUBJECT):
            result = _dispatch(command, actor=actor, correlation_id=correlation_id)
        changed = changed or result.outcome is CommandOutcome.APPENDED
    return changed


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
