"""One library's stream, read by batch.

From the events: no projection answers this.
"""

import uuid

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
