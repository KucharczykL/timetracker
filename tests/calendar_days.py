"""Seeding a fixture on the day the code under test counts in.

A test that wants "today" must ask the same clock the reader asks, which
since #1221 is the library's calendar and not the process. The two agree
for most of the day and disagree by one for the hours their zones do, so
a fixture seeded off `timezone.localdate()` passes until CI happens to
run in that window. `test_calendar_clock_guard.py` refuses the process
clock here for that reason; this is what to reach for instead.
"""

from datetime import datetime, time, timedelta

from games.models import UserLibrary
from games.reads.calendar import calendar_day_zone, calendar_today


def library_day_zone(library: UserLibrary) -> str:
    """The zone key a seeded session states, as `session_row(day_zone=...)`.

    A session's day is `effective_day`, which the database computes from
    the row's *own* `day_zone` -- not the library's calendar. Every
    day-grained reader filters on that column against calendar days, so a
    row stating another zone lands on the calendar's day only by luck of
    the offsets. Stating this one makes the two agree by construction.
    """
    return calendar_day_zone(library).key


def library_noon(library: UserLibrary, *, days_ago: int = 0) -> datetime:
    """Midday on the library's own day, in the library's own zone.

    Midday rather than any instant of that day: no zone the calendar can
    name moves it off the day `calendar_today()` answers, so a row seeded
    here is counted by the day a reader asks for. Midnight would sit an
    hour from the boundary the whole point is to avoid.

    Pair it with `library_day_zone()` when the row is a session, so the
    day the database computes is the day this instant names.
    """
    return datetime.combine(
        calendar_today(library) - timedelta(days=days_ago),
        time(12),
        tzinfo=calendar_day_zone(library),
    )
