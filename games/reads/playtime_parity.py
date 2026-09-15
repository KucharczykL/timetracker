"""Both sources' playtime figures, side by side."""

from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Final, NamedTuple, TypedDict
from zoneinfo import ZoneInfo

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from django_stubs_ext import WithAnnotations

from games.models import Game, UserLibrary
from games.reads.player_sessions import game_session_days, library_sessions
from games.reads.playtime import legacy, projection
from games.reads.playtime.source import (
    DayInterval,
    DayPlaytime,
    MonthPlaytime,
    PlatformPlaytime,
    PlaytimeSource,
)

ZERO = timedelta(0)
UNSPECIFIED_PLATFORM = "Unspecified"

#: Members read; the coverage test holds this whole.
COMPARED_MEMBERS: Final = frozenset(
    {
        "game_playtime",
        "game_playtime_between",
        "summed_by_game",
        "total_playtime",
        "playtime_between",
        "playtime_by_platform",
        "playtime_by_month",
        "playtime_by_day",
        "played_years",
    }
)
#: Members no figure reads, and why.
UNCOMPARED_MEMBERS: Final[dict[str, str]] = {
    "summed_by_game_matching": (
        "the session filter speaks the projection's words; the legacy "
        "source has no sum it can narrow"
    ),
}


class FigureKind(StrEnum):
    ALL_TIME = "all-time"
    YEAR = "year"
    GAME = "game"
    GAME_IN_YEAR = "game in year"
    GAME_DETAIL = "game detail"
    GAME_IN_WINDOW = "game in window"
    PLATFORM = "platform"
    PLATFORM_IN_YEAR = "platform in year"
    MONTH = "month"
    DAY = "day"
    TODAY = "today"
    LAST_SEVEN_DAYS = "last 7 days"


#: A figure's identity within its kind.
type FigureKey = tuple[str, ...]


@dataclass(frozen=True, order=True)
class FigureScope:
    """Identity compares; the label only prints."""

    kind: FigureKind
    key: FigureKey
    label: str = field(compare=False)

    def __str__(self) -> str:
        return self.label


class PlaytimeFigure(NamedTuple):
    scope: FigureScope
    legacy: timedelta
    projection: timedelta


class SourcePair(NamedTuple):
    legacy: PlaytimeSource
    projection: PlaytimeSource


SOURCES: Final = SourcePair(legacy, projection)


class GameSums(TypedDict):
    legacy_sum: timedelta | None
    projection_sum: timedelta | None


#: One figure, read from either source.
type FigureRead = Callable[[PlaytimeSource], timedelta]
#: Each scope's figure from one source.
type FiguresByScope = dict[FigureScope, timedelta]


def projection_day_zones(library: UserLibrary) -> list[str]:
    """Zones the projection's rows fix days in."""
    zones = (
        library_sessions(library)
        .exclude(day_zone=None)
        .values_list("day_zone", flat=True)
        .distinct()
    )
    return sorted(zone for zone in zones if zone is not None)


def playtime_figures(
    library: UserLibrary, zone: ZoneInfo, *, sources: SourcePair = SOURCES
) -> list[PlaytimeFigure]:
    """Each figure once; missing ones read zero."""
    with _one_snapshot(), timezone.override(zone):
        years = sorted(
            set(sources.legacy.played_years(library))
            | set(sources.projection.played_years(library))
        )
        today = timezone.localdate()
        return [
            _figure(
                sources,
                FigureScope(FigureKind.ALL_TIME, (), "all-time"),
                lambda source: source.total_playtime(library),
            ),
            *(
                _figure(
                    sources,
                    FigureScope(FigureKind.YEAR, (str(year),), f"year {year}"),
                    _total_in(library, year),
                )
                for year in years
            ),
            *_game_figures(library, sources, years),
            *_platform_figures(library, sources, None),
            *(
                figure
                for year in years
                for figure in _platform_figures(library, sources, year)
            ),
            *(
                figure
                for year in years
                for figure in _month_figures(library, sources, year)
            ),
            *(
                figure
                for year in years
                for figure in _day_figures(library, sources, year)
            ),
            _figure(
                sources,
                FigureScope(FigureKind.TODAY, (), "today"),
                _between(library, DayInterval.single(today)),
            ),
            _figure(
                sources,
                FigureScope(FigureKind.LAST_SEVEN_DAYS, (), "last 7 days"),
                _between(library, DayInterval.ending(today, days=7)),
            ),
        ]


def differing(figures: Sequence[PlaytimeFigure]) -> list[PlaytimeFigure]:
    return [figure for figure in figures if figure.legacy != figure.projection]


@contextmanager
def _one_snapshot() -> Iterator[None]:
    """Both sources read one committed state."""
    if connection.in_atomic_block:
        yield
        return
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield


def _figure(
    sources: SourcePair, scope: FigureScope, read: FigureRead
) -> PlaytimeFigure:
    return PlaytimeFigure(scope, read(sources.legacy), read(sources.projection))


def _total_in(library: UserLibrary, year: int) -> FigureRead:
    return lambda source: source.total_playtime(library, year=year)


