"""Both directions of the status map."""

import pytest

from games.models import Game, PlayerGameStatus
from games.playergame_status import (
    UnmappedLegacyStatus,
    UnmappedPlayerStatus,
    legacy_status_for,
    player_status_for,
)


@pytest.mark.parametrize("legacy_status", [member.value for member in Game.Status])
def test_every_legacy_status_maps_and_round_trips(legacy_status):
    player_status = player_status_for(legacy_status)
    assert legacy_status_for(player_status) == legacy_status


def test_shelved_has_no_legacy_status():
    #: The catalog cannot store the sixth member, so the
    #: mirror raises rather than invent a letter.
    with pytest.raises(UnmappedPlayerStatus, match="SHELVED"):
        legacy_status_for(PlayerGameStatus.SHELVED)


def test_an_unknown_letter_is_refused():
    with pytest.raises(UnmappedLegacyStatus, match="'z'"):
        player_status_for("z")


def test_finished_is_completed():
    #: The one state the two vocabularies name differently.
    assert player_status_for(Game.Status.FINISHED) is PlayerGameStatus.COMPLETED
