"""Legacy playtime; days read in active zone.

No filtered sum: the session filter speaks the projection's words.
"""

from datetime import datetime, time, timedelta

from django.db.models import DateField, DurationField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.utils.timezone import make_aware

from games.models import Game, Session, SessionQuerySet, UserLibrary
from games.reads.playthrough_completions import YearScope
from games.reads.playtime.source import (
    DayInterval,
    DayPlaytime,
    MonthPlaytime,
    PlatformPlaytime,
    PlaytimeSum,
    UnscopedSum,
)

ZERO = Value(timedelta(0), output_field=DurationField())


def _sessions(library: UserLibrary, year: YearScope = None) -> SessionQuerySet:
    """Live sessions, narrowed to a year."""
    sessions = Session.objects.for_library(library)
    if year is None:
        return sessions
    return sessions.filter(timestamp_start__year=year)


def _total(sessions: SessionQuerySet) -> timedelta:
    return sessions.aggregate(total=Coalesce(Sum("duration_total"), ZERO))["total"]


def _summed(sessions: SessionQuerySet) -> PlaytimeSum:
    return Subquery(
        sessions.filter(game=OuterRef("pk"))
        .values("game")
        .annotate(total=Sum("duration_total"))
        .values("total"),
        output_field=DurationField(),
    )


def _within(sessions: SessionQuerySet, days: DayInterval) -> SessionQuerySet:
    """Midnight to midnight, in the active zone."""
    return sessions.filter(
        timestamp_start__gte=make_aware(datetime.combine(days.first, time.min)),
        timestamp_start__lt=make_aware(
            datetime.combine(days.last + timedelta(days=1), time.min)
        ),
    )


def game_playtime(library: UserLibrary, game: Game) -> timedelta:
    return _total(_sessions(library).filter(game=game))


def game_playtime_between(
    library: UserLibrary, game: Game, days: DayInterval
) -> timedelta:
    return _total(_within(_sessions(library).filter(game=game), days))


def summed_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> PlaytimeSum:
    """No library compiles, then refuses to execute.

    `for_library(None)` reads the shared catalog's sessions,
    so an unscoped sum must never reach SQL.
    """
    if library is None:
        return UnscopedSum()
    return _summed(_sessions(library, year))


def total_playtime(library: UserLibrary, *, year: YearScope = None) -> timedelta:
    return _total(_sessions(library, year))


def playtime_between(library: UserLibrary, days: DayInterval) -> timedelta:
    return _total(_within(_sessions(library), days))


def playtime_by_platform(
    library: UserLibrary, *, year: YearScope = None
) -> list[PlatformPlaytime]:
    rows = (
        _sessions(library, year)
        .values("game__platform", "game__platform__name")
        .annotate(playtime=Coalesce(Sum("duration_total"), ZERO))
        .order_by("-playtime", "game__platform__name", "game__platform__id")
        .values_list("game__platform", "game__platform__name", "playtime")
    )
    return [PlatformPlaytime(*row) for row in rows]


def playtime_by_month(library: UserLibrary, *, year: int) -> list[MonthPlaytime]:
    rows = (
        _sessions(library, year)
        .annotate(month=TruncMonth("timestamp_start", output_field=DateField()))
        .values("month")
        .annotate(playtime=Coalesce(Sum("duration_total"), ZERO))
        .order_by("month")
        .values_list("month", "playtime")
    )
    return [MonthPlaytime(*row) for row in rows]


def playtime_by_day(library: UserLibrary, *, year: int) -> list[DayPlaytime]:
    rows = (
        _sessions(library, year)
        .annotate(day=TruncDate("timestamp_start"))
        .values("day")
        .annotate(playtime=Coalesce(Sum("duration_total"), ZERO))
        .order_by("day")
        .values_list("day", "playtime")
    )
    return [DayPlaytime(*row) for row in rows]


def played_years(library: UserLibrary) -> list[int]:
    return [
        moment.year
        for moment in _sessions(library).datetimes("timestamp_start", "year")
    ]
