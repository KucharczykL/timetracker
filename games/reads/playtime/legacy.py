"""Playtime read from the legacy Session table.

A year, a month and a day are read in the active zone.
"""

from datetime import datetime, time, timedelta

from django.db.models import DateField, DurationField, OuterRef, Subquery, Sum, Value
from django.db.models.expressions import Combinable
from django.db.models.functions import Coalesce, TruncMonth
from django.utils.timezone import make_aware

from games.filters import SessionFilter, filter_query_context_for_library
from games.models import Game, Session, SessionQuerySet, UserLibrary
from games.reads.playthrough_completions import YearScope
from games.reads.playtime.source import DayInterval, MonthPlaytime, PlatformPlaytime

ZERO = Value(timedelta(0), output_field=DurationField())


def _sessions(library: UserLibrary | None, year: YearScope = None) -> SessionQuerySet:
    """The library's live sessions, in the year when one is named.

    No library is no session: `for_library(None)` would read the
    shared catalog's.
    """
    if library is None:
        return Session.objects.none()
    sessions = Session.objects.for_library(library)
    if year is None:
        return sessions
    return sessions.filter(timestamp_start__year=year)


def _total(sessions: SessionQuerySet) -> timedelta:
    return sessions.aggregate(total=Coalesce(Sum("duration_total"), ZERO))["total"]


def _summed(sessions: SessionQuerySet) -> Combinable:
    return Subquery(
        sessions.filter(game=OuterRef("pk"))
        .values("game")
        .annotate(total=Sum("duration_total"))
        .values("total"),
        output_field=DurationField(),
    )


def game_playtime(library: UserLibrary, game: Game) -> timedelta:
    return _total(_sessions(library).filter(game=game))


def summed_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> Combinable:
    return _summed(_sessions(library, year))


def summed_by_game_matching(
    library: UserLibrary, session_filter: SessionFilter, *, year: YearScope = None
) -> Combinable:
    context = filter_query_context_for_library(library)
    return _summed(_sessions(library, year).filter(session_filter.to_q(context)))


def total_playtime(library: UserLibrary, year: YearScope = None) -> timedelta:
    return _total(_sessions(library, year))


def playtime_between(library: UserLibrary, days: DayInterval) -> timedelta:
    """Midnight to midnight, so the range reads the start index."""
    first, last = days
    return _total(
        _sessions(library).filter(
            timestamp_start__gte=make_aware(datetime.combine(first, time.min)),
            timestamp_start__lt=make_aware(
                datetime.combine(last + timedelta(days=1), time.min)
            ),
        )
    )


def playtime_by_platform(
    library: UserLibrary, year: YearScope = None
) -> list[PlatformPlaytime]:
    rows = (
        _sessions(library, year)
        .values("game__platform", "game__platform__name")
        .annotate(playtime=Coalesce(Sum("duration_total"), ZERO))
        .order_by("-playtime", "game__platform__name")
        .values_list("game__platform", "game__platform__name", "playtime")
    )
    return [PlatformPlaytime(*row) for row in rows]


def playtime_by_month(library: UserLibrary, year: int) -> list[MonthPlaytime]:
    rows = (
        _sessions(library, year)
        .annotate(month=TruncMonth("timestamp_start", output_field=DateField()))
        .values("month")
        .annotate(playtime=Coalesce(Sum("duration_total"), ZERO))
        .order_by("month")
        .values_list("month", "playtime")
    )
    return [MonthPlaytime(*row) for row in rows]


def played_years(library: UserLibrary) -> list[int]:
    return [
        moment.year
        for moment in _sessions(library).datetimes("timestamp_start", "year")
    ]
