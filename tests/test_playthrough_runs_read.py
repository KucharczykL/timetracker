"""The runs a tracked game holds."""

import uuid

import pytest
from django.utils import timezone

from games.commands.playthrough import CreatePlaythrough
from games.events.dispatch import dispatch
from games.models import Game, PlayerGame, Playthrough, PlaythroughKind
from games.reads.playthrough_runs import live_ordinary_runs, run_to_adopt
from games.writes.playergame import new_correlation_id, track_game

#: Every test wants the run #679 states,
#: so none starts from the fixture's bare row.
pytestmark = pytest.mark.untracked_games


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def a_tracked_game(owned_user, game) -> PlayerGame:
    """Track the game as a request does."""
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return PlayerGame.objects.get(library=owned_user.library, game=game)


def a_second_run(owned_user, owned_library, game) -> None:
    """One more run, beside the game's first."""
    dispatch(
        CreatePlaythrough(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )


@pytest.mark.django_db(transaction=True)
def test_a_tracked_game_holds_one_live_ordinary_run(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)

    runs = live_ordinary_runs(owned_library, tracked)

    assert runs.count() == 1
    assert runs.get().kind == PlaythroughKind.ORDINARY


@pytest.mark.django_db(transaction=True)
def test_the_run_a_tracked_game_is_born_with_is_the_one_adopted(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)

    adopted = run_to_adopt(owned_library, tracked)

    assert adopted is not None
    assert adopted.start_recorded_at is None
    assert adopted.completion_recorded_at is None


@pytest.mark.django_db(transaction=True)
def test_a_second_run_leaves_nothing_to_adopt(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)

    a_second_run(owned_user, owned_library, game)

    assert run_to_adopt(owned_library, tracked) is None


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_is_not_live(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)

    #: The projector's mark, stated with an UPDATE:
    #: RemovePlaythrough refuses a tracked game's last run.
    Playthrough.objects.filter(player_game=tracked).update(removed_at=timezone.now())

    assert live_ordinary_runs(owned_library, tracked).count() == 0
    assert run_to_adopt(owned_library, tracked) is None
