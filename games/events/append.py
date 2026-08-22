"""The only supported writer of the library event stream.

A command locks the stream head, validates whatever mutable projections it
depends on, and appends the events of one human action contiguously -- all in
one transaction owned by the caller.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.db import router, transaction
from django.utils import timezone

from games.models import LibraryEvent, LibraryEventStreamHead, UserLibrary
from timetracker.temporal import TemporalValue

type SourceMetadata = dict[str, Any]  # {"origin": "manual"}


class TransactionRequired(RuntimeError):
    """Raised when a stream is locked outside an open transaction."""


@dataclass(frozen=True, slots=True)
class NewEvent:
    """One fact to append. Carries no stream, sequence, or library: those are
    the stream's to assign, and a caller has no way to express them."""

    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload: dict[str, Any]
    payload_schema_version: int = 1
    effective_time: TemporalValue | None = None
    causation_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AppendResult:
    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int
    events: tuple[LibraryEvent, ...]


class LockedStream:
    """A library's stream head, locked for the rest of the caller's
    transaction. Obtained from `lock_stream`, never constructed directly."""

    def __init__(self, head: LibraryEventStreamHead) -> None:
        self._head = head

    @property
    def stream_id(self) -> uuid.UUID:
        return self._head.id

    @property
    def current_sequence(self) -> int:
        return self._head.current_sequence

    def append(
        self,
        events: Sequence[NewEvent],
        *,
        actor: AbstractBaseUser | None,
        correlation_id: uuid.UUID,
        idempotency_key: str,
        source_metadata: SourceMetadata | None = None,
        recorded_at: datetime | None = None,
    ) -> AppendResult:
        if not events:
            raise ValueError("An append records at least one event.")

        head = self._head
        first_sequence = head.current_sequence + 1
        #: One act of recording, so every row of one action shares a timestamp.
        recorded_at = recorded_at or timezone.now()
        rows = [
            LibraryEvent(
                library_id=head.library_id,
                stream=head,
                sequence=first_sequence + offset,
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                payload=event.payload,
                payload_schema_version=event.payload_schema_version,
                recorded_at=recorded_at,
                effective_time=event.effective_time,
                actor=actor,
                correlation_id=correlation_id,
                causation_id=event.causation_id,
                source_metadata=source_metadata or {},
                idempotency_key=idempotency_key,
            )
            for offset, event in enumerate(events)
        ]
        LibraryEvent.objects.bulk_create(rows)

        head.current_sequence = rows[-1].sequence
        head.save(update_fields=["current_sequence"])
        return AppendResult(
            stream_id=head.id,
            first_sequence=first_sequence,
            last_sequence=head.current_sequence,
            events=tuple(rows),
        )


def lock_stream(library: UserLibrary) -> LockedStream:
    """Lock `library`'s stream head until the caller's transaction ends.

    Take this before reading any projection the command validates against:
    that is what stops the projection moving between the read and the append.
    """
    connection = transaction.get_connection(router.db_for_write(LibraryEvent))
    if not connection.in_atomic_block:
        raise TransactionRequired(
            "lock_stream requires an open transaction: the head lock is held "
            "until the caller commits."
        )

    heads = LibraryEventStreamHead.objects.select_for_update()
    try:
        return LockedStream(heads.get(library=library))
    except LibraryEventStreamHead.DoesNotExist:
        #: First append for this library. get_or_create wraps its insert in a
        #: savepoint and falls back to get(), so a concurrent first append
        #: resolves at the unique constraint rather than poisoning the caller's
        #: transaction. Re-select so the row is locked whichever branch won.
        LibraryEventStreamHead.objects.get_or_create(library=library)
        return LockedStream(heads.get(library=library))


def append_events(
    library: UserLibrary,
    events: Sequence[NewEvent],
    *,
    actor: AbstractBaseUser | None,
    correlation_id: uuid.UUID,
    idempotency_key: str,
    source_metadata: SourceMetadata | None = None,
    recorded_at: datetime | None = None,
) -> AppendResult:
    """Lock, append, and advance in one call, for a command with nothing to
    validate between the lock and the append."""
    return lock_stream(library).append(
        events,
        actor=actor,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
        recorded_at=recorded_at,
    )
