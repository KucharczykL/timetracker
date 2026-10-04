"""Records a library holds and shows."""

from django.db.models import F, Prefetch, Q

from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeQuerySet,
    HistoricalPlaytimeRun,
    UserLibrary,
)
from games.reads.days import DayInterval, YearScope, year_days
from games.reads.prerelease_play import shown_play
from games.reads.unscoped import require_library

#: Newest first; an unknown `when` last; then newest recorded.
RECORD_ORDER = (F("when_lower").desc(nulls_last=True), "-created_at", "id")


def library_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """Every live record this library holds.

    A copy of this breaks quietly. The record's and its tracked
    game's libraries are both stated: either can name another
    library's row. `alive()` alone keeps the records of a removed
    catalog game.
    """
    library = require_library(library)
    return HistoricalPlaytime.objects.filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
        player_game__removed_at__isnull=True,
        player_game__game__removed_at__isnull=True,
    )


def shown_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """The records figures and lists hold."""
    return library_records(library).filter(shown_play(library))


def _with_row_path(
    library: UserLibrary, records: HistoricalPlaytimeQuerySet
) -> HistoricalPlaytimeQuerySet:
    """Game, device, Release, and this library's runs."""
    return records.select_related(
        "player_game__game__platform",
        "device",
        "release__edition",
        "release__platform",
    ).prefetch_related(
        Prefetch(
            "runs",
            queryset=HistoricalPlaytimeRun.objects.filter(library=library).order_by(
                "playthrough_id"
            ),
        )
    )


def readable_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """The row path over every row."""
    return _with_row_path(library, library_records(library))


def listed_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """The row path over shown rows."""
    return _with_row_path(library, shown_records(library))


def contains(days: DayInterval) -> Q:
    """The whole interval lies inside `days`."""
    return Q(when_lower__gte=days.first, when_upper__lte=days.last)


def contained_in(
    records: HistoricalPlaytimeQuerySet, days: DayInterval
) -> HistoricalPlaytimeQuerySet:
    return records.filter(contains(days))


def records_within(
    library: UserLibrary, within: DayInterval | None
) -> HistoricalPlaytimeQuerySet:
    """Shown records inside `within`; None: all."""
    records = shown_records(library)
    return records if within is None else contained_in(records, within)


def records_in_scope(
    library: UserLibrary, year: YearScope
) -> HistoricalPlaytimeQuerySet:
    """Shown records in the year; None: all-time."""
    return records_within(library, year_days(year))


def one_day_records(
    library: UserLibrary, year: YearScope
) -> HistoricalPlaytimeQuerySet:
    """Records in scope that name a single day."""
    return records_in_scope(library, year).filter(when_lower=F("when_upper"))
