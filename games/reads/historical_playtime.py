"""Historical playtime sums, counted by containment."""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import NamedTuple
from uuid import UUID

from django.db.models import DurationField, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, ExtractYear, TruncMonth

from games.models import (
    Game,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeQuerySet,
    UserLibrary,
)
from games.reads.days import DayInterval
from games.reads.historical_playtime_records import game_records, library_records
from games.reads.sums import ZERO, PlaytimeSum, UnscopedSum

__all__ = [
    "MonthHistorical",
    "PlatformHistorical",
    "contained_in",
    "game_historical_playtime",
    "historical_by_month",
    "historical_by_platform",
    "historical_summed_by_game",
    "historical_total",
    "historical_totals",
    "historical_years",
]

#: Records reach games through the tracked game.
GAME = "player_game__game"
PLATFORM = f"{GAME}__platform"


class PlatformHistorical(NamedTuple):
    #: None is the unspecified-platform bucket.
    platform_id: UUID | None
    platform_name: str | None
    playtime: timedelta


class MonthHistorical(NamedTuple):
    #: The first day of the month.
    month: date
    playtime: timedelta


def _contains(days: DayInterval) -> Q:
    return Q(when_lower__gte=days.first, when_upper__lte=days.last)


def contained_in(
    records: HistoricalPlaytimeQuerySet, days: DayInterval
) -> HistoricalPlaytimeQuerySet:
    return records.filter(_contains(days))


def _records(
    library: UserLibrary, within: DayInterval | None
) -> HistoricalPlaytimeQuerySet:
    records = library_records(library)
    return records if within is None else contained_in(records, within)


def _total(records: HistoricalPlaytimeQuerySet) -> timedelta:
    return records.aggregate(total=Coalesce(Sum("duration"), ZERO))["total"]


def historical_total(
    library: UserLibrary, *, within: DayInterval | None = None
) -> timedelta:
    return _total(_records(library, within))


def historical_totals(
    library: UserLibrary, windows: Sequence[DayInterval]
) -> list[timedelta]:
    """One sum per window, in one query."""
    if not windows:
        return []
    sums = library_records(library).aggregate(
        **{
            f"window_{index}": Coalesce(Sum("duration", filter=_contains(days)), ZERO)
            for index, days in enumerate(windows)
        }
    )
    return [sums[f"window_{index}"] for index in range(len(windows))]


def historical_summed_by_game(
    library: UserLibrary | None, *, within: DayInterval | None = None
) -> PlaytimeSum:
    """NULL when no record is in scope."""
    if library is None:
        return UnscopedSum()
    return Subquery(
        _records(library, within)
        .filter(**{GAME: OuterRef("pk")})
        .values(GAME)
        .annotate(total=Sum("duration"))
        .values("total"),
        output_field=DurationField(),
    )


def historical_by_platform(
    library: UserLibrary, *, within: DayInterval | None = None
) -> list[PlatformHistorical]:
    rows = (
        _records(library, within)
        .values(PLATFORM, f"{PLATFORM}__name")
        .annotate(playtime=Sum("duration"))
        .order_by(PLATFORM)
        .values_list(PLATFORM, f"{PLATFORM}__name", "playtime")
    )
    return [PlatformHistorical(*row) for row in rows]


def historical_by_month(library: UserLibrary, *, year: int) -> list[MonthHistorical]:
    """Counts a record only within one month."""
    rows = (
        contained_in(library_records(library), DayInterval.year(year))
        .filter(when_lower__month=F("when_upper__month"))
        .annotate(month=TruncMonth("when_lower"))
        .values("month")
        .annotate(playtime=Sum("duration"))
        .order_by("month")
        .values_list("month", "playtime")
    )
    return [MonthHistorical(*row) for row in rows]


def historical_years(library: UserLibrary) -> list[int]:
    """Years that wholly contain a record's `when`."""
    return list(
        library_records(library)
        .filter(when_lower__year=F("when_upper__year"))
        .annotate(year=ExtractYear("when_lower"))
        .values_list("year", flat=True)
        .distinct()
        .order_by("year")
    )


def game_historical_playtime(
    library: UserLibrary,
    game: Game,
    provenance: HistoricalPlaytimeProvenance | None = None,
    *,
    within: DayInterval | None = None,
) -> timedelta:
    records = game_records(library, game)
    if within is not None:
        records = contained_in(records, within)
    if provenance is not None:
        records = records.filter(provenance=provenance)
    return _total(records)
