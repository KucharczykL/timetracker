"""The runs a tracked game holds."""

from django.db.models import QuerySet

from games.models import (
    Game,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
    PlaythroughQuerySet,
    UserLibrary,
)
from games.reads.playthrough_activity import activity_clock
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.reads.playthrough_referrers import blocking_referrer


def library_runs(library: UserLibrary) -> PlaythroughQuerySet:
    """Every live ordinary run this library holds.

    The one scope the page, the filter reads and the
    numbering share. The library is stated beside the
    parent, never inferred: a run may name another
    library's PlayerGame, which is the drift
    `audit_library_ownership` reports.

    Both parents' marks read here as well: nothing
    stamps a run when its game leaves. Carries no
    condition alias: `runs_with_condition` states that.
    """
    return Playthrough.objects.filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
        player_game__removed_at__isnull=True,
        player_game__game__removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    )


def runs_with_condition(library: UserLibrary) -> PlaythroughQuerySet:
    """The same runs, each carrying its condition."""
    return library_runs(library).annotated_for_filtering(activity_clock(library))


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


def buckets_of(library: UserLibrary, player_game: PlayerGame) -> QuerySet[Playthrough]:
    """This game's live imported-history runs, oldest first.

    Plural: nothing holds a tracked game to one. Its own
    facts, as `live_ordinary_runs` states them, because
    the caller names the parent already.
    """
    return Playthrough.objects.filter(
        library=library,
        player_game=player_game,
        removed_at__isnull=True,
        kind=PlaythroughKind.IMPORTED_HISTORY,
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


def sole_ordinary_run(library: UserLibrary, game: Game) -> Playthrough | None:
    """The one live ordinary run a game holds, or none.

    What a page seeds, so the seed and the picker state one
    rule: a game holding several runs is a choice.
    """
    tracked = tracked_game(library, game)
    if tracked is None:
        return None
    runs = list(live_ordinary_runs(library, tracked)[:2])
    return runs[0] if len(runs) == 1 else None


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


def placeholder_run(
    library: UserLibrary, player_game: PlayerGame
) -> Playthrough | None:
    """The empty run tracking minted, and nothing else.

    Narrower than `run_to_adopt`, which names any sole run
    that states neither act. A person who types a name asks
    for the run they named: a run that a registered referrer
    names -- a live session, a live record -- would take the
    new label and carry those rows under it.

    A blank name as well, because a named run is one
    somebody already called something.
    """
    run = run_to_adopt(library, player_game)
    if run is None or run.name != "":
        return None
    return None if blocking_referrer(run) is not None else run