def _between(library: UserLibrary, days: DayInterval) -> FigureRead:
    return lambda source: source.playtime_between(library, days)


def _game_detail(library: UserLibrary, game: Game) -> FigureRead:
    return lambda source: source.game_playtime(library, game)


def _game_between(library: UserLibrary, game: Game, days: DayInterval) -> FigureRead:
    return lambda source: source.game_playtime_between(library, game, days)


def _game_figures(
    library: UserLibrary, sources: SourcePair, years: Sequence[int]
) -> list[PlaytimeFigure]:
    """Per game: all-time, detail, its window, each year."""
    figures: list[PlaytimeFigure] = []
    for game in _counted_games(library, sources, year=None):
        key = (str(game.pk),)
        label = f"{game.name} {game.pk}"
        figures.append(
            PlaytimeFigure(
                FigureScope(FigureKind.GAME, key, f"game {label}"),
                game.legacy_sum or ZERO,
                game.projection_sum or ZERO,
            )
        )
        figures.append(
            _figure(
                sources,
                FigureScope(FigureKind.GAME_DETAIL, key, f"game detail {label}"),
                _game_detail(library, game),
            )
        )
        #: The projection's own span: legacy time outside it
        #: shows here, and in the per-game figure above.
        span = game_session_days(library, game)
        if span is not None:
            days = DayInterval(span.first, span.last)
            figures.append(
                _figure(
                    sources,
                    FigureScope(
                        FigureKind.GAME_IN_WINDOW,
                        key,
                        f"game {label} between {days.first} and {days.last}",
                    ),
                    _game_between(library, game, days),
                )
            )
    for year in years:
        for game in _counted_games(library, sources, year=year):
            figures.append(
                PlaytimeFigure(
                    FigureScope(
                        FigureKind.GAME_IN_YEAR,
                        (str(year), str(game.pk)),
                        f"game {game.name} {game.pk} in {year}",
                    ),
                    game.legacy_sum or ZERO,
                    game.projection_sum or ZERO,
                )
            )
    return figures


def _counted_games(
    library: UserLibrary, sources: SourcePair, *, year: int | None
) -> Iterable[WithAnnotations[Game, GameSums]]:
    """Games either source counts, by sort name."""
    #: Named columns: the conversion's gate runs this read
    #: inside migration 0004, against the concrete models.
    return (
        Game.objects.visible_to(library)
        .only("id", "name", "sort_name")
        .annotate(
            legacy_sum=sources.legacy.summed_by_game(library, year=year),
            projection_sum=sources.projection.summed_by_game(library, year=year),
        )
        .filter(Q(legacy_sum__isnull=False) | Q(projection_sum__isnull=False))
        .order_by("sort_name", "pk")
    )


def _platform_figures(
    library: UserLibrary, sources: SourcePair, year: int | None
) -> list[PlaytimeFigure]:
    kind = FigureKind.PLATFORM if year is None else FigureKind.PLATFORM_IN_YEAR
    year_key = "" if year is None else str(year)
    suffix = "" if year is None else f" in {year}"

    def keyed(rows: Iterable[PlatformPlaytime]) -> FiguresByScope:
        return {
            FigureScope(
                kind,
                (year_key, str(row.platform_id or "")),
                f"platform {row.platform_name or UNSPECIFIED_PLATFORM}"
                f" {row.platform_id}{suffix}",
            ): row.playtime
            for row in rows
        }

    return _union(
        keyed(sources.legacy.playtime_by_platform(library, year=year)),
        keyed(sources.projection.playtime_by_platform(library, year=year)),
    )


def _month_figures(
    library: UserLibrary, sources: SourcePair, year: int
) -> list[PlaytimeFigure]:
    def keyed(rows: Iterable[MonthPlaytime]) -> FiguresByScope:
        return {
            FigureScope(
                FigureKind.MONTH, (f"{row.month:%Y-%m}",), f"month {row.month:%Y-%m}"
            ): row.playtime
            for row in rows
        }

    return _union(
        keyed(sources.legacy.playtime_by_month(library, year=year)),
        keyed(sources.projection.playtime_by_month(library, year=year)),
    )


def _day_figures(
    library: UserLibrary, sources: SourcePair, year: int
) -> list[PlaytimeFigure]:
    def keyed(rows: Iterable[DayPlaytime]) -> FiguresByScope:
        return {
            FigureScope(
                FigureKind.DAY, (row.day.isoformat(),), f"day {row.day.isoformat()}"
            ): row.playtime
            for row in rows
        }

    return _union(
        keyed(sources.legacy.playtime_by_day(library, year=year)),
        keyed(sources.projection.playtime_by_day(library, year=year)),
    )


def _union(
    legacy_figures: FiguresByScope, projection_figures: FiguresByScope
) -> list[PlaytimeFigure]:
    return [
        PlaytimeFigure(
            scope,
            legacy_figures.get(scope, ZERO),
            projection_figures.get(scope, ZERO),
        )
        for scope in sorted(legacy_figures.keys() | projection_figures.keys())
    ]
