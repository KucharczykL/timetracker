"""One library's stream, read by batch or by one dispatch.

From the events: no projection answers these.
"""

import uuid

from games.events.dispatch import CommandResult
from games.events.vocabulary import DEFAULT_EVENT_TYPES, AggregateType
from games.models import LibraryEvent, LibraryEventQuerySet, UserLibrary


def batch_events(
    library: UserLibrary, correlation_id: uuid.UUID
) -> LibraryEventQuerySet:
    """One act's events, in append order."""
    return LibraryEvent.objects.filter(
        library=library, correlation_id=correlation_id
    ).order_by("sequence")


def batch_aggregate_ids(
    library: UserLibrary, correlation_id: uuid.UUID, aggregate_type: AggregateType
) -> list[uuid.UUID]:
    """One aggregate type's rows, named once.

    An act may write two: the caller says which its command reads.
    """
    named = batch_events(library, correlation_id).filter(
        event_type__in=DEFAULT_EVENT_TYPES.event_types_for(aggregate_type)
    )
    #: dict, not set: append order matters.
    return list(dict.fromkeys(named.values_list("aggregate_id", flat=True)))


def created_aggregate_id(result: CommandResult) -> uuid.UUID:
    """The row a creation wrote: its first event's aggregate id.

    Never `stream_id`, which is the library's one stream head.
    The first event is the creation, which is the caller's to
    know: an outcome that appended nothing states no sequence.
    """
    if result.sequences is None:
        #: Not an assert: `-O` strips one.
        raise ValueError("An outcome that appended no event names no created row.")
    return LibraryEvent.objects.get(
        stream_id=result.stream_id, sequence=result.sequences.first
    ).aggregate_id
