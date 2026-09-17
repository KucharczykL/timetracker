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
from games.models import HistoricalPlaytime, LibraryEvent
from games.writes.answers import answered

SUBJECT = "historical playtime"


def _dispatch(
    command: Command, *, actor: User, correlation_id: uuid.UUID
) -> CommandResult:
    return dispatch(
        command,
        actor=actor,
        library=actor.library,
        #: Deduplicates nothing; each build absorbs a repeat.
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id,
    )


def record_historical_playtime(
    actor: User, statement: HistoricalPlaytimeStatement, *, correlation_id: uuid.UUID
) -> uuid.UUID:
    """Record the statement; answer the new record's id."""
    with answered(SUBJECT):
        result = _dispatch(
            RecordHistoricalPlaytime(statement=statement),
            actor=actor,
            correlation_id=correlation_id,
        )
    assert result.sequences is not None
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
    """State the whole record again; the same statement changes nothing."""
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
