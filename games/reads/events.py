"""One library's stream, read by batch or by one dispatch.

From the events: no projection answers these.
"""

import uuid

from games.events.dispatch import CommandResult
from games.events.playthrough import PLAYTHROUGH_CREATED, PLAYTHROUGH_MOVED
from games.events.vocabulary import DEFAULT_EVENT_TYPES, AggregateType
from games.ids import PlayerGameId, PlaythroughId
from games.models import LibraryEvent, LibraryEventQuerySet, UserLibrary


def batch_events(
    library: UserLibrary, correlation_id: uuid.UUID
) -> LibraryEventQuerySet:
    """One act's events, in append order."""
    return LibraryEvent.objects.filter(
        library=library, correlation_id=correlation_id
    ).order_by("sequence")


def aggregate_events(
    library: UserLibrary, aggregate_id: uuid.UUID
) -> LibraryEventQuerySet:
    """One row's whole history, in append order.

    No projection keeps what a column held before.
    """
    return LibraryEvent.objects.filter(
        library=library, aggregate_id=aggregate_id
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


def dispatched_events(result: CommandResult) -> LibraryEventQuerySet:
    """One dispatch's events, in append order."""
    if result.sequences is None:
        #: Not an assert: `-O` strips one.
        raise ValueError("An outcome that appended no event names no range.")
    return LibraryEvent.objects.filter(
        stream_id=result.stream_id,
        sequence__range=(result.sequences.first, result.sequences.last),
    ).order_by("sequence")


#: The events that state a run's game.
_RUN_PARENT_TYPES = (PLAYTHROUGH_CREATED.event_type, PLAYTHROUGH_MOVED.event_type)


def run_game_at_batch(
    library: UserLibrary, playthrough_id: PlaythroughId, batch_id: uuid.UUID
) -> PlayerGameId | None:
    """The run's PlayerGame when the batch wrote.

    None: no batch event, or no earlier game.
    """
    events = aggregate_events(library, playthrough_id)
    batch_event = events.filter(correlation_id=batch_id).first()
    if batch_event is None:
        return None
    parent = events.filter(
        event_type__in=_RUN_PARENT_TYPES, sequence__lt=batch_event.sequence
    ).last()
    return None if parent is None else uuid.UUID(parent.payload["player_game"])
