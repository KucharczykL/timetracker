"""Baseline PlayerGame events for the games a library already holds.

Issue #676. The catalog states which games a library has; the event log
states nothing until this runs. Every live game becomes a tracked game,
expressed as events and folded by the PlayerGames projector, because a
projection row is written by its projector and by nothing else.
"""

from collections.abc import Mapping
from datetime import datetime

from django.utils import timezone

from games.models import Game, PlayerGameStatus
from timetracker.temporal import TemporalValue

#: Names the issue in every key and every source_metadata blob.
PGAME_ISSUE = 676
KEY_PREFIX = "backfill:676:playergame"

#: One letter of Game.Status.
type LegacyStatus = str  # "f"

#: A recorded payload cannot be upcast, so the letters become words here and
#: never reach an event. SHELVED is absent: no legacy column states it.
LEGACY_STATUS_TO_PLAYER_STATUS: Mapping[LegacyStatus, PlayerGameStatus] = {
    Game.Status.UNPLAYED: PlayerGameStatus.UNPLAYED,
    Game.Status.PLAYED: PlayerGameStatus.PLAYED,
    Game.Status.FINISHED: PlayerGameStatus.COMPLETED,
    Game.Status.RETIRED: PlayerGameStatus.RETIRED,
    Game.Status.ABANDONED: PlayerGameStatus.ABANDONED,
}


class UnmappedLegacyStatus(ValueError):
    """Raised for a legacy letter the map does not know."""


def player_status_for(legacy_status: LegacyStatus) -> PlayerGameStatus:
    """The word a recorded payload carries for one legacy letter."""
    try:
        return LEGACY_STATUS_TO_PLAYER_STATUS[legacy_status]
    except KeyError:
        raise UnmappedLegacyStatus(
            f"{legacy_status!r} is not a legacy status this backfill maps. "
            "Every member of Game.Status names a PlayerGameStatus."
        ) from None


def transition_effective_time(timestamp: datetime | None) -> TemporalValue:
    """When the transition happened, at the precision that is honest.

    A non-null legacy timestamp is the effective transition time rather than
    a recording time: live signals wrote the moment of the player's action,
    and the original data migration used the earliest Session, the refund or
    drop date, or the PlayEvent completion date. A null one stays unknown, so
    it enters approximate history rather than claiming a day.
    """
    if timestamp is None:
        return TemporalValue.unknown()
    return TemporalValue.from_day(timezone.localtime(timestamp).date())
