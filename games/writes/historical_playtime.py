"""State a historical playtime record; answer a refusal.

An actor goes in here, not a request.
"""

import uuid

from django.contrib.auth.models import User

from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
    RemoveHistoricalPlaytime,
    RestateHistoricalPlaytime,
    RestoreHistoricalPlaytime,
)
from games.events.dispatch import Command, CommandResult, dispatch
from games.events.idempotency import IdempotencyKey
from games.models import HistoricalPlaytime, LibraryEvent
from games.writes.answers import answered

SUBJECT = "historical playtime"


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
        #: Caller's key, else one per request.
        #:
        #: Not `or`: a blank key is falsy, so it would be minted
        #: over, and the caller that asked for one write would get
        #: a second on its retry rather than a refusal.
        idempotency_key=(
            str(uuid.uuid7()) if idempotency_key is None else idempotency_key
        ),
        correlation_id=correlation_id,
    )


def record_historical_playtime(
    actor: User,
    statement: HistoricalPlaytimeStatement,
    *,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> uuid.UUID:
    """Record the statement; answer the record's id.

    Record has no Unchanged, so the key is what makes a
    repeated submit replay rather than record twice.
    """
    with answered(SUBJECT):
        result = _dispatch(
            RecordHistoricalPlaytime(statement=statement),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    if result.sequences is None:
        raise RuntimeError(
            f"Recording historical playtime under {idempotency_key} appended nothing."
        )
    return LibraryEvent.objects.get(
        stream_id=result.stream_id, sequence=result.sequences.first
    ).aggregate_id


def restate_historical_playtime(
    actor: User,
    record: HistoricalPlaytime,
    statement: HistoricalPlaytimeStatement,
    *,
    correlation_id: uuid.UUID,
) -> None:
    """State the whole record again."""
    with answered(SUBJECT):
        _dispatch(
            RestateHistoricalPlaytime(record_id=record.pk, statement=statement),
            actor=actor,
            correlation_id=correlation_id,
        )


def remove_historical_playtime(
    actor: User, record: HistoricalPlaytime, *, correlation_id: uuid.UUID
) -> None:
    """Take a record out of the totals."""
    with answered(SUBJECT):
        _dispatch(
            RemoveHistoricalPlaytime(record_id=record.pk),
            actor=actor,
            correlation_id=correlation_id,
        )


def restore_historical_playtime(
    actor: User, record: HistoricalPlaytime, *, correlation_id: uuid.UUID
) -> None:
    """Put a removed record back."""
    with answered(SUBJECT):
        _dispatch(
            RestoreHistoricalPlaytime(record_id=record.pk),
            actor=actor,
            correlation_id=correlation_id,
        )
