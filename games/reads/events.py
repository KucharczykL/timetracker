"""Reading one library's recorded stream by the batch that wrote it.

Nearly every read in this package answers from a projection. This one
answers from the events, as `playergame_history` does, because what it
asks about — which rows one human act changed — no projection keeps.
"""

import uuid

from games.events.vocabulary import DEFAULT_EVENT_TYPES, AggregateType
from games.models import LibraryEvent, LibraryEventQuerySet, UserLibrary


def batch_events(
    library: UserLibrary, correlation_id: uuid.UUID
) -> LibraryEventQuerySet:
    """The events of one act, in the order they were appended.

    Scoped on the library as well as the correlation: one id in two
    libraries is two batches, and nothing stops a person naming another
    library's.
    """
    return LibraryEvent.objects.filter(
        library=library, correlation_id=correlation_id
    ).order_by("sequence")


def batch_aggregate_ids(
    library: UserLibrary, correlation_id: uuid.UUID, aggregate_type: AggregateType
) -> list[uuid.UUID]:
    """The rows of one aggregate type the batch changed, each named once.

    One act may write more than one aggregate: the reclassification
    appends a created record beside the session that became it. A caller
    wants the rows its own command reads, so it says which.
    """
    named = batch_events(library, correlation_id).filter(
        event_type__in=DEFAULT_EVENT_TYPES.event_types_for(aggregate_type)
    )
    #: dict, not set: the append order is the order the act ran in.
    return list(dict.fromkeys(named.values_list("aggregate_id", flat=True)))
