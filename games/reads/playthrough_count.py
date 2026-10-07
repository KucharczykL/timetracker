"""The runs a stated count may take."""

from functools import reduce
from operator import or_

from django.db.models import Q, QuerySet

from games.models import PlayerGame, Playthrough, UserLibrary
from games.reads.playthrough_runs import live_ordinary_runs
from games.reads.referrers import named_in_its_library, referrers_of


def unnamed_runs(runs: QuerySet[Playthrough]) -> QuerySet[Playthrough]:
    """Runs no own-library row names."""
    named = [named_in_its_library(referrer) for referrer in referrers_of(Playthrough)]
    if not named:
        return runs
    return runs.exclude(reduce(or_, (Q(exists) for exists in named)))


def _blank(runs: QuerySet[Playthrough]) -> QuerySet[Playthrough]:
    return runs.filter(name="", note="", start_note="", completion_note="")


def bare_runs(library: UserLibrary, player_game: PlayerGame) -> QuerySet[Playthrough]:
    """Live ordinary runs stating nothing at all."""
    return unnamed_runs(
        _blank(live_ordinary_runs(library, player_game)).filter(
            start_recorded_at__isnull=True, completion_recorded_at__isnull=True
        )
    )


def dateless_runs(
    library: UserLibrary, player_game: PlayerGame
) -> QuerySet[Playthrough]:
    """Played-through runs stating nothing else, newest first."""
    return unnamed_runs(
        _blank(live_ordinary_runs(library, player_game)).filter(
            start_recorded_at__isnull=False,
            completion_recorded_at__isnull=False,
            started__isnull=True,
            completed__isnull=True,
        )
    ).order_by("-created_at", "-id")
