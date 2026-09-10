"""A start for the runs #684 left empty. #1038.

#684 states one run per legacy PlayEvent row, and one empty
default for a tracked game holding none. Most tracked games
held none, so most runs state no day at all while a status
change and a session both record when play began. This pass
states that day, and states no completion.
"""

import uuid
from typing import NamedTuple

from games.events.playthrough import PLAYTHROUGH_CREATED
from games.models import (
    LibraryEvent,
    Playthrough,
    PlaythroughKind,
    UserLibrary,
)

#: Named in every key and every metadata value.
START_ISSUE = 1038
KEY_PREFIX = f"backfill:{START_ISSUE}:playthrough-start"

#: The issue whose defaults this repairs.
CONVERSION_ISSUE = 684


class RunInScope(NamedTuple):
    """One empty default, and what dates it."""

    run_id: uuid.UUID
    player_game_id: uuid.UUID
    game_id: uuid.UUID


def default_run_ids(library: UserLibrary) -> set[uuid.UUID]:
    """Every run #684 minted holding no legacy row.

    The creation event names its origin and the projection row
    names none, so the stream answers this. A creation #684
    made from a row names that row; a default names none, which
    is what the excluded key reads.
    """
    return set(
        LibraryEvent.objects.filter(
            library=library,
            event_type=PLAYTHROUGH_CREATED.event_type,
            source_metadata__origin="backfill",
            source_metadata__issue=CONVERSION_ISSUE,
        )
        .exclude(source_metadata__has_key="play_event_id")
        .values_list("aggregate_id", flat=True)
    )


def runs_in_scope(library: UserLibrary) -> list[RunInScope]:
    """The empty defaults this pass may date.

    Six conditions, and the sixth carries the weight: a person
    may create a blank run and #679 states one at track time.
    Neither is this pass's debt.

    values_list rather than rows, so the columns this reads are
    named: a migration replaying it against a later schema
    cannot select a column that is not there yet.
    """
    identifiers = default_run_ids(library)
    if not identifiers:
        return []
    rows = (
        Playthrough.objects.filter(
            pk__in=identifiers,
            library=library,
            kind=PlaythroughKind.ORDINARY,
            removed_at__isnull=True,
            start_recorded_at__isnull=True,
            completion_recorded_at__isnull=True,
            player_game__removed_at__isnull=True,
            player_game__game__removed_at__isnull=True,
        )
        .order_by("pk")
        .values_list("pk", "player_game_id", "player_game__game_id")
    )
    return [
        RunInScope(run_id=run_id, player_game_id=player_game_id, game_id=game_id)
        for run_id, player_game_id, game_id in rows
    ]
