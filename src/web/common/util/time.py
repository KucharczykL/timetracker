from datetime import datetime, timedelta
from django.conf import settings
from zoneinfo import ZoneInfo
import re


def now() -> datetime:
    return datetime.now(ZoneInfo(settings.TIME_ZONE))


def format_duration(
    duration: timedelta, format_string: str = "%H hours %m minutes"
) -> str:
    """
    Format timedelta into the specified format_string.
    If duration is less than 60 seconds, skips formatting, returns "less than a minute".
    If duration is 0, skips formatting, returns 0.
    Valid format variables:
    - %H hours
    - %m minutes
    - %s seconds
    """
    seconds_in_hours = 3600
    seconds_in_minute = 60
    hours: int
    minutes: int
    seconds: int
    seconds_total: int
    remainder: int
    seconds_total = duration.total_seconds()
    if seconds_total == 0:
        return 0
    else:
        hours = int(seconds_total // seconds_in_hours)
        remainder = int(seconds_total % seconds_in_hours)
        minutes = int(remainder // seconds_in_minute)
        if hours == 0 and minutes == 0:
            return "less than a minute"
        seconds = int(minutes % seconds_in_minute)
        literals = {"%H": str(hours), "%m": str(minutes), "%s": str(seconds)}
        formatted_string = format_string
        for pattern, replacement in literals.items():
            formatted_string = re.sub(pattern, replacement, formatted_string)
        return formatted_string
