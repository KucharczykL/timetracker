import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings


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
    Format specifiers can include width and precision options:
    - %5.2H: hours formatted with width 5 and 2 decimal places (padded with zeros)
    """
    minute_seconds = 60
    hour_seconds = 60 * minute_seconds
    day_seconds = 24 * hour_seconds
    safe_duration = _safe_timedelta(duration)
    # we don't need float
    seconds_total = int(safe_duration.total_seconds())
    # timestamps where end is before start
    if seconds_total < 0:
        seconds_total = 0
    days = hours = minutes = seconds = 0
    remainder = seconds = seconds_total
    if "%d" in format_string:
        days, remainder = divmod(seconds_total, day_seconds)
    if re.search(r"%\d*\.?\d*H", format_string):
        hours_float, remainder = divmod(remainder, hour_seconds)
        hours = float(hours_float) + remainder / hour_seconds
    if re.search(r"%\d*\.?\d*m", format_string):
        minutes, seconds = divmod(remainder, minute_seconds)
    literals = {
        "d": str(days),
        "H": str(hours),
        "m": str(minutes),
        "s": str(seconds),
        "r": str(seconds_total),
    }
    formatted_string = format_string
    for pattern, replacement in literals.items():
        # Match format specifiers with optional width and precision
        match = re.search(rf"%(\d*\.?\d*){pattern}", formatted_string)
        if match:
            format_spec = match.group(1)
            if "." in format_spec:
                # Format the number as float if precision is specified
                replacement = f"{float(replacement):{format_spec}f}"
            else:
                # Format the number as integer if no precision is specified
                replacement = f"{int(float(replacement)):>{format_spec}}"
            # Replace the format specifier with the formatted number
            formatted_string = re.sub(
                rf"%\d*\.?\d*{pattern}", replacement, formatted_string
            )
    return formatted_string
