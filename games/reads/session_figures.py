"""The session figures the stats page prints, one reader each.

Every tie is broken, so a figure is one row and never whichever
the planner chose: value first, then the game's sort name, then
the game's key, then the session's.
"""

from datetime import date, timedelta
from typing import NamedTuple

from django.db.models import Avg, Count, Q

from games.filters import GAME_SESSIONS
from games.models import Game, PlayerSession, PlayerSessionQuerySet, UserLibrary
from games.reads.player_sessions import GAME, library_sessions
from games.reads.playthrough_completions import YearScope


class LongestSession(NamedTuple):
    session: PlayerSession
    game: Game


class GameCount(NamedTuple):
    game: Game
    sessions: int


class GameAverage(NamedTuple):
    game: Game
    average: timedelta


class PlayDay(NamedTuple):
    day: date
    game: Game


def scoped_sessions(library: UserLibrary, year: YearScope) -> PlayerSessionQuerySet:
    """Counted sessions, narrowed to a year; None is all-time."""
    sessions = library_sessions(library).select_related(GAME)
    if year is None:
        return sessions
    return sessions.filter(effective_day__year=year)


def counted_sessions_q(library: UserLibrary, year: YearScope) -> Q:
    """`library_sessions`' marks and the year, spelled from a Game."""
    counted = Q(
        player_games__library=library,
        player_games__removed_at__isnull=True,
        player_games__playthroughs__library=library,
        player_games__playthroughs__removed_at__isnull=True,
        **{
            f"{GAME_SESSIONS}__library": library,
            f"{GAME_SESSIONS}__removed_at__isnull": True,
        },
    )
    if year is None:
        return counted
    return counted & Q(**{f"{GAME_SESSIONS}__effective_day__year": year})


def games_in_scope(library: UserLibrary, year: YearScope):
    return Game.objects.filter(
        **{f"{GAME_SESSIONS}__in": scoped_sessions(library, year)}
    ).distinct()


def session_count(library: UserLibrary, year: YearScope) -> int:
    return scoped_sessions(library, year).count()


def distinct_days(library: UserLibrary, year: YearScope) -> int:
    return (
        scoped_sessions(library, year)
        .values("effective_day")
        .distinct()
        .aggregate(days=Count("effective_day"))["days"]
    )


def longest_session(library: UserLibrary, year: YearScope) -> LongestSession | None:
    """`effective_duration`: an override or a stated time counts whole."""
    session = (
        scoped_sessions(library, year)
        .order_by("-effective_duration", f"{GAME}__sort_name", f"{GAME}_id", "id")
        .first()
    )
    if session is None:
        return None
    return LongestSession(session, session.playthrough.player_game.game)


def most_sessions_game(library: UserLibrary, year: YearScope) -> GameCount | None:
    game = (
        games_in_scope(library, year)
        .annotate(
            session_count=Count(GAME_SESSIONS, filter=counted_sessions_q(library, year))
        )
        .order_by("-session_count", "sort_name", "pk")
        .first()
    )
    if game is None:
        return None
    return GameCount(game, game.session_count)


def highest_average_game(library: UserLibrary, year: YearScope) -> GameAverage | None:
    game = (
        games_in_scope(library, year)
        .annotate(
            session_average=Avg(
                f"{GAME_SESSIONS}__effective_duration",
                filter=counted_sessions_q(library, year),
            )
        )
        .order_by("-session_average", "sort_name", "pk")
        .first()
    )
    if game is None:
        return None
    return GameAverage(game, game.session_average)


def _play_day(session: PlayerSession | None) -> PlayDay | None:
    if session is None:
        return None
    return PlayDay(session.effective_day, session.playthrough.player_game.game)


def first_play(library: UserLibrary, year: YearScope) -> PlayDay | None:
    """The earliest day; within it, the lower key."""
    return _play_day(
        scoped_sessions(library, year).order_by("effective_day", "id").first()
    )


def last_play(library: UserLibrary, year: YearScope) -> PlayDay | None:
    return _play_day(
        scoped_sessions(library, year).order_by("-effective_day", "-id").first()
    )


def has_sessions(library: UserLibrary) -> bool:
    return library_sessions(library).exists()
