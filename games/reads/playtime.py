"""Every playtime figure: sessions plus historical records."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple
from uuid import UUID

from django.db.models import DurationField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, NullIf, TruncMonth

from games.filters import PlayerSessionFilter, filter_query_context_for_library
from games.models import Game, PlayerSessionQuerySet, UserLibrary
from games.reads.days import DayInterval
from games.reads.historical_playtime import (
    game_historical_playtime,
    historical_by_month,
    historical_by_platform,
    historical_summed_by_game,
    historical_total,
    historical_totals,
    historical_years,
)
from games.reads.player_sessions import GAME, library_sessions
from games.reads.playthrough_completions import YearScope
from games.reads.sums import (
    ZERO,
    Playtime,
    PlaytimeSum,
    UnscopedPlaytimeRead,
    UnscopedSum,
)

__all__ = [
    "MonthPlaytime",
    "PlatformPlaytime",
    "PlaytimeBreakdown",
    "PlaytimeParts",
    "UnscopedPlaytimeRead",
    "game_playtime",
    "game_playtime_between",
    "played_years",
    "playtime_between",
    "playtime_between_each",
    "playtime_by_game",
    "playtime_by_month",
    "playtime_by_platform",
    "playtime_matching",
    "playtime_parts_by_game",
    "playtime_sort_key",
    "total_playtime",
    "tracked_summed_by_game",
    "tracked_summed_by_game_matching",
]

PLATFORM = f"{GAME}__platform"


@dataclass(frozen=True, slots=True)
class PlaytimeBreakdown:
    """Tracked sessions beside historical records."""

    tracked: timedelta
    historical: timedelta

    @property
    def total(self) -> timedelta:
        return self.tracked + self.historical


NOTHING = PlaytimeBreakdown(timedelta(0), timedelta(0))


class PlatformPlaytime(NamedTuple):
    #: None is the unspecified-platform bucket.
    platform_id: UUID | None
    platform_name: str | None
    playtime: PlaytimeBreakdown


class MonthPlaytime(NamedTuple):
    #: The first day of the month.
    month: date
    playtime: PlaytimeBreakdown


class PlaytimeParts(NamedTuple):
    """Per-game halves, each zero when unplayed.

    No total member: it would run both subqueries again.
    """

    tracked: Playtime
    historical: Playtime


def _year_days(year: YearScope) -> DayInterval | None:
    return None if year is None else DayInterval.year(year)


def _sessions(library: UserLibrary, year: YearScope = None) -> PlayerSessionQuerySet:
    """Counted sessions, narrowed to a year."""
    sessions = library_sessions(library)
    if year is None:
        return sessions
    return sessions.filter(effective_day__year=year)


def _on_days(days: DayInterval) -> Q:
    return Q(effective_day__range=(days.first, days.last))


def _total(sessions: PlayerSessionQuerySet) -> timedelta:
    return sessions.aggregate(total=Coalesce(Sum("effective_duration"), ZERO))["total"]


def _summed(sessions: PlayerSessionQuerySet) -> PlaytimeSum:
    return Subquery(
        sessions.filter(**{GAME: OuterRef("pk")})
        .values(GAME)
        .annotate(total=Sum("effective_duration"))
        .values("total"),
        output_field=DurationField(),
    )


def _zero_when_null(figure: PlaytimeSum) -> Playtime:
    return Coalesce(figure, ZERO, output_field=DurationField())


def game_playtime(library: UserLibrary, game: Game) -> PlaytimeBreakdown:
    return PlaytimeBreakdown(
        tracked=_total(_sessions(library).filter(**{GAME: game})),
        historical=game_historical_playtime(library, game),
    )


def game_playtime_between(
    library: UserLibrary, game: Game, days: DayInterval
) -> PlaytimeBreakdown:
    """One game's playtime over inclusive days."""
    return PlaytimeBreakdown(
        tracked=_total(_sessions(library).filter(_on_days(days), **{GAME: game})),
        historical=game_historical_playtime(library, game, within=days),
    )


def tracked_summed_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> PlaytimeSum:
    """No library compiles, then refuses to execute."""
    if library is None:
        return UnscopedSum()
    return _summed(_sessions(library, year))


def tracked_summed_by_game_matching(
    library: UserLibrary,
    session_filter: PlayerSessionFilter,
    *,
    year: YearScope = None,
) -> PlaytimeSum:
    context = filter_query_context_for_library(library)
    return _summed(_sessions(library, year).filter(session_filter.to_q(context)))


