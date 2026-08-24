"""The only supported writer of the library event stream.

A command locks the stream head, validates whatever mutable projections it
depends on, and appends the events of one human action contiguously -- all in
one transaction owned by the caller.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.contrib.auth.models import User
from django.db import router, transaction
from django.utils import timezone

from games.events.envelope import RecordedEvent
from games.events.vocabulary import NewEvent
from games.events.wiring import DEFAULT_WIRING, EventWiring
from games.models import LibraryEvent, LibraryEventStreamHead, UserLibrary

type SourceMetadata = dict[str, Any]  # {"origin": "manual"}


class TransactionRequired(RuntimeError):
    """Raised when a stream is locked outside an open transaction."""


class PayloadNotCanonical(ValueError):
    """Raised for a payload PostgreSQL would hand back as something else."""


def canonical_json[T](value: T, *, label: str) -> T:
    """Return `value` as JSONB will return it, refusing anything that differs.

    A projector reads the appended row rather than a re-selected one, so a value
    that changes shape on the way to the database would be seen one way during
    the command and another way during a replay. A tuple returns as a list and
    an integer key as a string; the rest do not survive the encoder at all.

    The round-trip is returned rather than the argument so the stored payload is
    nobody else's object: an aliased one lets a projector reach back into the
    NewEvent the command built.
    """
    try:
        round_tripped = json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise PayloadNotCanonical(
            f"This {label} holds something JSON cannot carry: {error}"
        ) from error
    if round_tripped != value:
        raise PayloadNotCanonical(
            f"This {label} is not what PostgreSQL would return: "
            f"{value!r} would come back as {round_tripped!r}."
        )
    return round_tripped


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
        actor: User | None,
        correlation_id: uuid.UUID,
        idempotency_key: str,
        source_metadata: SourceMetadata | None = None,
        recorded_at: datetime | None = None,
        wiring: EventWiring = DEFAULT_WIRING,
    ) -> AppendResult:
        if not events:
            raise ValueError("An append records at least one event.")

        #: Before the rows and before the advance: a refusal must leave a
        #: transaction that may still commit exactly as it found it.
        metadata = canonical_json(source_metadata or {}, label="source metadata")
        payloads = [canonical_json(event.payload, label="payload") for event in events]

        head = self._head
        first_sequence = head.current_sequence + 1
        #: One act of recording, so every row of one action shares a timestamp.
        recorded_at = recorded_at or timezone.now()
        rows = [
            LibraryEvent(
                library_id=head.library_id,
                stream=head,
                sequence=first_sequence + offset,
                event_type=event.spec.event_type,
                aggregate_type=event.spec.aggregate_type,
                aggregate_id=event.aggregate_id,
                payload=payloads[offset],
                payload_schema_version=event.spec.version,
                recorded_at=recorded_at,
                effective_time=event.effective_time,
                actor=actor,
                correlation_id=correlation_id,
                causation_id=event.causation_id,
                source_metadata=metadata,
                idempotency_key=idempotency_key,
            )
            for offset, event in enumerate(events)
        ]
        LibraryEvent.objects.bulk_create(rows)

        head.current_sequence = rows[-1].sequence
        head.save(update_fields=["current_sequence"])

        #: Event-major, and only after the advance: a family sees the append
        #: already recorded rather than the event it happens to be holding. An
        #: append is the one place this can run and still be in the command's
        #: transaction under the lock it already took, which is what makes "no
        #: event commits unprojected" a property of the writer.
        for row in rows:
            wiring.projectors.apply(RecordedEvent.from_row(row))

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
