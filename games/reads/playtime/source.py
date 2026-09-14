"""The figures a playtime source answers."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple, Protocol, Self
from uuid import UUID

from django.db.models import DurationField
from django.db.models.expressions import Combinable, Expression

from games.filters import SessionFilter
from games.models import Game, UserLibrary
from games.reads.playthrough_completions import YearScope

#: A per-game sum; NULL when unplayed.
type PlaytimeSum = Combinable
#: A per-game figure; never NULL.
type Playtime = Combinable


class UnscopedPlaytimeRead(RuntimeError):
    """A playtime sum executed without a library."""


class UnscopedSum(Expression):
    """Compiles for validation; refuses to execute."""

    output_field = DurationField()

    def as_sql(self, compiler, connection):
        raise UnscopedPlaytimeRead(
            "A playtime sum was executed without a library; state one."
        )


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


class PlatformPlaytime(NamedTuple):
    #: None is the unspecified-platform bucket.
    platform_id: UUID | None
    platform_name: str | None
    playtime: timedelta


class MonthPlaytime(NamedTuple):
    #: The first day of the month.
    month: date
    playtime: timedelta


class DayPlaytime(NamedTuple):
    day: date
    playtime: timedelta


class PlaytimeSource(Protocol):
    """Per-game sums NULL when unplayed; totals never."""

    def game_playtime(self, library: UserLibrary, game: Game) -> timedelta: ...

    def summed_by_game(
        self, library: UserLibrary | None, *, year: YearScope = None
    ) -> PlaytimeSum: ...

    def total_playtime(
        self, library: UserLibrary, *, year: YearScope = None
    ) -> timedelta: ...

    def playtime_between(
        self, library: UserLibrary, days: DayInterval
    ) -> timedelta: ...

    def playtime_by_platform(
        self, library: UserLibrary, *, year: YearScope = None
    ) -> list[PlatformPlaytime]: ...

    def playtime_by_month(
        self, library: UserLibrary, *, year: int
    ) -> list[MonthPlaytime]: ...

    def playtime_by_day(
        self, library: UserLibrary, *, year: int
    ) -> list[DayPlaytime]: ...

    def played_years(self, library: UserLibrary) -> list[int]: ...


class FilteredPlaytimeSource[FilterT](Protocol):
    """Sums narrowed by a session filter."""

    def summed_by_game_matching(
        self,
        library: UserLibrary,
        session_filter: FilterT,
        *,
        year: YearScope = None,
    ) -> PlaytimeSum: ...


class FullPlaytimeSource(
    PlaytimeSource, FilteredPlaytimeSource[SessionFilter], Protocol
):
    """A source every caller can be handed."""
