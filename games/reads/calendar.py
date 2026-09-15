"""The zone a library counts days in, and what a change to it moves."""

from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.db.models import DateField, F, Func, Value
from django.db.models.functions import Cast, ExtractMonth, ExtractYear

from games.models import LibraryCalendar, PlayerSessionTimingMode, UserLibrary
from games.reads.player_sessions import library_sessions
from timetracker.settings_resolver import resolve_str_for_user

#: An IANA zone name, e.g. "Europe/Prague".
type ZoneName = str


def calendar_day_zone(library: UserLibrary) -> ZoneInfo:
    """The calendar's zone, or the owner's display zone before one is stated."""
    row = LibraryCalendar.objects.filter(library=library).only("day_zone").first()
    if row is not None:
        return ZoneInfo(row.day_zone)
    return ZoneInfo(resolve_str_for_user(library.user, "DISPLAY_TIME_ZONE"))


class CalendarDelta(NamedTuple):
    """What counting days in `day_zone` moves, over the live sessions."""

    day_zone: ZoneName
    sessions: int
    day_moved: int
    month_moved: int
    year_moved: int

    def __add__(self, other: object) -> CalendarDelta:  # type: ignore[override]
        if not isinstance(other, CalendarDelta):
            return NotImplemented
        return CalendarDelta(
            self.day_zone,
            self.sessions + other.sessions,
            self.day_moved + other.day_moved,
            self.month_moved + other.month_moved,
            self.year_moved + other.year_moved,
        )


def calendar_delta(library: UserLibrary, day_zone: ZoneName) -> CalendarDelta:
    """Count the rows whose day, month or year moves under `day_zone`.

    Read before the projector rewrites the rows: it compares the day
    the new zone reads with the stored `effective_day`.
    """
    rows = library_sessions(library).filter(
        timing_mode__in=(
            PlayerSessionTimingMode.TIMED,
            PlayerSessionTimingMode.CORRECTED,
        )
    )
    #: The generated column's own expression, under the new zone.
    new_day = Cast(
        Func(Value(day_zone), F("started_at"), function="timezone"), DateField()
    )
    rows = rows.annotate(
        new_day=new_day,
        new_year=ExtractYear("new_day"),
        new_month=ExtractMonth("new_day"),
        old_year=ExtractYear("effective_day"),
        old_month=ExtractMonth("effective_day"),
    )
    return CalendarDelta(
        day_zone=day_zone,
        sessions=rows.count(),
        day_moved=rows.exclude(new_day=F("effective_day")).count(),
        month_moved=rows.exclude(
            new_year=F("old_year"), new_month=F("old_month")
        ).count(),
        year_moved=rows.exclude(new_year=F("old_year")).count(),
    )


def calendar_sentence(delta: CalendarDelta) -> str:
    """The one line a person reads after the change."""
    return (
        f"Days now counted in {delta.day_zone}: {delta.sessions:,} sessions, "
        f"{delta.day_moved:,} moved to another day, "
        f"{delta.month_moved:,} to another month, "
        f"{delta.year_moved:,} to another year."
    )
