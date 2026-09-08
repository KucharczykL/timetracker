"""The runs a tracked game holds."""

from django.db.models import QuerySet

from games.models import Game, PlayerGame, Playthrough, PlaythroughKind, UserLibrary
from games.reads.playthrough_endpoints import stated_completion, stated_start


def library_runs(library: UserLibrary) -> QuerySet[Playthrough]:
    """Every live ordinary run this library holds.

    The one scope the page, the filter seams and the
    numbering share. The library is stated beside the
    parent, never inferred: a run may name another
    library's PlayerGame, which is the drift
    `audit_library_ownership` reports.

    Both parents' marks read here as well: nothing
    stamps a run when its game leaves.
    """
    return Playthrough.objects.filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
        player_game__removed_at__isnull=True,
        player_game__game__removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    )


def live_ordinary_runs(
    library: UserLibrary, player_game: PlayerGame
) -> QuerySet[Playthrough]:
    """This game's live ordinary runs, oldest first.

    Its own facts, not `library_runs` narrowed:
    the caller names the parent already.
    """
    return Playthrough.objects.filter(
        library=library,
        player_game=player_game,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    ).order_by("created_at", "id")


def tracked_game(library: UserLibrary, game: Game) -> PlayerGame | None:
    """The row this library tracks the game with.

    One per pair. A removed one is not tracked.
    """
    return PlayerGame.objects.filter(
        library=library, game=game, removed_at__isnull=True
    ).first()


def completed_run_count(library: UserLibrary, player_game: PlayerGame | None) -> int:
    """How many times the game was played through.

    Runs whose completion is stated, day known or not. An
    unfinished run is not a time played through.
    """
    if player_game is None:
        return 0
    return (
        live_ordinary_runs(library, player_game)
        .filter(completion_recorded_at__isnull=False)
        .count()
    )


def run_to_adopt(library: UserLibrary, player_game: PlayerGame) -> Playthrough | None:
    """The run a first statement fills in.

    #679 gives a tracked game one run. Where it is the only
    one and states neither act, a first statement fills it
    in. Nothing enforces that shape, so this reads it.
    """
    runs = list(live_ordinary_runs(library, player_game)[:2])
    if len(runs) != 1:
        return None
    run = runs[0]
    if stated_start(run) is not None or stated_completion(run) is not None:
        return None
    return run
