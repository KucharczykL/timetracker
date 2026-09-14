"""Every playtime figure, from one source."""

from datetime import timedelta

from django.db.models import DurationField, Value
from django.db.models.expressions import Combinable
from django.db.models.functions import Coalesce

from games.filters import SessionFilter
from games.models import Game, UserLibrary
from games.reads.playthrough_completions import YearScope
from games.reads.playtime import legacy
from games.reads.playtime.source import (
    DayInterval,
    FilteredPlaytimeSource,
    FullPlaytimeSource,
    MonthPlaytime,
    PlatformPlaytime,
    PlaytimeSource,
)

__all__ = [
    "SOURCE",
    "DayInterval",
    "FilteredPlaytimeSource",
    "FullPlaytimeSource",
    "MonthPlaytime",
    "PlatformPlaytime",
    "PlaytimeSource",
    "game_playtime",
    "playtime_between",
    "playtime_by_game",
    "playtime_by_month",
    "playtime_by_platform",
    "playtime_matching",
    "playtime_sort_key",
    "total_playtime",
]

#: Legacy table until writes reach the projection.
SOURCE: FullPlaytimeSource = legacy


def playtime_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> Combinable:
    """Each game's playtime, zero when unplayed."""
    return Coalesce(
        SOURCE.summed_by_game(library, year=year),
        Value(timedelta(0)),
        output_field=DurationField(),
    )


def playtime_sort_key(library: UserLibrary) -> Combinable:
    """The sum, NULL when unplayed: sorts last."""
    return SOURCE.summed_by_game(library)


def playtime_matching(
    library: UserLibrary, session_filter: SessionFilter | None
) -> Combinable:
    """Matching sessions' sum, NULL when none match."""
    if session_filter is None:
        return SOURCE.summed_by_game(library)
    return SOURCE.summed_by_game_matching(library, session_filter)


def game_playtime(library: UserLibrary, game: Game) -> timedelta:
    return SOURCE.game_playtime(library, game)


def total_playtime(library: UserLibrary, year: YearScope = None) -> timedelta:
    return SOURCE.total_playtime(library, year)


def playtime_between(library: UserLibrary, days: DayInterval) -> timedelta:
    return SOURCE.playtime_between(library, days)


def playtime_by_platform(
    library: UserLibrary, year: YearScope = None
) -> list[PlatformPlaytime]:
    return SOURCE.playtime_by_platform(library, year)


def playtime_by_month(library: UserLibrary, year: int) -> list[MonthPlaytime]:
    return SOURCE.playtime_by_month(library, year)
