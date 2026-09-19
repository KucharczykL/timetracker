"""The day figures, counted over sessions and day-precision records.

A record counts on its day when it names exactly one, so a month,
a year and a range wider than a day count in no figure here. The
tie-break names no source, so restating a session as a record
cannot move an answer.
"""

from datetime import date
from typing import NamedTuple

from django.db.models import Count

from games.models import Game, PlayerSession, UserLibrary
from games.reads.player_sessions import GAME
from games.reads.playthrough_completions import YearScope
from games.reads.session_figures import GAME_KEY, SORT_NAME, scoped_sessions


class PlayDay(NamedTuple):
    day: date
    game: Game


def distinct_days(library: UserLibrary, year: YearScope) -> int:
    return (
        scoped_sessions(library, year)
        .values("effective_day")
        .distinct()
        .aggregate(days=Count("effective_day"))["days"]
    )


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