def playtime_parts_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> PlaytimeParts:
    return PlaytimeParts(
        tracked=_zero_when_null(tracked_summed_by_game(library, year=year)),
        historical=_zero_when_null(
            historical_summed_by_game(library, within=_year_days(year))
        ),
    )


def playtime_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> Playtime:
    """Each game's playtime, zero when unplayed."""
    tracked, historical = playtime_parts_by_game(library, year=year)
    return tracked + historical


def playtime_sort_key(library: UserLibrary) -> PlaytimeSum:
    """NULL without playtime; `apply_sort` orders it last.

    A game whose only session is running sorts as unplayed.
    Telling the two apart runs each subquery twice.
    """
    return NullIf(playtime_by_game(library), ZERO, output_field=DurationField())


def playtime_matching(
    library: UserLibrary, session_filter: PlayerSessionFilter
) -> PlaytimeSum:
    """Matching sessions' sum; NULL when none match."""
    return tracked_summed_by_game_matching(library, session_filter)


def total_playtime(
    library: UserLibrary, *, year: YearScope = None
) -> PlaytimeBreakdown:
    return PlaytimeBreakdown(
        tracked=_total(_sessions(library, year)),
        historical=historical_total(library, within=_year_days(year)),
    )


def playtime_between_each(
    library: UserLibrary, windows: Sequence[DayInterval]
) -> list[PlaytimeBreakdown]:
    """One figure per window, in two queries."""
    if not windows:
        return []
    tracked = library_sessions(library).aggregate(
        **{
            f"window_{index}": Coalesce(
                Sum("effective_duration", filter=_on_days(days)), ZERO
            )
            for index, days in enumerate(windows)
        }
    )
    historical = historical_totals(library, windows)
    return [
        PlaytimeBreakdown(tracked[f"window_{index}"], historical[index])
        for index in range(len(windows))
    ]


def playtime_between(library: UserLibrary, days: DayInterval) -> PlaytimeBreakdown:
    return playtime_between_each(library, [days])[0]


def _platform_order(row: PlatformPlaytime) -> tuple[object, ...]:
    """The database's order; None sorts last."""
    return (
        -row.playtime.total,
        row.platform_name is None,
        row.platform_name or "",
        row.platform_id is None,
        row.platform_id or UUID(int=0),
    )


def _merged[Key](
    tracked: Iterable[tuple[Key, timedelta]],
    historical: Iterable[tuple[Key, timedelta]],
) -> dict[Key, PlaytimeBreakdown]:
    merged: dict[Key, PlaytimeBreakdown] = {}
    for key, playtime in tracked:
        merged[key] = PlaytimeBreakdown(playtime, timedelta(0))
    for key, playtime in historical:
        merged[key] = PlaytimeBreakdown(merged.get(key, NOTHING).tracked, playtime)
    return merged


def playtime_by_platform(
    library: UserLibrary, *, year: YearScope = None
) -> list[PlatformPlaytime]:
    tracked_rows = (
        _sessions(library, year)
        .values(PLATFORM, f"{PLATFORM}__name")
        .annotate(playtime=Sum("effective_duration"))
        .order_by()
        .values_list(PLATFORM, f"{PLATFORM}__name", "playtime")
    )
    merged = _merged(
        (
            ((platform_id, name), playtime)
            for platform_id, name, playtime in tracked_rows
        ),
        (
            ((row.platform_id, row.platform_name), row.playtime)
            for row in historical_by_platform(library, within=_year_days(year))
        ),
    )
    rows = [
        PlatformPlaytime(platform_id, name, playtime)
        for (platform_id, name), playtime in merged.items()
    ]
    return sorted(rows, key=_platform_order)


def playtime_by_month(library: UserLibrary, *, year: int) -> list[MonthPlaytime]:
    tracked_rows = (
        _sessions(library, year)
        .annotate(month=TruncMonth("effective_day"))
        .values("month")
        .annotate(playtime=Sum("effective_duration"))
        .order_by()
        .values_list("month", "playtime")
    )
    merged = _merged(
        tracked_rows,
        ((row.month, row.playtime) for row in historical_by_month(library, year=year)),
    )
    return [MonthPlaytime(month, merged[month]) for month in sorted(merged)]


def played_years(library: UserLibrary) -> list[int]:
    tracked = {day.year for day in _sessions(library).dates("effective_day", "year")}
    return sorted(tracked | set(historical_years(library)))
