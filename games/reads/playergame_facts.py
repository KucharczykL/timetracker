"""A game's facts before a batch changed them."""

import uuid
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
from games.models import PlayerGameStatus, UserLibrary
from games.reads.events import aggregate_events

#: A fact's value on the wire: a status word or a flag.
type FactValue = str | bool


@dataclass(frozen=True, slots=True)
class _Fact:
    """Where a fact lives in its payload, and its start."""

    key: str
    initial: FactValue


_FACTS: dict[str, _Fact] = {
    PLAYERGAME_STATUS_CHANGED.event_type: _Fact(
        "status", PlayerGameStatus.UNPLAYED.value
    ),
    PLAYERGAME_MASTERED_CHANGED.event_type: _Fact("mastered", False),
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.event_type: _Fact(
        "excluded_from_unfinished", False
    ),
}


@dataclass(frozen=True, slots=True)
class FactChange:
    """One fact, before a batch and as it stated."""

    before: FactValue
    stated: FactValue


def fact_change(
    library: UserLibrary,
    player_game_id: uuid.UUID,
    batch_id: uuid.UUID,
    changed: EventSpec[Any],
) -> FactChange | None:
    """None where the batch stated no such fact.

    Raises `RowUnreadable` for a stream with no creation.
    """
    fact = _FACTS[changed.event_type]
    events = list(
        aggregate_events(library, player_game_id).filter(
            event_type__in=(PLAYERGAME_CREATED.event_type, changed.event_type)
        )
    )
    ours = next(
        (
            event
            for event in events
            if event.correlation_id == batch_id
            and event.event_type == changed.event_type
        ),
        None,
    )
    if ours is None:
        return None
    earlier = [event for event in events if event.sequence < ours.sequence]
    if not earlier:
        raise RowUnreadable(
            f"PlayerGame {player_game_id} of library {library.pk} states "
            f"{changed.event_type} at sequence {ours.sequence} and no creation "
            "before it"
        )
    latest = earlier[-1]
    before = (
        fact.initial
        if latest.event_type == PLAYERGAME_CREATED.event_type
        else latest.payload[fact.key]
    )
    return FactChange(before=before, stated=ours.payload[fact.key])


@dataclass(frozen=True, slots=True)
class FactsBefore:
    """Each fact a batch changed, else None."""

    status: FactChange | None
    mastered: FactChange | None
    excluded_from_unfinished: FactChange | None

    @property
    def changed_any(self) -> bool:
        return not (
            self.status is None
            and self.mastered is None
            and self.excluded_from_unfinished is None
        )


def facts_before(
    library: UserLibrary, player_game_id: uuid.UUID, batch_id: uuid.UUID
) -> FactsBefore:
    return FactsBefore(
        status=fact_change(
            library, player_game_id, batch_id, PLAYERGAME_STATUS_CHANGED
        ),
        mastered=fact_change(
            library, player_game_id, batch_id, PLAYERGAME_MASTERED_CHANGED
        ),
        excluded_from_unfinished=fact_change(
            library,
            player_game_id,
            batch_id,
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
        ),
    )
