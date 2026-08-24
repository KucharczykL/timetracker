"""The event as everything downstream of the append reads it: a value.

One dataclass, built from a `LibraryEvent` row, carrying the whole envelope and
none of the model. It is shared vocabulary rather than projection machinery --
`append` constructs it, `projection` consumes it, and a replay constructs it from
a read without caring whether anything projects.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from games.models import LibraryEvent
from timetracker.temporal import TemporalValue


class DeferredRowRefused(ValueError):
    """Raised for a row whose columns were not all selected."""


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """One event as a projector reads it: the envelope, by value.

    Carries no relation, no manager, and no `save()`, so a family cannot
    traverse to the actor -- free at append, where `bulk_create` cached it, and
    one query per event on a replay -- cannot mutate an event that is already
    immutable, and reads the same value whichever path reached it.

    `payload` and `source_metadata` are plain dicts and are read-only by
    convention. Nothing available freezes them without breaking either equality
    against a plain dict or `json.dumps`, and a projection writing a JSONField
    needs both; the design document measures the alternatives.
    """

    id: uuid.UUID
    library_id: uuid.UUID
    stream_id: uuid.UUID
    sequence: int
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload_schema_version: int
    recorded_at: datetime
    effective_time: TemporalValue | None
    actor_id: int | None
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None
    source_metadata: dict[str, Any]
    idempotency_key: str
    payload: dict[str, Any]

    @classmethod
    def from_row(cls, row: LibraryEvent) -> RecordedEvent:
        """Copy every concrete field off `row`.

        Written out rather than built from `_meta`, so mypy checks each field
        against its declared type and a model change fails as a named test
        rather than as a `TypeError` inside an append.
        """
        deferred = row.get_deferred_fields()
        if deferred:
            #: Every field is read below, and a deferred one is a round trip
            #: each. Selecting fewer columns is the obvious way to make a large
            #: rebuild read cheaper, and it is exactly what must not happen.
            raise DeferredRowRefused(
                "A recorded event reads the whole envelope, so a row missing "
                f"{', '.join(sorted(deferred))} would fetch one column per "
                "event. Select every field."
            )
        return cls(
            id=row.id,
            library_id=row.library_id,
            stream_id=row.stream_id,
            sequence=row.sequence,
            event_type=row.event_type,
            aggregate_type=row.aggregate_type,
            aggregate_id=row.aggregate_id,
            payload_schema_version=row.payload_schema_version,
            recorded_at=row.recorded_at,
            effective_time=row.effective_time,
            actor_id=row.actor_id,
            correlation_id=row.correlation_id,
            causation_id=row.causation_id,
            source_metadata=row.source_metadata,
            idempotency_key=row.idempotency_key,
            payload=row.payload,
        )
