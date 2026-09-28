"""A game's facts before a batch changed them."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from games.events.dispatch import RowUnreadable
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_STATUS_CHANGED,
)
from games.events.vocabulary import EventSpec
from games.models import LibraryEvent, PlayerGameStatus, UserLibrary
from games.reads.events import aggregate_events
from games.reads.fact_change import FactChange

#: A payload's key for one fact.
type PayloadKey = str  # "status"


@dataclass(frozen=True, slots=True)
class _Fact[T]:
    """One fact's event, payload key, value at creation, and reading."""

    changed: EventSpec[Any]
    key: PayloadKey
    initial: T
    read: Callable[[object], T | None]


def _status(value: object) -> PlayerGameStatus | None:
    return PlayerGameStatus(value) if value in PlayerGameStatus.values else None


def _flag(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


_STATUS = _Fact(PLAYERGAME_STATUS_CHANGED, "status", PlayerGameStatus.UNPLAYED, _status)
_MASTERED = _Fact(PLAYERGAME_MASTERED_CHANGED, "mastered", False, _flag)
_EXCLUDED = _Fact(
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    "excluded_from_unfinished",
    False,
    _flag,
)


def _value[T](fact: _Fact[T], event: LibraryEvent) -> T:
    value = fact.read(event.payload.get(fact.key))
    if value is None:
        raise RowUnreadable(
            f"event {event.pk} at sequence {event.sequence} of library "
            f"{event.library_id} states {fact.key} {event.payload.get(fact.key)!r}"
        )
    return value


def _change[T](
    fact: _Fact[T],
    library: UserLibrary,
    player_game_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> FactChange[T] | None:
    """None where the batch stated no such fact."""
    changed = fact.changed.event_type
    events = list(
        aggregate_events(library, player_game_id).filter(
            event_type__in=(PLAYERGAME_CREATED.event_type, changed)
        )
    )
    ours = next(
        (
            event
            for event in events
            if event.correlation_id == batch_id and event.event_type == changed
        ),
        None,
    )
    if ours is None:
        return None
    earlier = [event for event in events if event.sequence < ours.sequence]
    if not earlier:
        raise RowUnreadable(
            f"PlayerGame {player_game_id} of library {library.pk} states "
            f"{changed} at sequence {ours.sequence} and nothing before it"
        )
    latest = earlier[-1]
    before = (
        fact.initial
        if latest.event_type == PLAYERGAME_CREATED.event_type
        else _value(fact, latest)
    )
    return FactChange(before=before, stated=_value(fact, ours))


def status_change(
    library: UserLibrary, player_game_id: uuid.UUID, batch_id: uuid.UUID
) -> FactChange[PlayerGameStatus] | None:
    """Else the word before and the one stated.

    `RowUnreadable` where nothing precedes the batch's event.
    """
    return _change(_STATUS, library, player_game_id, batch_id)


@dataclass(frozen=True, slots=True)
class BatchFactChanges:
    """Each fact a batch changed, else None."""

    status: FactChange[PlayerGameStatus] | None
    mastered: FactChange[bool] | None
    excluded_from_unfinished: FactChange[bool] | None

    @property
    def changed_any(self) -> bool:
        return not (
            self.status is None
            and self.mastered is None
            and self.excluded_from_unfinished is None
        )


def batch_fact_changes(
    library: UserLibrary, player_game_id: uuid.UUID, batch_id: uuid.UUID
) -> BatchFactChanges:
    return BatchFactChanges(
        status=status_change(library, player_game_id, batch_id),
        mastered=_change(_MASTERED, library, player_game_id, batch_id),
        excluded_from_unfinished=_change(_EXCLUDED, library, player_game_id, batch_id),
    )
