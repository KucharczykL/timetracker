"""The day figures, counted over sessions and day-precision records.

A record counts on its day when it names exactly one, so a month,
a year and a range wider than a day count in no figure here. The
tie-break names no source, so restating a session as a record
cannot move an answer.
"""

from datetime import date
from typing import NamedTuple

from django.db.models import F

from games.models import Game, HistoricalPlaytimeQuerySet, PlayerSession, UserLibrary
from games.reads.days import YearScope, year_days
from games.reads.historical_playtime import contained_in
from games.reads.historical_playtime_records import library_records
from games.reads.player_sessions import GAME
from games.reads.session_figures import GAME_KEY, SORT_NAME, scoped_sessions


class PlayDay(NamedTuple):
    day: date
    game: Game


def _day_records(library: UserLibrary, year: YearScope) -> HistoricalPlaytimeQuerySet:
    """Records naming exactly one day, that day inside the scope."""
    records = library_records(library).filter(when_lower=F("when_upper"))
    days = year_days(year)
    return records if days is None else contained_in(records, days)


def distinct_days(library: UserLibrary, year: YearScope) -> int:
    """One query: UNION is distinct, so a day both sources hold counts once."""
    session_days = (
        scoped_sessions(library, year).values_list("effective_day").distinct()
    )
    record_days = _day_records(library, year).values_list("when_lower").distinct()
    return session_days.union(record_days).count()


def _play_day(session: PlayerSession | None) -> PlayDay | None:
    if session is None:
        return None
    return PlayDay(session.effective_day, session.playthrough.player_game.game)


def first_play(library: UserLibrary, year: YearScope) -> PlayDay | None:
    """The earliest day; within it, the lower sort name, then game key."""
    return _play_day(
        scoped_sessions(library, year)
        .select_related(GAME)
        .order_by("effective_day", SORT_NAME, GAME_KEY)
        .first()
    )


def last_play(library: UserLibrary, year: YearScope) -> PlayDay | None:
    """The mirror of `first_play`, level for level."""
    return _play_day(
        scoped_sessions(library, year)
        .select_related(GAME)
        .order_by("-effective_day", f"-{SORT_NAME}", f"-{GAME_KEY}")
        .first()
    )
