"""The run a converted legacy row became.

#684 recorded the row's id in the creation event's source_metadata and
wrote no column, so this reads the provenance rather than a join.
#771 removes the legacy table and this module with it.
"""

import uuid
from collections.abc import Iterable

from games.events.playthrough import PLAYTHROUGH_CREATED
from games.models import LibraryEvent, Playthrough, UserLibrary

#: The legacy row, and the run #684 made from it.
type PlayEventId = uuid.UUID
type PlaythroughId = uuid.UUID


def runs_for_rows(
    library: UserLibrary, row_ids: Iterable[PlayEventId]
) -> dict[PlayEventId, PlaythroughId]:
    """The run each converted row became.

    Partial by construction: a default run the conversion minted and a
    run TrackGame states carry no row id, because no row became either.
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
    """The run this legacy row became, or nothing.

    The run is read whatever its mark says: a removal answers Unchanged
    for a run already removed, which is a better answer than a refusal
    naming a row the person can still see.
    """
    run_id = runs_for_rows(library, [row_id]).get(row_id)
    if run_id is None:
        return None
    return (
        Playthrough.objects.select_related("player_game")
        .filter(library=library, pk=run_id)
        .first()
    )
