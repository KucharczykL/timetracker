from datetime import date, timedelta

from django.utils import timezone

from common.utils import generate_split_ranges


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
            {
                datelist[0] + timedelta(x)
                for x in range((datelist[-1] - datelist[0]).days)
            }
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


def available_stats_year_range():
    return range(timezone.localdate().year, 1999, -1)
