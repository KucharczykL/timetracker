"""Letter to word, the direction that remains."""

import pytest

from games.models import Game, PlayerGameStatus
from games.playergame_status import UnmappedLegacyStatus, player_status_for

pytestmark = pytest.mark.untracked_games


@pytest.mark.parametrize("legacy_status", [member.value for member in Game.Status])
def test_every_legacy_status_maps(legacy_status):
    assert isinstance(player_status_for(legacy_status), PlayerGameStatus)


def test_an_unknown_letter_is_refused():
    with pytest.raises(UnmappedLegacyStatus, match="'z'"):
        player_status_for("z")


def test_finished_is_completed():
    #: The one state the two vocabularies name differently.
    assert player_status_for(Game.Status.FINISHED) is PlayerGameStatus.COMPLETED
