"""The rows every act on a run reads.

Here rather than beside one act: an act importing a sibling closes a
cycle. The table imports each act at its foot, so an act reached first
runs that foot before its own body, and the sibling finds nothing.
"""

import uuid
from collections.abc import Sequence

from django.db.models import QuerySet

from common.components.primitives import Cell
from common.temporal_presentation import TemporalText
from games.bulk_actions import (
    FilterJson,
    Presentations,
    PreviewColumn,
    Resolution,
)
from games.bulk_narrowing import narrowed
from games.bulk_sessions import lost
from games.filters import parse_playthrough_filter
from games.models import Playthrough, UserLibrary
from games.reads.playthrough_endpoints import (
    StatedEndpoint,
    stated_completion,
    stated_start,
)
from games.reads.playthrough_numbering import display_name, numbered_for
from games.reads.playthrough_runs import library_runs, runs_with_condition

RUN_GONE = "One of the playthroughs is no longer available, so it was left as it is."


def run_scope(library: UserLibrary, filter_json: FilterJson) -> QuerySet[Playthrough]:
    """The list's own read, which carries the condition aliases.

    `runs_with_condition`, not `library_runs`: `activity` is a quick
    facet of this mode, and a statement carrying it would not compile
    over a queryset no clock reached.
    """
    return narrowed(
        runs_with_condition(library), library, filter_json, parse_playthrough_filter
    )


def run_resolution(
    library: UserLibrary, keys: Sequence[uuid.UUID]
) -> Resolution[Playthrough]:
    """Keys to rows, each carrying the number a screen calls it.

    The number is counted across every live ordinary run of the games
    the keys name, never across the selection: a partition narrowed to
    what a person ticked would call each of them the first. So the
    rows the act offers are read off the numbered queryset, and the
    list's own scope says which of them are offered.
    """
    wanted = list(dict.fromkeys(keys))
    offered = library_runs(library).filter(pk__in=wanted)
    live = set(offered.values_list("pk", flat=True))
    games = set(offered.values_list("player_game_id", flat=True))
    rows = tuple(
        sorted(
            (
                run
                for run in numbered_for(library, games).select_related(
                    "player_game__game"
                )
                if run.pk in live
            ),
            #: A stable sort keeps the numbering order inside a game.
            key=lambda run: run.player_game.game.name,
        )
    )
    return Resolution(rows, tuple(lost(wanted, live, RUN_GONE)))


def _start_cell(row: Playthrough, presentations: Presentations) -> Cell:
    return _endpoint_cell(stated_start(row), presentations)


def _completion_cell(row: Playthrough, presentations: Presentations) -> Cell:
    return _endpoint_cell(stated_completion(row), presentations)


def _endpoint_cell(stated: StatedEndpoint | None, presentations: Presentations) -> Cell:
    """No act reads a dash, as the list writes it."""
    if stated is None:
        return "-"
    return TemporalText(stated.when, presentations.dates)


RUN_PREVIEW: tuple[PreviewColumn[Playthrough], ...] = (
    PreviewColumn("Playthrough", lambda row, _: display_name(row)),
    PreviewColumn("Game", lambda row, _: row.player_game.game.name),
    PreviewColumn("Started", _start_cell),
    PreviewColumn("Completed", _completion_cell),
)
