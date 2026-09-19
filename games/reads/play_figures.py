"""Day figures over sessions and one-day records."""

import uuid
from datetime import date
from typing import NamedTuple

from django.db.models import F

from games.models import Game, HistoricalPlaytimeQuerySet, UserLibrary
from games.reads.days import YearScope, year_days
from games.reads.historical_playtime import contained_in
from games.reads.historical_playtime_records import library_records
from games.reads.player_sessions import GAME
from games.reads.session_figures import GAME_KEY, SORT_NAME, scoped_sessions


class PlayDay(NamedTuple):
    day: date
    game: Game
    #: A record alone answered; no session link.
    from_record: bool


#: The tie-break's game columns, from a record.
RECORD_GAME = "player_game__game"
RECORD_SORT_NAME = f"{RECORD_GAME}__sort_name"
RECORD_GAME_KEY = f"{RECORD_GAME}_id"

type PlayKey = tuple[date, str, uuid.UUID]  # day, sort name, game key


def _day_records(library: UserLibrary, year: YearScope) -> HistoricalPlaytimeQuerySet:
    """Records naming one day inside the scope."""
    records = library_records(library).filter(when_lower=F("when_upper"))
    days = year_days(year)
    return records if days is None else contained_in(records, days)


def distinct_days(library: UserLibrary, year: YearScope) -> int:
    """UNION is distinct: a shared day counts once."""
    session_days = (
        scoped_sessions(library, year).values_list("effective_day").distinct()
    )
    record_days = _day_records(library, year).values_list("when_lower").distinct()
    return session_days.union(record_days).count()


def _play_key(play: PlayDay) -> PlayKey:
    return (play.day, play.game.sort_name, play.game.pk)


def _session_end(
    library: UserLibrary, year: YearScope, *, latest: bool
) -> PlayDay | None:
    order = ("effective_day", SORT_NAME, GAME_KEY)
    session = (
        scoped_sessions(library, year)
        .select_related(GAME)
        .order_by(*(f"-{column}" for column in order) if latest else order)
        .first()
    )
    if session is None:
        return None
    return PlayDay(session.effective_day, session.playthrough.player_game.game, False)


def _record_end(
    library: UserLibrary, year: YearScope, *, latest: bool
) -> PlayDay | None:
    order = ("when_lower", RECORD_SORT_NAME, RECORD_GAME_KEY)
    record = (
        _day_records(library, year)
        .select_related(RECORD_GAME)
        .order_by(*(f"-{column}" for column in order) if latest else order)
        .first()
    )
    if record is None:
        return None
    return PlayDay(record.when_lower, record.player_game.game, True)


def _pick(library: UserLibrary, year: YearScope, *, latest: bool) -> PlayDay | None:
    """One read a source; tie-break in Python.

    The Python comparison of sort_name agrees with the two SQL
    orders only because the database collates in C.UTF-8. A tie on
    all three levels answers the session.
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
    if latest:
        return max(candidates, key=lambda play: (_play_key(play), not play.from_record))
    return min(candidates, key=lambda play: (_play_key(play), play.from_record))


def first_play(library: UserLibrary, year: YearScope) -> PlayDay | None:
    """Earliest day; then sort name, game key."""
    return _pick(library, year, latest=False)


def last_play(library: UserLibrary, year: YearScope) -> PlayDay | None:
    """The mirror of `first_play`, level for level."""
    return _pick(library, year, latest=True)
