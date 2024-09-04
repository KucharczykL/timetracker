import re
from datetime import date, datetime, timedelta

from django.utils import timezone

from common.utils import generate_split_ranges

dateformat: str = "%d/%m/%Y"
datetimeformat: str = "%d/%m/%Y %H:%M"
timeformat: str = "%H:%M"
durationformat: str = "%2.1H hours"
durationformat_manual: str = "%H hours"


def _safe_timedelta(duration: timedelta | int | None):
    if duration == None:
        return timedelta(0)
    elif isinstance(duration, int):
        return timedelta(seconds=duration)
    elif isinstance(duration, timedelta):
        return duration


def format_duration(
    duration: timedelta | int | float | None, format_string: str = "%H hours"
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
    days = hours = hours_float = minutes = seconds = 0
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
        "H": str(hours) if "m" not in format_string else str(hours_float),
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


def local_strftime(datetime: datetime, format: str = datetimeformat) -> str:
    return timezone.localtime(datetime).strftime(format)


def daterange(start: date, end: date, end_inclusive: bool = False) -> list[date]:
    time_between: timedelta = end - start
    if (days_between := time_between.days) < 1:
        raise ValueError("start and end have to be at least 1 day apart.")
    if end_inclusive:
        print(f"{end_inclusive=}")
        print(f"{days_between=}")
        days_between += 1
    print(f"{days_between=}")
    return [start + timedelta(x) for x in range(days_between)]


def streak(datelist: list[date]) -> dict[str, int | tuple[date, date]]:
    if len(datelist) == 1:
        return {"days": 1, "dates": (datelist[0], datelist[0])}
    else:
        print(f"Processing {len(datelist)} dates.")
        missing = sorted(
            set(
                datelist[0] + timedelta(x)
                for x in range((datelist[-1] - datelist[0]).days)
            )
            - set(datelist)
        )
        print(f"{len(missing)} days missing.")
        datelist_with_missing = sorted(datelist + missing)
        ranges = list(generate_split_ranges(datelist_with_missing, missing))
        print(f"{len(ranges)} ranges calculated.")
        longest_consecutive_days = timedelta(0)
        longest_range: tuple[date, date] = (date(1970, 1, 1), date(1970, 1, 1))
        for start, end in ranges:
            if (current_streak := end - start) > longest_consecutive_days:
                longest_consecutive_days = current_streak
                longest_range = (start, end)
        return {"days": longest_consecutive_days.days + 1, "dates": longest_range}


def streak_bruteforce(datelist: list[date]) -> dict[str, int | tuple[date, date]]:
    if (datelist_length := len(datelist)) == 0:
        raise ValueError("Number of dates in the list is 0.")
    datelist.sort()
    current_streak = 1
    current_start = datelist[0]
    current_end = datelist[0]
    current_date = datelist[0]
    highest_streak = 1
    highest_streak_daterange = (current_start, current_end)

    def update_highest_streak():
        nonlocal highest_streak, highest_streak_daterange
        if current_streak > highest_streak:
            highest_streak = current_streak
            highest_streak_daterange = (current_start, current_end)

    def reset_streak():
        nonlocal current_start, current_end, current_streak
        current_start = current_end = current_date
        current_streak = 1

    def increment_streak():
        nonlocal current_end, current_streak
        current_end = current_date
        current_streak += 1

    for i, datelist_item in enumerate(datelist, start=1):
        current_date = datelist_item
        if current_date == current_start or current_date == current_end:
            continue
        if current_date - timedelta(1) != current_end and i != datelist_length:
            update_highest_streak()
            reset_streak()
        elif current_date - timedelta(1) == current_end and i == datelist_length:
            increment_streak()
            update_highest_streak()
        else:
            increment_streak()
    return {"days": highest_streak, "dates": highest_streak_daterange}
