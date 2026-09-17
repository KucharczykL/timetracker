"""Windows of calendar days."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Self


@dataclass(frozen=True, slots=True)
class DayInterval:
    """First and last day, both inclusive."""

    first: date
    last: date

    def __post_init__(self) -> None:
        if self.last < self.first:
            raise ValueError(f"{self.last} is before {self.first}")

    @classmethod
    def single(cls, day: date) -> Self:
        return cls(day, day)

    @classmethod
    def ending(cls, day: date, *, days: int) -> Self:
        """The `days` calendar days ending on `day`."""
        return cls(day - timedelta(days=days - 1), day)
