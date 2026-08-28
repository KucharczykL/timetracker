"""The status map: letter to word."""

from collections.abc import Mapping

from games.models import Game, PlayerGameStatus

#: One letter of Game.Status.
type LegacyStatus = str  # "f"


class UnmappedLegacyStatus(ValueError):
    """Raised for a letter the map lacks."""


class UnmappedPlayerStatus(ValueError):
    """Raised for a status no letter holds."""


#: SHELVED is absent: no letter states it.
LEGACY_STATUS_TO_PLAYER_STATUS: Mapping[LegacyStatus, PlayerGameStatus] = {
    Game.Status.UNPLAYED: PlayerGameStatus.UNPLAYED,
    Game.Status.PLAYED: PlayerGameStatus.PLAYED,
    Game.Status.FINISHED: PlayerGameStatus.COMPLETED,
    Game.Status.RETIRED: PlayerGameStatus.RETIRED,
    Game.Status.ABANDONED: PlayerGameStatus.ABANDONED,
}

#: Inverted, so the two cannot disagree.
PLAYER_STATUS_TO_LEGACY_STATUS: Mapping[PlayerGameStatus, LegacyStatus] = {
    player_status: legacy_status
    for legacy_status, player_status in LEGACY_STATUS_TO_PLAYER_STATUS.items()
}


#: (value, label) per status, for a widget that sets one. The same
#: shape as common.components.LabeledOption, declared apart: this is
#: a domain module, and importing the component package for a pair
#: of strings would point the dependency the wrong way.
type LabeledStatus = tuple[str, str]

#: Every word a letter holds, in Game.Status declaration order.
#: SHELVED is absent, because _mirror() would have no letter to
#: write and would raise after the event had already committed.
#: #678 D removes the mirror and this list with it.
SETTABLE_PLAYER_STATUSES: tuple[LabeledStatus, ...] = tuple(
    (player_status.value, player_status.label)
    for player_status in PLAYER_STATUS_TO_LEGACY_STATUS
)


def player_status_for(legacy_status: LegacyStatus) -> PlayerGameStatus:
    """The word one legacy letter records as."""
    try:
        return LEGACY_STATUS_TO_PLAYER_STATUS[legacy_status]
    except KeyError:
        raise UnmappedLegacyStatus(
            f"{legacy_status!r} is not a legacy status this map knows. "
            "Every member of Game.Status names a PlayerGameStatus."
        ) from None


def legacy_status_for(player_status: PlayerGameStatus) -> LegacyStatus:
    """The catalog letter for one word."""
    try:
        return PLAYER_STATUS_TO_LEGACY_STATUS[player_status]
    except KeyError:
        raise UnmappedPlayerStatus(
            f"{player_status!r} has no member of Game.Status. Nothing emits "
            "it while the catalog is the read source; #678 moves the reads "
            "and takes this guard with them."
        ) from None
