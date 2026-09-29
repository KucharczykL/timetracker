"""Seeding a fixture on the day the code under test counts in.

A test that wants "today" asks the clock the reader asks: the library's
calendar, not the process. The two agree except for the hours their zones
sit on different dates, so a fixture seeded off the process clock passes
until CI runs in that window. `test_calendar_clock_guard.py` refuses the
process clock in tests; this is what to reach for instead.
"""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.utils import timezone

from games.commands.calendar import SetCalendarDayZone
from games.events.dispatch import dispatch
from games.events.playersession import ZoneName
from games.models import UserLibrary
from games.reads.calendar import calendar_day_zone, calendar_today

#: 25 hours apart, so at any instant one is on another date than any zone.
DISPLACED_ZONES: tuple[ZoneName, ZoneName] = ("Pacific/Kiritimati", "Pacific/Niue")


def library_noon(library: UserLibrary, *, days_ago: int = 0) -> datetime:
    """Midday on the library's day, in the library's zone.

    As far from either day boundary as an instant gets. `session_row`
    and its siblings stamp the calendar's zone by default, so a row
    seeded here lands on the day `calendar_today()` answers.
    """
    return datetime.combine(
        calendar_today(library) - timedelta(days=days_ago),
        time(12),
        tzinfo=calendar_day_zone(library),
    )


def process_day() -> date:
    """The process clock's day, which no reader asks.

    Only for proving a calendar disagrees with it.
    """
    return timezone.localdate()


def displace_calendar(user: User, library: UserLibrary) -> ZoneName:
    """Set the library's calendar to a zone on another date than the process.

    A fixture on the process clock then fails at every hour, not only
    inside the window the default zones disagree in.
    """
    zone = next(
        name
        for name in DISPLACED_ZONES
        if timezone.now().astimezone(ZoneInfo(name)).date() != process_day()
    )
    dispatch(
        SetCalendarDayZone(day_zone=zone),
        actor=user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )
    return zone


def other_displaced_zone(zone: ZoneName) -> ZoneName:
    """The displaced zone that is not `zone`: never on the same date as it."""
    (other,) = (name for name in DISPLACED_ZONES if name != zone)
    return other
