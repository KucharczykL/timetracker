from datetime import datetime, timedelta
from django.conf import settings
from zoneinfo import ZoneInfo
import re


def now() -> datetime:
    return datetime.now(ZoneInfo(settings.TIME_ZONE))


def _safe_timedelta(duration: timedelta | int | None):
    if duration == None:
        return timedelta(0)
    elif isinstance(duration, int):
        return timedelta(seconds=duration)
    elif isinstance(duration, timedelta):
        return duration


def format_duration(
    duration: timedelta | int | None, format_string: str = "%H hours"
) -> str:
    """
    Format timedelta into the specified format_string.
    Valid format variables:
    - %H hours
    - %m minutes
    - %s seconds
    - %r total seconds
    Values don't change into higher units if those units are missing
    from the formatting string. For example:
    - 61 seconds as "%s" = 61 seconds
    - 61 seconds as "%m %s" = 1 minutes 1 seconds"
    """
    minute_seconds = 60
    hour_seconds = 60 * minute_seconds
    day_seconds = 24 * hour_seconds
    duration = _safe_timedelta(duration)
    # we don't need float
    seconds_total = int(duration.total_seconds())
    # timestamps where end is before start
    if seconds_total < 0:
        seconds_total = 0
    days = hours = minutes = seconds = 0
    remainder = seconds = seconds_total
    if "%d" in format_string:
        days, remainder = divmod(seconds_total, day_seconds)
    if "%H" in format_string:
        hours, remainder = divmod(remainder, hour_seconds)
    if "%m" in format_string:
        minutes, seconds = divmod(remainder, minute_seconds)
    literals = {
        "%d": str(days),
        "%H": str(hours),
        "%m": str(minutes),
        "%s": str(seconds),
        "%r": str(seconds_total),
    }
    formatted_string = format_string
    for pattern, replacement in literals.items():
        formatted_string = re.sub(pattern, replacement, formatted_string)
    return formatted_string
