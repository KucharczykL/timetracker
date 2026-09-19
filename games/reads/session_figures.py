"""The session figures the stats page prints, one reader each.

Every tie is broken, so a figure is one row and never whichever
the planner chose: value first, then the game's sort name, then
the game's key, then the session's.
"""

from datetime import timedelta
from typing import NamedTuple

from django.db.models import Avg, Count, Q

from games.filters import GAME_SESSIONS
from games.models import (
    Game,
    HistoricalPlaytimeQuerySet,
    PlayerSession,
    PlayerSessionQuerySet,
    UserLibrary,
)
from games.reads.days import YearScope, year_days
from games.reads.historical_playtime import contained_in
from games.reads.historical_playtime_records import library_records
from games.reads.player_sessions import GAME, library_sessions

#: The tie-break's two game columns, spelled from a session.
SORT_NAME = f"{GAME}__sort_name"
GAME_KEY = f"{GAME}_id"


class LongestSession(NamedTuple):
    session: PlayerSession
    game: Game


class GameCount(NamedTuple):
    game: Game
    sessions: int


class GameAverage(NamedTuple):
    game: Game
    average: timedelta


def scoped_sessions(library: UserLibrary, year: YearScope) -> PlayerSessionQuerySet:
    """Counted sessions, narrowed to a year; None is all-time."""
    sessions = library_sessions(library)
    if year is None:
        return sessions
    return sessions.filter(effective_day__year=year)


def records_in_scope(
    library: UserLibrary, year: YearScope
) -> HistoricalPlaytimeQuerySet:
    """Live records wholly inside the year."""
    records = library_records(library)
    days = year_days(year)
    return records if days is None else contained_in(records, days)


#: A game's path to its records.
GAME_RECORDS = "player_games__historical_playtime"


def games_in_scope(library: UserLibrary, year: YearScope):
    """A session in scope or contained record."""
    return Game.objects.filter(
        Q(**{f"{GAME_SESSIONS}__in": scoped_sessions(library, year)})
        | Q(**{f"{GAME_RECORDS}__in": records_in_scope(library, year)})
    ).distinct()


def session_count(library: UserLibrary, year: YearScope) -> int:
    return scoped_sessions(library, year).count()


def longest_session(library: UserLibrary, year: YearScope) -> LongestSession | None:
    """`effective_duration`: an override or a stated time counts whole.

    The order is taken over keys and the row fetched after: sorting
    the joined rows whole costs twice as much on production shape.
    """
    key = (
        scoped_sessions(library, year)
        .order_by("-effective_duration", SORT_NAME, GAME_KEY, "id")
        .values_list("id", flat=True)
        .first()
    )
    if key is None:
        return None
    session = PlayerSession.objects.select_related(GAME).get(pk=key)
    return LongestSession(session, session.playthrough.player_game.game)


def most_sessions_game(library: UserLibrary, year: YearScope) -> GameCount | None:
    """Grouped on the session table, not walked from the Game."""
    row = (
        scoped_sessions(library, year)
        .values(GAME_KEY, SORT_NAME)
        .annotate(sessions=Count("id"))
        .order_by("-sessions", SORT_NAME, GAME_KEY)
        .values_list(GAME_KEY, "sessions")
        .first()
    )
    if row is None:
        return None
    game_id, sessions = row
    return GameCount(Game.objects.get(pk=game_id), sessions)


def highest_average_game(library: UserLibrary, year: YearScope) -> GameAverage | None:
    row = (
        scoped_sessions(library, year)
        .values(GAME_KEY, SORT_NAME)
        .annotate(average=Avg("effective_duration"))
        .order_by("-average", SORT_NAME, GAME_KEY)
        .values_list(GAME_KEY, "average")
        .first()
    )
    if row is None:
        return None
    game_id, average = row
    return GameAverage(Game.objects.get(pk=game_id), average)


def has_sessions(library: UserLibrary) -> bool:
    return library_sessions(library).exists()
