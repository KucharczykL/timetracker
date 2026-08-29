"""The status map: letter to word, one way.

The baseline backfill reads catalog letters, and so do the test
fixtures that stand in for it. Nothing writes a letter any more.
"""

from collections.abc import Mapping

from games.models import Game, PlayerGameStatus

#: One letter of Game.Status.
type LegacyStatus = str  # "f"


class UnmappedLegacyStatus(ValueError):
    """Raised for a letter the map lacks."""


#: SHELVED is absent: no letter states it. A fact
#: about the letters, not about the words.
LEGACY_STATUS_TO_PLAYER_STATUS: Mapping[LegacyStatus, PlayerGameStatus] = {
    Game.Status.UNPLAYED: PlayerGameStatus.UNPLAYED,
    Game.Status.PLAYED: PlayerGameStatus.PLAYED,
    Game.Status.FINISHED: PlayerGameStatus.COMPLETED,
    Game.Status.RETIRED: PlayerGameStatus.RETIRED,
    Game.Status.ABANDONED: PlayerGameStatus.ABANDONED,
}


def player_status_for(legacy_status: LegacyStatus) -> PlayerGameStatus:
    """The word one legacy letter records as."""
    try:
        return LEGACY_STATUS_TO_PLAYER_STATUS[legacy_status]
    except KeyError:
        raise UnmappedLegacyStatus(
            f"{legacy_status!r} is not a legacy status this map knows. "
            "Every member of Game.Status names a PlayerGameStatus."
        ) from None
