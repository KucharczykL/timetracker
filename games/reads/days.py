"""Windows of calendar days."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Self

type YearScope = int | None  # a year, or None for all-time


@dataclass(frozen=True, slots=True)
class DayInterval:
    """First and last day, both inclusive."""

    first: date
    last: date

    def __post_init__(self) -> None:
        if self.last < self.first:
            raise ValueError(f"{self.last} is before {self.first}")

    @classmethod
    def year(cls, year: int) -> Self:
        return cls(date(year, 1, 1), date(year, 12, 31))

    @classmethod
    def month(cls, year: int, month: int) -> Self:
        return cls(date(year, month, 1), date(year, month, monthrange(year, month)[1]))

    @classmethod
    def single(cls, day: date) -> Self:
        return cls(day, day)

    @classmethod
    def ending(cls, day: date, *, days: int) -> Self:
        """The `days` calendar days ending on `day`."""
        if days < 1:
            raise ValueError(f"a window of {days} days is empty")
        return cls(day - timedelta(days=days - 1), day)


def year_days(year: YearScope) -> DayInterval | None:
    """The year's days; None bounds nothing."""
    return None if year is None else DayInterval.year(year)
