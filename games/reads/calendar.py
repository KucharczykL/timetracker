"""The zone a library counts days in, and what a change to it moves."""

import logging
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.db.models import Count, DateField, F, Func, Q, Value
from django.db.models.functions import Cast, ExtractMonth, ExtractYear

from common.date_time_presentation import zone_or_none
from games.events.playersession import ZoneName
from games.models import LibraryCalendar, PlayerSessionTimingMode, UserLibrary
from games.reads.player_sessions import library_sessions
from timetracker.settings_resolver import resolve_str_for_user

logger = logging.getLogger("games")


def stated_calendar_zone(library: UserLibrary) -> ZoneName | None:
    """The name the calendar row states, readable or not; None without a row."""
    row = LibraryCalendar.objects.filter(library=library).only("day_zone").first()
    return None if row is None else row.day_zone


def calendar_day_zone(library: UserLibrary) -> ZoneInfo:
    """The calendar's zone, or the owner's display zone before one is stated.

    A stored name tzdata no longer reads falls back too, loudly: the
    setting change restates it, and nothing else may fail on it.
    """
    stated = stated_calendar_zone(library)
    if stated is not None:
        zone = zone_or_none(stated)
        if zone is not None:
            return zone
        logger.error(
            "Library %s's calendar names %r, a zone this installation cannot "
            "read; reading the owner's display zone until it is set again.",
            library.pk,
            stated,
        )
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
        if other.day_zone != self.day_zone:
            raise ValueError(
                f"a delta in {self.day_zone} cannot add one in {other.day_zone}"
            )
        return CalendarDelta(
            self.day_zone,
            self.sessions + other.sessions,
            self.day_moved + other.day_moved,
            self.month_moved + other.month_moved,
            self.year_moved + other.year_moved,
        )


def calendar_delta(library: UserLibrary, day_zone: ZoneName) -> CalendarDelta:
    """Count the rows whose day, month or year moves under `day_zone`.

    Read before the projector rewrites `day_zone` and `effective_day`
    regenerates. One pass: the caller holds the stream head meanwhile.
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
    same_year = Q(new_year=F("old_year"))
    same_month = same_year & Q(new_month=F("old_month"))
    counted = rows.annotate(
        new_day=new_day,
        new_year=ExtractYear("new_day"),
        new_month=ExtractMonth("new_day"),
        old_year=ExtractYear("effective_day"),
        old_month=ExtractMonth("effective_day"),
    ).aggregate(
        sessions=Count("id"),
        day_moved=Count("id", filter=~Q(new_day=F("effective_day"))),
        month_moved=Count("id", filter=~same_month),
        year_moved=Count("id", filter=~same_year),
    )
    return CalendarDelta(day_zone=day_zone, **counted)


def calendar_sentence(delta: CalendarDelta) -> str:
    """The one line a person reads after the change."""
    return (
        f"Days now counted in {delta.day_zone}: {delta.sessions:,} sessions, "
        f"{delta.day_moved:,} moved to another day, "
        f"{delta.month_moved:,} to another month, "
        f"{delta.year_moved:,} to another year."
    )
