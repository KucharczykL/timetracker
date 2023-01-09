from datetime import datetime, timedelta
from django.conf import settings
from zoneinfo import ZoneInfo
import re


def now() -> datetime:
    return datetime.now(ZoneInfo(settings.TIME_ZONE))


def format_duration(
    duration: timedelta | None, format_string: str = "%H hours %m minutes"
) -> str:
    """
    Format timedelta into the specified format_string.
    Valid format variables:
    - %H hours
    - %m minutes
    - %s seconds
    - %r total seconds
    """
    minute_seconds = 60
    hour_seconds = 60 * minute_seconds
    day_seconds = 24 * hour_seconds
    if not isinstance(duration, timedelta):
        if duration == None:
            duration = timedelta(seconds=0)
        else:
            duration = timedelta(seconds=duration)
    seconds_total = int(duration.total_seconds())
    # timestamps where end is before start
    if seconds_total < 0:
        seconds_total = 0
    days, remainder = divmod(seconds_total, day_seconds)
    hours, remainder = divmod(remainder, hour_seconds)
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
