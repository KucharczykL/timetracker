"""Every playtime figure, from the projection."""

from datetime import date, timedelta
from typing import NamedTuple
from uuid import UUID

from django.db.models import DurationField, OuterRef, Subquery, Sum, Value
from django.db.models.expressions import Combinable, Expression
from django.db.models.functions import Coalesce, TruncMonth

from games.filters import PlayerSessionFilter, filter_query_context_for_library
from games.models import Game, PlayerSessionQuerySet, UserLibrary
from games.reads.days import DayInterval
from games.reads.player_sessions import GAME, library_sessions
from games.reads.playthrough_completions import YearScope

__all__ = [
    "MonthPlaytime",
    "PlatformPlaytime",
    "UnscopedPlaytimeRead",
    "game_playtime",
    "game_playtime_between",
    "played_years",
    "playtime_between",
    "playtime_by_game",
    "playtime_by_month",
    "playtime_by_platform",
    "playtime_matching",
    "playtime_sort_key",
    "summed_by_game",
    "summed_by_game_matching",
    "total_playtime",
]

#: A per-game sum; NULL when unplayed.
type PlaytimeSum = Combinable
#: A per-game figure; never NULL.
type Playtime = Combinable

ZERO = Value(timedelta(0), output_field=DurationField())

PLATFORM = f"{GAME}__platform"


class UnscopedPlaytimeRead(RuntimeError):
    """A playtime sum executed without a library."""


class UnscopedSum(Expression):
    """Compiles for validation; refuses to execute."""

    output_field = DurationField()

    def as_sql(self, compiler, connection):
        raise UnscopedPlaytimeRead(
            "A playtime sum was executed without a library; state one."
        )


class PlatformPlaytime(NamedTuple):
    #: None is the unspecified-platform bucket.
    platform_id: UUID | None
    platform_name: str | None
    playtime: timedelta


class MonthPlaytime(NamedTuple):
    #: The first day of the month.
    month: date
    playtime: timedelta


def _sessions(library: UserLibrary, year: YearScope = None) -> PlayerSessionQuerySet:
    """Counted sessions, narrowed to a year."""
    sessions = library_sessions(library)
    if year is None:
        return sessions
    return sessions.filter(effective_day__year=year)


def _total(sessions: PlayerSessionQuerySet) -> timedelta:
    return sessions.aggregate(total=Coalesce(Sum("effective_duration"), ZERO))["total"]


def _within(
    sessions: PlayerSessionQuerySet, days: DayInterval
) -> PlayerSessionQuerySet:
    return sessions.filter(effective_day__range=(days.first, days.last))


def _summed(sessions: PlayerSessionQuerySet) -> PlaytimeSum:
    return Subquery(
        sessions.filter(**{GAME: OuterRef("pk")})
        .values(GAME)
        .annotate(total=Sum("effective_duration"))
        .values("total"),
        output_field=DurationField(),
    )


def game_playtime(library: UserLibrary, game: Game) -> timedelta:
    return _total(_sessions(library).filter(**{GAME: game}))


def game_playtime_between(
    library: UserLibrary, game: Game, days: DayInterval
) -> timedelta:
    """One game's playtime over inclusive days."""
    return _total(_within(_sessions(library).filter(**{GAME: game}), days))


def summed_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> PlaytimeSum:
    """No library compiles, then refuses to execute."""
    if library is None:
        return UnscopedSum()
    return _summed(_sessions(library, year))


def summed_by_game_matching(
    library: UserLibrary,
    session_filter: PlayerSessionFilter,
    *,
    year: YearScope = None,
) -> PlaytimeSum:
    context = filter_query_context_for_library(library)
    return _summed(_sessions(library, year).filter(session_filter.to_q(context)))


def playtime_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> Playtime:
    """Each game's playtime, zero when unplayed."""
    return Coalesce(
        summed_by_game(library, year=year),
        Value(timedelta(0)),
        output_field=DurationField(),
    )


def playtime_sort_key(library: UserLibrary) -> PlaytimeSum:
    """NULL when unplayed; `apply_sort` orders it last."""
    return summed_by_game(library)


def playtime_matching(
    library: UserLibrary, session_filter: PlayerSessionFilter | None
) -> PlaytimeSum:
    """Matching sessions' sum, NULL when none match."""
    if session_filter is None:
        return summed_by_game(library)
    return summed_by_game_matching(library, session_filter)


def total_playtime(library: UserLibrary, *, year: YearScope = None) -> timedelta:
    return _total(_sessions(library, year))


def playtime_between(library: UserLibrary, days: DayInterval) -> timedelta:
    return _total(_within(_sessions(library), days))


def playtime_by_platform(
    library: UserLibrary, *, year: YearScope = None
) -> list[PlatformPlaytime]:
    rows = (
        _sessions(library, year)
        .values(PLATFORM, f"{PLATFORM}__name")
        .annotate(playtime=Coalesce(Sum("effective_duration"), ZERO))
        .order_by("-playtime", f"{PLATFORM}__name", f"{PLATFORM}__id")
        .values_list(PLATFORM, f"{PLATFORM}__name", "playtime")
    )
    return [PlatformPlaytime(*row) for row in rows]


def playtime_by_month(library: UserLibrary, *, year: int) -> list[MonthPlaytime]:
    rows = (
        _sessions(library, year)
        .annotate(month=TruncMonth("effective_day"))
        .values("month")
        .annotate(playtime=Coalesce(Sum("effective_duration"), ZERO))
        .order_by("month")
        .values_list("month", "playtime")
    )
    return [MonthPlaytime(*row) for row in rows]


def played_years(library: UserLibrary) -> list[int]:
    return [day.year for day in _sessions(library).dates("effective_day", "year")]
