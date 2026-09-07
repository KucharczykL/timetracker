"""The run a converted legacy row became.

#684 wrote no column, so this reads the row id off the
creation event. #771 takes the table and this module.
"""

import logging
import uuid
from collections.abc import Iterable
from typing import NamedTuple

from games.events.playthrough import PLAYTHROUGH_CREATED
from games.models import LibraryEvent, Playthrough, UserLibrary

logger = logging.getLogger("games")

#: A legacy row and its converted run.
type PlayEventId = uuid.UUID
type PlaythroughId = uuid.UUID

#: The ordinary way to hold no run.
NEVER_CONVERTED = (
    "This play event was never converted into a playthrough, because your "
    "library no longer tracks its game. Track the game again to record runs at it."
)
#: Drift: the event names a run this library cannot read.
RUN_UNREADABLE = (
    "This play event's playthrough cannot be read right now. Try again in a "
    "moment, and report it if it keeps happening."
)


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
    mapped: dict[PlayEventId, PlaythroughId] = {}
    for raw_row_id, run_id in recorded:
        row_id = uuid.UUID(raw_row_id)
        claimed = mapped.get(row_id)
        if claimed is not None and claimed != run_id:
            #: A doubled conversion. Keeping the first is
            #: arbitrary, so the other one is on the record.
            logger.error(
                "legacy row converted twice (library=%s, play_event=%s, "
                "playthrough=%s, also=%s)",
                library.pk,
                row_id,
                claimed,
                run_id,
            )
            continue
        mapped[row_id] = run_id
    return mapped


class ConvertedRun(NamedTuple):
    """What a legacy row's id maps to.

    Two ways to hold no run, told apart because only one
    of them is ordinary and the sentences differ.
    """

    run: Playthrough | None
    #: True where no creation event names the row.
    never_converted: bool

    @property
    def sentence(self) -> str:
        """What a person is shown for a missing run."""
        return NEVER_CONVERTED if self.never_converted else RUN_UNREADABLE


def run_for_row(library: UserLibrary, row_id: PlayEventId) -> ConvertedRun:
    """The run this legacy row became.

    Read whatever its mark says: a removal answers Unchanged
    for a removed run, which beats refusing a visible row.

    An event that names a run this library cannot read is
    drift rather than an untracked game -- a lagging
    projection, a rebuild mid-swap, or the ownership
    `audit_library_ownership` reports -- so it is logged
    and answered in its own words.
    """
    run_id = runs_for_rows(library, [row_id]).get(row_id)
    if run_id is None:
        return ConvertedRun(None, never_converted=True)
    run = (
        Playthrough.objects.select_related("player_game")
        .filter(library=library, pk=run_id)
        .first()
    )
    if run is None:
        logger.error(
            "converted playthrough unreadable (library=%s, play_event=%s, "
            "playthrough=%s)",
            library.pk,
            row_id,
            run_id,
        )
    return ConvertedRun(run, never_converted=False)
