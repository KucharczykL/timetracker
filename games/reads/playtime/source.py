"""The figures a playtime source answers."""

from datetime import date, timedelta
from typing import NamedTuple, Protocol
from uuid import UUID

from django.db.models import DurationField
from django.db.models.expressions import Combinable, Expression

from games.filters import SessionFilter
from games.models import Game, UserLibrary
from games.reads.playthrough_completions import YearScope


class UnscopedPlaytimeRead(RuntimeError):
    """A playtime sum executed without a library."""


class UnscopedSum(Expression):
    """Compiles for validation; refuses to execute."""

    output_field = DurationField()

    def as_sql(self, compiler, connection):
        raise UnscopedPlaytimeRead(
            "A playtime sum was executed without a library; state one."
        )


#: First and last day, both inclusive.
type DayInterval = tuple[date, date]


class PlatformPlaytime(NamedTuple):
    #: None is the unspecified-platform bucket.
    platform_id: UUID | None
    platform_name: str | None
    playtime: timedelta


class MonthPlaytime(NamedTuple):
    #: The first day of the month.
    month: date
    playtime: timedelta


class PlaytimeSource(Protocol):
    """Sums are NULL when unplayed; figures never."""

    def game_playtime(self, library: UserLibrary, game: Game) -> timedelta: ...

    def summed_by_game(
        self, library: UserLibrary | None, *, year: YearScope = None
    ) -> Combinable: ...

    def total_playtime(
        self, library: UserLibrary, year: YearScope = None
    ) -> timedelta: ...

    def playtime_between(
        self, library: UserLibrary, days: DayInterval
    ) -> timedelta: ...

    def playtime_by_platform(
        self, library: UserLibrary, year: YearScope = None
    ) -> list[PlatformPlaytime]: ...

    def playtime_by_month(
        self, library: UserLibrary, year: int
    ) -> list[MonthPlaytime]: ...

    def played_years(self, library: UserLibrary) -> list[int]: ...


class FilteredPlaytimeSource(Protocol):
    """Sums narrowed by a legacy session filter."""

    def summed_by_game_matching(
        self,
        library: UserLibrary,
        session_filter: SessionFilter,
        *,
        year: YearScope = None,
    ) -> Combinable: ...


class FullPlaytimeSource(PlaytimeSource, FilteredPlaytimeSource, Protocol):
    """A source every caller can be handed."""
