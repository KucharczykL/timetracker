"""The sessions a library counts."""

import uuid
from datetime import date
from typing import NamedTuple

from django.db.models import Max, Min

from games.models import Game, PlayerSession, PlayerSessionQuerySet, UserLibrary
from games.reads.unscoped import require_library

#: A catalog game's key, as a caller holds it.
type GameId = uuid.UUID

#: Sessions reach their game through the run.
GAME = "playthrough__player_game__game"


class SessionDays(NamedTuple):
    """The first and last day a game was played, inclusive."""

    first: date
    last: date


def library_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """Every live session this library counts.

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


def readable_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """The row path the list and the API share: run, game, platform, device."""
    return library_sessions(library).select_related(f"{GAME}__platform", "device")


def game_sessions(library: UserLibrary, game: Game) -> PlayerSessionQuerySet:
    """The counted sessions at one game, on any of its runs."""
    return library_sessions(library).filter(**{GAME: game})


def game_session_days(library: UserLibrary, game: Game) -> SessionDays | None:
    """The span of days the game's counted sessions land on; None unplayed."""
    span = game_sessions(library, game).aggregate(
        first=Min("effective_day"), last=Max("effective_day")
    )
    if span["last"] is None:
        return None
    return SessionDays(span["first"], span["last"])
