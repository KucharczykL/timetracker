"""The runs a test states, through the commands that state them.

#679 gives every tracked game one run, so a test that wants
that run filled in states its endpoints onto it, and a test
that wants a second one states a second. Both go through the
write path, because a row written by hand states no event and
replays into nothing.
"""

from django.contrib.auth.models import User

from games.commands.playthrough import ActStatement, CreatePlaythrough
from games.events.dispatch import dispatch
from games.models import Game, Playthrough, PlaythroughKind, UserLibrary
from games.writes.playergame import new_correlation_id
from games.writes.playthrough import RunDraft, restate_run


def _born_run(library: UserLibrary, game: Game) -> Playthrough | None:
    """The run a tracked game was born with."""
    return Playthrough.objects.filter(
        library=library,
        player_game__game=game,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    ).first()


def state_run(
    user: User,
    game: Game,
    *,
    started: ActStatement | None = None,
    completed: ActStatement | None = None,
    note: str = "",
) -> Playthrough:
    """Fill in the run the game was born with.

    An endpoint stated as None is an act that never
    happened, the same way a draft states it.
    """
    run = _born_run(user.library, game)
    assert run is not None, f"Nothing tracks game {game.pk}, so it holds no run."
    restate_run(
        user,
        run,
        RunDraft(started=started, completed=completed, note=note),
        correlation_id=new_correlation_id(),
    )
    run.refresh_from_db()
    return run


def another_run(
    user: User,
    game: Game,
    *,
    started: ActStatement | None = None,
    completed: ActStatement | None = None,
    note: str = "",
) -> Playthrough:
    """State one more run at a game, beside the ones it holds."""
    held = set(
        Playthrough.objects.filter(player_game__game=game).values_list("pk", flat=True)
    )
    dispatch(
        CreatePlaythrough(
            game_id=game.pk, started=started, completed=completed, note=note
        ),
        actor=user,
        library=user.library,
        idempotency_key=str(new_correlation_id()),
    )
    return Playthrough.objects.exclude(pk__in=held).get(player_game__game=game)
