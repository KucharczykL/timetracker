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


def _with_sorted_keys(value: Any) -> Any:
    """Return `value` with every dict's keys sorted, at every depth.

    Keys only. A list is ordered data, so its items keep the order they were
    recorded in and are rebuilt in place.
    """
    if isinstance(value, dict):
        return {key: _with_sorted_keys(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_with_sorted_keys(item) for item in value]
    return value


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
        """Copy every concrete field off `row`, the payload canonically.

        Written out rather than built from `_meta`, so mypy checks each field
        against its declared type and a model change fails as a named test
        rather than as a `TypeError` inside an append.

        The payload's keys are sorted here because both paths reach a projector
        through this method and they do not agree on order: an append hands over
        the order its caller wrote, while a replay hands over jsonb's, which
        sorts keys by length then bytes. A family that iterates a payload,
        re-dumps it into a column, or hashes it would produce different rows on
        the two paths, and no equality check would see it -- dict comparison
        ignores order, which is why the defect survived. One fixed rule applied
        here settles both paths and couples us to no PostgreSQL behaviour. The
        consequence is deliberate: the order stored in the row is not the order
        a projector reads.
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
            aggregate_id=row.aggregate_id,
            payload_schema_version=row.payload_schema_version,
            recorded_at=row.recorded_at,
            effective_time=row.effective_time,
            actor_id=row.actor_id,
            correlation_id=row.correlation_id,
            causation_id=row.causation_id,
            source_metadata=row.source_metadata,
            idempotency_key=row.idempotency_key,
            payload=_with_sorted_keys(row.payload),
        )
