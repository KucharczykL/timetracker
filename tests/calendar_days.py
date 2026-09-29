"""Seeding fixtures on the library's calendar day."""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from games.commands.calendar import SetCalendarDayZone
from games.events.dispatch import dispatch
from games.events.playersession import ZoneName
from games.models import UserLibrary
from games.reads.calendar import calendar_day_zone, calendar_today
from timetracker.settings_resolver import resolve_fallthrough_uncached

#: 25 hours apart, no DST: never one date.
DISPLACED_ZONES: tuple[ZoneName, ZoneName] = ("Pacific/Kiritimati", "Pacific/Niue")


def library_noon(library: UserLibrary, *, days_ago: int = 0) -> datetime:
    """Midday on the library's day and zone."""
    return datetime.combine(
        calendar_today(library) - timedelta(days=days_ago),
        time(12),
        tzinfo=calendar_day_zone(library),
    )


def process_day() -> date:
    """The process clock's day, for contrast only."""
    return timezone.localdate()


def _off_the_date_of(day: date) -> ZoneName:
    return next(
        name
        for name in DISPLACED_ZONES
        if timezone.now().astimezone(ZoneInfo(name)).date() != day
    )


def process_zone_off_the_calendar() -> ZoneName:
    """A process zone off the default calendar's date."""
    default_calendar = ZoneInfo(
        resolve_fallthrough_uncached("DISPLAY_TIME_ZONE", skip_db=True).value
    )
    return _off_the_date_of(timezone.now().astimezone(default_calendar).date())


def displace_calendar(library: UserLibrary) -> ZoneName:
    """Moves the calendar off the process date."""
    zone = _off_the_date_of(process_day())
    dispatch(
        SetCalendarDayZone(day_zone=zone),
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )
    return zone


def other_displaced_zone(zone: ZoneName) -> ZoneName:
    """The other zone; never the same date."""
    (other,) = (name for name in DISPLACED_ZONES if name != zone)
    return other
