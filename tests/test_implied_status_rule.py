"""Which status an act implies over the held one."""

import pytest

from games.models import PlayerGameStatus, status_implied_over

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
def test_no_act_implies_another_status(implied):
    with pytest.raises(ValueError, match="implies"):
        status_implied_over(PlayerGameStatus.UNPLAYED, implied)
