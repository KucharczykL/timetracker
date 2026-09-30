"""A game's facts before a batch changed them."""

import uuid
from dataclasses import dataclass, fields

from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_DROPPED_CHANGED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_STATUS_CHANGED,
)
from games.models import PlayerGameStatus, UserLibrary
from games.reads.fact_change import Fact, FactChange, fact_change


def _status(value: object) -> PlayerGameStatus | None:
    return PlayerGameStatus(value) if value in PlayerGameStatus.values else None


def _flag(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


_STATUS = Fact(
    PLAYERGAME_CREATED,
    PLAYERGAME_STATUS_CHANGED,
    "status",
    _status,
    initial=PlayerGameStatus.UNPLAYED,
)
_MASTERED = Fact(
    PLAYERGAME_CREATED, PLAYERGAME_MASTERED_CHANGED, "mastered", _flag, initial=False
)
_UNFINISHED = Fact(
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    "excluded_from_unfinished",
    _flag,
    initial=False,
)
_DROPPED = Fact(
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_DROPPED_CHANGED,
    "excluded_from_dropped",
    _flag,
    initial=False,
)


def status_change(
    library: UserLibrary, player_game_id: uuid.UUID, batch_id: uuid.UUID
) -> FactChange[PlayerGameStatus] | None:
    """Else the word before and the one stated.

    `RowUnreadable` where nothing precedes the batch's event.
    """
    return fact_change(_STATUS, library, player_game_id, batch_id)


@dataclass(frozen=True, slots=True)
class BatchFactChanges:
    """Each fact a batch changed, else None."""

    status: FactChange[PlayerGameStatus] | None
    mastered: FactChange[bool] | None
    excluded_from_unfinished: FactChange[bool] | None
    excluded_from_dropped: FactChange[bool] | None

    @property
    def changed_any(self) -> bool:
        return any(getattr(self, fact.name) is not None for fact in fields(self))


def batch_fact_changes(
    library: UserLibrary, player_game_id: uuid.UUID, batch_id: uuid.UUID
) -> BatchFactChanges:
    return BatchFactChanges(
        status=status_change(library, player_game_id, batch_id),
        mastered=fact_change(_MASTERED, library, player_game_id, batch_id),
        excluded_from_unfinished=fact_change(
            _UNFINISHED, library, player_game_id, batch_id
        ),
        excluded_from_dropped=fact_change(_DROPPED, library, player_game_id, batch_id),
    )
