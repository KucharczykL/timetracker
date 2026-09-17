from datetime import date, timedelta

from django.utils import timezone


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


def available_stats_year_range():
    return range(timezone.localdate().year, 1999, -1)
