from datetime import date, timedelta


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


def available_stats_year_range(today: date) -> range:
    """The years the stats picker offers.

    The day is stated, because the year a library is in is
    its calendar's answer and this module knows no library.
    """
    return range(today.year, 1999, -1)
