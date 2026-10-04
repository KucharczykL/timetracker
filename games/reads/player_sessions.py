"""Sessions a library holds and shows."""

from datetime import date
from typing import NamedTuple

from django.db.models import Max, Min

from games.models import Game, PlayerSession, PlayerSessionQuerySet, UserLibrary
from games.reads.prerelease_play import shown_play
from games.reads.unscoped import require_library

#: Sessions reach their game through the run.
GAME = "playthrough__player_game__game"


class SessionDays(NamedTuple):
    """The first and last day a game was played, inclusive."""

    first: date
    last: date


def library_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """Every live session this library holds.

    A copy of `library_runs` breaks this quietly. Its `kind`
    condition drops the sessions of the imported-history bucket.
    `alive()` alone keeps the sessions of a removed catalog game.
    The run's and its tracked game's libraries are stated too:
    either can name another library's row.
    """
    library = require_library(library)
    return PlayerSession.objects.filter(
        library=library,
        playthrough__library=library,
        playthrough__player_game__library=library,
        removed_at__isnull=True,
        playthrough__removed_at__isnull=True,
        playthrough__player_game__removed_at__isnull=True,
        playthrough__player_game__game__removed_at__isnull=True,
    )


def shown_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """The sessions figures and lists hold."""
    return library_sessions(library).filter(shown_play(library))


def _with_row_path(sessions: PlayerSessionQuerySet) -> PlayerSessionQuerySet:
    return sessions.select_related(
        f"{GAME}__platform", "device", "release__edition", "release__platform"
    )


def readable_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """One named session's row path: every row."""
    return _with_row_path(library_sessions(library))


def listed_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """The row path lists read: shown rows."""
    return _with_row_path(shown_sessions(library))


def game_sessions(library: UserLibrary, game: Game) -> PlayerSessionQuerySet:
    """Every live session at one game."""
    return library_sessions(library).filter(**{GAME: game})


def game_session_days(library: UserLibrary, game: Game) -> SessionDays | None:
    """First and last session day; None unplayed."""
    span = game_sessions(library, game).aggregate(
        first=Min("effective_day"), last=Max("effective_day")
    )
    if span["last"] is None:
        return None
    return SessionDays(span["first"], span["last"])
