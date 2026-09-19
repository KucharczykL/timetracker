"""Day figures and played games over both sources."""

import uuid
from datetime import date
from enum import Enum, auto
from typing import NamedTuple, Self

from django.db.models import Q

from games.models import Game, HistoricalPlaytime, PlayerSession, UserLibrary
from games.reads.days import YearScope
from games.reads.historical_playtime_records import one_day_records, records_in_scope
from games.reads.player_sessions import GAME
from games.reads.session_figures import GAME_KEY, SORT_NAME, scoped_sessions


class PlaySource(Enum):
    SESSION = auto()
    RECORD = auto()


class PlayDay(NamedTuple):
    day: date
    game: Game
    source: PlaySource

    @classmethod
    def of_session(cls, session: PlayerSession) -> Self:
        return cls(
            session.effective_day,
            session.playthrough.player_game.game,
            PlaySource.SESSION,
        )

    @classmethod
    def of_record(cls, record: HistoricalPlaytime) -> Self:
        """A one-day record; the scope keeps every other out."""
        if record.when_lower is None or record.when_lower != record.when_upper:
            raise ValueError(f"record {record.pk} names no single day")
        return cls(record.when_lower, record.player_game.game, PlaySource.RECORD)


#: A game's path to its records.
GAME_RECORDS = "player_games__historical_playtime"

#: The tie-break's game columns, from a record.
RECORD_GAME = "player_game__game"
RECORD_SORT_NAME = f"{RECORD_GAME}__sort_name"
RECORD_GAME_KEY = f"{RECORD_GAME}_id"


class PlayKey(NamedTuple):
    """The order both SQL legs state."""

    day: date
    sort_name: str
    game_key: uuid.UUID


#: Each leg's order, level for level.
SESSION_ORDER = ("effective_day", SORT_NAME, GAME_KEY)
RECORD_ORDER = ("when_lower", RECORD_SORT_NAME, RECORD_GAME_KEY)


def games_in_scope(library: UserLibrary, year: YearScope):
    """A session in scope or contained record."""
    sessions = scoped_sessions(library, year).values(f"{GAME}_id")
    records = records_in_scope(library, year).values(f"{RECORD_GAME}_id")
    return Game.objects.filter(Q(id__in=sessions) | Q(id__in=records))


def distinct_days(library: UserLibrary, year: YearScope) -> int:
    """UNION is distinct: a shared day counts once."""
    session_days = (
        scoped_sessions(library, year).values_list("effective_day").distinct()
    )
    record_days = one_day_records(library, year).values_list("when_lower").distinct()
    return session_days.union(record_days).count()


def _play_key(play: PlayDay) -> PlayKey:
    return PlayKey(play.day, play.game.sort_name, play.game.pk)


def _ordered(order: tuple[str, ...], *, latest: bool) -> tuple[str, ...]:
    return tuple(f"-{column}" for column in order) if latest else order


def _session_end(
    library: UserLibrary, year: YearScope, *, latest: bool
) -> PlayDay | None:
    session = (
        scoped_sessions(library, year)
        .select_related(GAME)
        .order_by(*_ordered(SESSION_ORDER, latest=latest))
        .first()
    )
    return None if session is None else PlayDay.of_session(session)


def _record_end(
    library: UserLibrary, year: YearScope, *, latest: bool
) -> PlayDay | None:
    record = (
        one_day_records(library, year)
        .select_related(RECORD_GAME)
        .order_by(*_ordered(RECORD_ORDER, latest=latest))
        .first()
    )
    return None if record is None else PlayDay.of_record(record)


def _pick(library: UserLibrary, year: YearScope, *, latest: bool) -> PlayDay | None:
    """One read a source; tie-break in Python.

    The Python comparison of sort_name agrees with the two SQL
    orders only because the database collates in C.UTF-8. The
    session is listed first, so a tie on every level answers it.
    """
    candidates = [
        play
        for play in (
            _session_end(library, year, latest=latest),
            _record_end(library, year, latest=latest),
        )
        if play is not None
    ]
    if not candidates:
        return None
    return (max if latest else min)(candidates, key=_play_key)


def first_play(library: UserLibrary, year: YearScope) -> PlayDay | None:
    """Earliest day; then sort name, game key."""
    return _pick(library, year, latest=False)


def last_play(library: UserLibrary, year: YearScope) -> PlayDay | None:
    """The mirror of `first_play`, level for level."""
    return _pick(library, year, latest=True)
