"""The run a converted legacy row became.

#684 wrote no column, so this reads the row id off the
creation event. #771 takes the table and this module.
"""

import uuid
from collections.abc import Iterable

from games.events.playthrough import PLAYTHROUGH_CREATED
from games.models import LibraryEvent, Playthrough, UserLibrary

#: A legacy row and its converted run.
type PlayEventId = uuid.UUID
type PlaythroughId = uuid.UUID


def runs_for_rows(
    library: UserLibrary, row_ids: Iterable[PlayEventId]
) -> dict[PlayEventId, PlaythroughId]:
    """The run each converted row became.

    Partial: a default run and a TrackGame run name no row.
    """
    keys = [str(row_id) for row_id in row_ids]
    if not keys:
        return {}
    recorded = LibraryEvent.objects.filter(
        library=library,
        event_type=PLAYTHROUGH_CREATED.event_type,
        source_metadata__play_event_id__in=keys,
    ).values_list("source_metadata__play_event_id", "aggregate_id")
    return {uuid.UUID(row_id): run_id for row_id, run_id in recorded}


def run_for_row(library: UserLibrary, row_id: PlayEventId) -> Playthrough | None:
    """The run this legacy row became.

    Read whatever its mark says: a removal answers Unchanged
    for a removed run, which beats refusing a visible row.
    """
    run_id = runs_for_rows(library, [row_id]).get(row_id)
    if run_id is None:
        return None
    return (
        Playthrough.objects.select_related("player_game")
        .filter(library=library, pk=run_id)
        .first()
    )
