"""Seeding fixtures on the library's calendar day."""

import os
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from games.commands.calendar import SetCalendarDayZone
from games.events.dispatch import dispatch
from games.events.playersession import ZoneName
from games.models import UserLibrary
from games.reads.calendar import calendar_day_zone, calendar_today
from timetracker.settings_resolver import resolve_fallthrough_uncached

#: 25 hours apart, no DST, never coincide.
DISPLACED_ZONES: tuple[ZoneName, ZoneName] = ("Pacific/Kiritimati", "Pacific/Niue")


def library_noon(library: UserLibrary, *, days_ago: int = 0) -> datetime:
    """Midday on the library's day and zone."""
    return datetime.combine(
        calendar_today(library) - timedelta(days=days_ago),
        time(12),
        tzinfo=calendar_day_zone(library),
    )


def process_day() -> date:
    """The active zone's day, for contrast only."""
    return timezone.localdate()


def _off_the_date_of(day: date) -> ZoneName:
    return next(
        name
        for name in DISPLACED_ZONES
        if timezone.now().astimezone(ZoneInfo(name)).date() != day
    )


#: Forces the process zone; must be off the calendar's date.
FORCED_PROCESS_ZONE = "TIMETRACKER_TEST_PROCESS_ZONE"


def default_calendar_day() -> date:
    """Today on a calendar nobody has set."""
    default_calendar = ZoneInfo(
        resolve_fallthrough_uncached("DISPLAY_TIME_ZONE", skip_db=True).value
    )
    return timezone.now().astimezone(default_calendar).date()


def process_zone_off_the_calendar() -> ZoneName:
    """A process zone off the default calendar's date."""
    calendar_day = default_calendar_day()
    forced = os.environ.get(FORCED_PROCESS_ZONE)
    if forced is None:
        return _off_the_date_of(calendar_day)
    if timezone.now().astimezone(ZoneInfo(forced)).date() == calendar_day:
        raise RuntimeError(
            f"{FORCED_PROCESS_ZONE}={forced} is on the calendar's date now; "
            "Pacific/Kiritimati is off it before 10:00 UTC, Pacific/Niue after "
            "11:00 UTC, both between."
        )
    return forced


def set_calendar(library: UserLibrary, zone: ZoneName) -> ZoneName:
    """States the library's calendar zone."""
    dispatch(
        SetCalendarDayZone(day_zone=zone),
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )
    return zone


def displace_calendar(library: UserLibrary) -> ZoneName:
    """Moves the calendar off the process date."""
    return set_calendar(library, _off_the_date_of(process_day()))


def other_displaced_zone(zone: ZoneName) -> ZoneName:
    """The other zone; never the same date."""
    (other,) = (name for name in DISPLACED_ZONES if name != zone)
    return other


@pytest.fixture(autouse=True)
def _process_clock_off_the_calendar(settings):
    """A process-clock day is wrong at every hour."""
    settings.TIME_ZONE = process_zone_off_the_calendar()
