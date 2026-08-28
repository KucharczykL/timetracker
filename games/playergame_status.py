"""Both directions of the map between the catalog's status letter and the
event vocabulary's word.

Issue #677. #676 needed one direction and kept it inside the backfill. The
write path holds both vocabularies at once, so both directions live here and
#678 deletes this module with the mirror that needs it.
"""

from collections.abc import Mapping

from games.models import Game, PlayerGameStatus

#: One letter of Game.Status.
type LegacyStatus = str  # "f"


class UnmappedLegacyStatus(ValueError):
    """Raised for a legacy letter the map does not know."""


class UnmappedPlayerStatus(ValueError):
    """Raised for a player status the catalog column cannot hold."""


#: A recorded payload cannot be upcast, so the letters become words here and
#: never reach an event. SHELVED is absent: no legacy column states it.
LEGACY_STATUS_TO_PLAYER_STATUS: Mapping[LegacyStatus, PlayerGameStatus] = {
    Game.Status.UNPLAYED: PlayerGameStatus.UNPLAYED,
    Game.Status.PLAYED: PlayerGameStatus.PLAYED,
    Game.Status.FINISHED: PlayerGameStatus.COMPLETED,
    Game.Status.RETIRED: PlayerGameStatus.RETIRED,
    Game.Status.ABANDONED: PlayerGameStatus.ABANDONED,
}

#: Inverted rather than written twice, so the two cannot fall out of step.
PLAYER_STATUS_TO_LEGACY_STATUS: Mapping[PlayerGameStatus, LegacyStatus] = {
    player_status: legacy_status
    for legacy_status, player_status in LEGACY_STATUS_TO_PLAYER_STATUS.items()
}


def player_status_for(legacy_status: LegacyStatus) -> PlayerGameStatus:
    """The word a recorded payload carries for one legacy letter."""
    try:
        return LEGACY_STATUS_TO_PLAYER_STATUS[legacy_status]
    except KeyError:
        raise UnmappedLegacyStatus(
            f"{legacy_status!r} is not a legacy status this map knows. "
            "Every member of Game.Status names a PlayerGameStatus."
        ) from None


def legacy_status_for(player_status: PlayerGameStatus) -> LegacyStatus:
    """The letter the catalog column holds for one recorded word."""
    try:
        return PLAYER_STATUS_TO_LEGACY_STATUS[player_status]
    except KeyError:
        raise UnmappedPlayerStatus(
            f"{player_status!r} has no member of Game.Status. Nothing emits "
            "it while the catalog is the read source; #678 moves the reads "
            "and takes this guard with them."
        ) from None
