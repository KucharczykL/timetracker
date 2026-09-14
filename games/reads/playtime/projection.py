"""Playtime read from the PlayerSession projection.

A year, a month and a day are read off `effective_day`, frozen
in the row's own `day_zone`; the active zone moves nothing.

No `summed_by_game_matching`: a session filter names the legacy
table's fields.
"""

from datetime import timedelta

from django.db.models import DurationField, OuterRef, Subquery, Sum, Value
from django.db.models.expressions import Combinable
from django.db.models.functions import Coalesce, TruncMonth

from games.models import Game, PlayerSession, PlayerSessionQuerySet, UserLibrary
from games.reads.player_sessions import library_sessions
from games.reads.playthrough_completions import YearScope
from games.reads.playtime.source import DayInterval, MonthPlaytime, PlatformPlaytime

ZERO = Value(timedelta(0), output_field=DurationField())

#: A session reaches its game only through its run.
GAME = "playthrough__player_game__game"
PLATFORM = f"{GAME}__platform"


def _sessions(
    library: UserLibrary | None, year: YearScope = None
) -> PlayerSessionQuerySet:
    """The library's counted sessions, in the year when one is named."""
    if library is None:
        return PlayerSession.objects.none()
    sessions = library_sessions(library)
    if year is None:
        return sessions
    return sessions.filter(effective_day__year=year)


def _total(sessions: PlayerSessionQuerySet) -> timedelta:
    return sessions.aggregate(total=Coalesce(Sum("effective_duration"), ZERO))["total"]


def game_playtime(library: UserLibrary, game: Game) -> timedelta:
    return _total(_sessions(library).filter(**{GAME: game}))


def summed_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> Combinable:
    return Subquery(
        _sessions(library, year)
        .filter(**{GAME: OuterRef("pk")})
        .values(GAME)
        .annotate(total=Sum("effective_duration"))
        .values("total"),
        output_field=DurationField(),
    )


def total_playtime(library: UserLibrary, year: YearScope = None) -> timedelta:
    return _total(_sessions(library, year))


def playtime_between(library: UserLibrary, days: DayInterval) -> timedelta:
    return _total(_sessions(library).filter(effective_day__range=days))


def playtime_by_platform(
    library: UserLibrary, year: YearScope = None
) -> list[PlatformPlaytime]:
    rows = (
        _sessions(library, year)
        .values(PLATFORM, f"{PLATFORM}__name")
        .annotate(playtime=Coalesce(Sum("effective_duration"), ZERO))
        .order_by("-playtime", f"{PLATFORM}__name", f"{PLATFORM}__id")
        .values_list(PLATFORM, f"{PLATFORM}__name", "playtime")
    )
    return [PlatformPlaytime(*row) for row in rows]


def playtime_by_month(library: UserLibrary, year: int) -> list[MonthPlaytime]:
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
