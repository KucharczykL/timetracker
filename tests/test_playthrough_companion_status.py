"""#683: the status a lifecycle act offers."""

import pytest

from games.models import Game, PlayerGameStatus
from games.reads.companion_status import played_is_offered
from games.writes.playergame import new_correlation_id, record_facts, track_game

#: TrackGame states the run, so the real command runs.
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]


@pytest.fixture
def game(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def tracked(owned_user, game) -> Game:
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return game


def state(owned_user, game, status: PlayerGameStatus) -> None:
    record_facts(owned_user, game, status=status, correlation_id=new_correlation_id())


def test_an_untracked_game_is_offered_played(owned_library, game):
    assert played_is_offered(owned_library, game) is True


def test_a_game_with_no_name_yet_is_offered_played(owned_library):
    """The generic Add form, before a game is picked."""
    assert played_is_offered(owned_library, None) is True


def test_an_unplayed_game_is_offered_played(owned_library, tracked):
    assert played_is_offered(owned_library, tracked) is True


@pytest.mark.parametrize(
    "status",
    [
        PlayerGameStatus.PLAYED,
        PlayerGameStatus.COMPLETED,
        PlayerGameStatus.RETIRED,
        PlayerGameStatus.SHELVED,
        PlayerGameStatus.ABANDONED,
    ],
)
def test_every_stronger_status_is_offered_nothing(
    owned_user, owned_library, tracked, status
):
    """A checked box here would walk the status back."""
    state(owned_user, tracked, status)

    assert played_is_offered(owned_library, tracked) is False
