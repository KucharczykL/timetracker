"""The runs a tracked game holds."""

from django.db.models import QuerySet

from games.models import PlayerGame, Playthrough, PlaythroughKind, UserLibrary
from games.reads.playthrough_endpoints import stated_completion, stated_start


def live_ordinary_runs(
    library: UserLibrary, player_game: PlayerGame
) -> QuerySet[Playthrough]:
    """This tracked game's live ordinary runs, in the order they were made.

    The library is stated beside the parent, not inferred from it: a run
    may name another library's PlayerGame, which is the drift
    `audit_library_ownership` reports, and a count that trusted the
    parent alone would count rows this library does not hold.
    """
    return Playthrough.objects.filter(
        library=library,
        player_game=player_game,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    ).order_by("created_at", "id")


def run_to_adopt(library: UserLibrary, player_game: PlayerGame) -> Playthrough | None:
    """The run a first statement fills in, or nothing.

    A tracked game holds one run from the moment #679 tracks it. Where
    that run is the only one and states neither act, the first
    playthrough a person records is that run rather than a second one
    beside it. Nothing enforces at most one actless run at runtime, so
    this reads the shape rather than trusting it.
    """
    runs = list(live_ordinary_runs(library, player_game)[:2])
    if len(runs) != 1:
        return None
    run = runs[0]
    if stated_start(run) is not None or stated_completion(run) is not None:
        return None
    return run
