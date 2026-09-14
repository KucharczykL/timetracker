"""Both sources' playtime figures, side by side."""

from collections.abc import Callable, Iterable, Sequence
from datetime import timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from games.models import Game, UserLibrary
from games.reads.playtime import legacy, projection
from games.reads.playtime.source import (
    DayInterval,
    MonthPlaytime,
    PlatformPlaytime,
    PlaytimeSource,
)
from timetracker.settings_resolver import resolve_str_for_user

#: What a figure counts, e.g. "year 2025".
type FigureScope = str

LEGACY: PlaytimeSource = legacy
PROJECTION: PlaytimeSource = projection
ZERO = timedelta(0)
UNSPECIFIED_PLATFORM = "Unspecified"


class PlaytimeFigure(NamedTuple):
    scope: FigureScope
    legacy: timedelta
    projection: timedelta


def display_zone(library: UserLibrary) -> ZoneInfo:
    """The zone the viewer reads days in."""
    return ZoneInfo(resolve_str_for_user(library.user, "DISPLAY_TIME_ZONE"))


def playtime_figures(library: UserLibrary, zone: ZoneInfo) -> list[PlaytimeFigure]:
    """Each figure once; missing ones read zero."""
    with timezone.override(zone):
        years = sorted(
            set(LEGACY.played_years(library)) | set(PROJECTION.played_years(library))
        )
        today = timezone.localdate()
        figures = [
            _figure("all-time", lambda source: source.total_playtime(library)),
            *(_figure(f"year {year}", _total_in(library, year)) for year in years),
            *_game_figures(library),
            *(figure for year in years for figure in _platform_figures(library, year)),
            *(figure for year in years for figure in _month_figures(library, year)),
            _figure("today", _between(library, (today, today))),
            _figure(
                "last 7 days",
                _between(library, (today - timedelta(days=6), today)),
            ),
        ]
    return figures


def differing(figures: Sequence[PlaytimeFigure]) -> list[PlaytimeFigure]:
    return [figure for figure in figures if figure.legacy != figure.projection]


def _figure(
    scope: FigureScope, read: Callable[[PlaytimeSource], timedelta]
) -> PlaytimeFigure:
    return PlaytimeFigure(scope, read(LEGACY), read(PROJECTION))


def _total_in(library: UserLibrary, year: int) -> Callable[[PlaytimeSource], timedelta]:
    return lambda source: source.total_playtime(library, year)


def _between(
    library: UserLibrary, days: DayInterval
) -> Callable[[PlaytimeSource], timedelta]:
    return lambda source: source.playtime_between(library, days)


def _game_figures(library: UserLibrary) -> list[PlaytimeFigure]:
    """Games either source counts, by name."""
    games = (
        Game.objects.visible_to(library)
        .annotate(
            legacy_sum=LEGACY.summed_by_game(library),
            projection_sum=PROJECTION.summed_by_game(library),
        )
        .filter(Q(legacy_sum__isnull=False) | Q(projection_sum__isnull=False))
        .order_by("sort_name", "pk")
    )
    return [
        PlaytimeFigure(
            f"game {game.name} {game.pk}",
            game.legacy_sum or ZERO,
            game.projection_sum or ZERO,
        )
        for game in games
    ]


def _platform_figures(library: UserLibrary, year: int) -> list[PlaytimeFigure]:
    def keyed(rows: Iterable[PlatformPlaytime]) -> dict[FigureScope, timedelta]:
        return {
            f"platform {row.platform_name or UNSPECIFIED_PLATFORM} "
            f"{row.platform_id} {year}": row.playtime
            for row in rows
        }

    return _union(
        keyed(LEGACY.playtime_by_platform(library, year)),
        keyed(PROJECTION.playtime_by_platform(library, year)),
    )


def _month_figures(library: UserLibrary, year: int) -> list[PlaytimeFigure]:
    def keyed(rows: Iterable[MonthPlaytime]) -> dict[FigureScope, timedelta]:
        return {f"month {row.month:%Y-%m}": row.playtime for row in rows}

    return _union(
        keyed(LEGACY.playtime_by_month(library, year)),
        keyed(PROJECTION.playtime_by_month(library, year)),
    )


def _union(
    legacy_figures: dict[FigureScope, timedelta],
    projection_figures: dict[FigureScope, timedelta],
) -> list[PlaytimeFigure]:
    return [
        PlaytimeFigure(
            scope,
            legacy_figures.get(scope, ZERO),
            projection_figures.get(scope, ZERO),
        )
        for scope in sorted(legacy_figures.keys() | projection_figures.keys())
    ]
