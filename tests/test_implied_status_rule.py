"""Which implied status is stated over which."""

import uuid

import pytest

from games.commands.playergame import RecordPlayerGameFacts, held_status
from games.events.dispatch import RowUnreadable
from games.models import PlayerGame, PlayerGameStatus, status_implied_over

PLAYED = PlayerGameStatus.PLAYED
COMPLETED = PlayerGameStatus.COMPLETED


@pytest.mark.parametrize(
    ("held", "stated"),
    [
        (PlayerGameStatus.UNPLAYED, True),
        (PlayerGameStatus.PLAYED, False),
        (PlayerGameStatus.COMPLETED, False),
        (PlayerGameStatus.RETIRED, False),
        (PlayerGameStatus.SHELVED, False),
        (PlayerGameStatus.ABANDONED, False),
    ],
)
def test_played_is_stated_over_unplayed_alone(held, stated):
    assert status_implied_over(held, PLAYED) is stated


@pytest.mark.parametrize(
    ("held", "stated"),
    [
        (PlayerGameStatus.UNPLAYED, True),
        (PlayerGameStatus.PLAYED, True),
        (PlayerGameStatus.COMPLETED, False),
        (PlayerGameStatus.RETIRED, True),
        (PlayerGameStatus.SHELVED, True),
        (PlayerGameStatus.ABANDONED, True),
    ],
)
def test_completed_is_stated_wherever_it_is_not_held(held, stated):
    assert status_implied_over(held, COMPLETED) is stated


@pytest.mark.parametrize(
    "implied",
    [
        PlayerGameStatus.UNPLAYED,
        PlayerGameStatus.RETIRED,
        PlayerGameStatus.SHELVED,
        PlayerGameStatus.ABANDONED,
    ],
)
def test_no_command_implies_another_status(implied):
    with pytest.raises(ValueError, match="no act implies"):
        RecordPlayerGameFacts(game_id=uuid.uuid7(), implied_status=implied)


@pytest.mark.django_db
def test_an_unknown_held_word_is_a_defect(owned_library):
    row = PlayerGame(library=owned_library, status="mastered")

    with pytest.raises(RowUnreadable, match="mastered"):
        held_status(row)
