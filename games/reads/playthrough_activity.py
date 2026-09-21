"""Whether an unfinished run is being played."""

from datetime import date, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.db import models
from django.db.models import Case, F, OuterRef, Subquery, Value, When
from django.db.models.expressions import Combinable, Expression
from django.db.models.functions import Coalesce
from django.utils import timezone as django_timezone

from games.models import PlayerSession, UserLibrary
from games.reads.calendar import calendar_day_zone
from timetracker.settings_resolver import resolve_for_user


class RunActivity(models.TextChoices):
    """The three words a clock counts."""

    PLAYING = "playing", "Playing"
    DORMANT = "dormant", "Dormant"
    NEVER_PLAYED = "never_played", "Never played"


class ActivityClock(NamedTuple):
    """How long is too long, today.

    `today` is the day the library's calendar is on, and it
    is kept rather than discarded so a renderer reading a
    row's day can subtract the same one the word beside it
    was counted against. A second today, derived from a
    presentation zone or from `localdate()`, is the
    disagreement #1047 named and #1217 found again.
    """

    threshold_days: int
    zone: ZoneInfo
    today: date
    boundary_day: date


def activity_clock(library: UserLibrary) -> ActivityClock:
    """The threshold and zone this library reads."""
    user = library.user
    threshold_days = resolve_for_user(user, "DORMANT_AFTER_DAYS")
    #: A float would shift the boundary day.
    if not isinstance(threshold_days, int) or isinstance(threshold_days, bool):
        raise TypeError(
            f"DORMANT_AFTER_DAYS resolved to {threshold_days!r}, not a day count"
        )
    return _clock(threshold_days, calendar_day_zone(library))


class UnscopedActivityRead(RuntimeError):
    """A condition alias executed without a clock."""


class UnscopedActivityAlias(Expression):
    """Resolves for validation; refuses to compile."""

    def as_sql(self, compiler, connection):
        raise UnscopedActivityRead(
            "An activity read was executed without a clock; state one."
        )


def _clock(threshold_days: int, zone: ZoneInfo) -> ActivityClock:
    today = django_timezone.now().astimezone(zone).date()
    return ActivityClock(
        threshold_days=threshold_days,
        zone=zone,
        today=today,
        boundary_day=today - timedelta(days=threshold_days),
    )


def activity_day_expression() -> Combinable:
    """The day the word reads.

    The run's own sessions, not the game's: a sibling run
    or the imported-history bucket moves no word. The day
    is the row's `effective_day`, already counted in the
    library's calendar, so the clock's zone plays no part
    here. The library is stated beside the run so a row
    another library holds at it, the drift
    `audit_library_ownership` reports, reads nothing.
    """
    latest_session_day = (
        PlayerSession.objects.filter(
            playthrough=OuterRef("pk"),
            library=OuterRef("library"),
            removed_at__isnull=True,
        )
        .order_by("-effective_day")
        .values("effective_day")[:1]
    )
    #: Sessions first; the start day is fallback.
    return Coalesce(
        Subquery(latest_session_day, output_field=models.DateField()),
        F("started_lower"),
        output_field=models.DateField(),
    )


def activity_expression(clock: ActivityClock) -> Combinable:
    """One of the three words, or nothing.

    A completed run's alias is null, and
    `_SetCriterion._not_in_q` keeps that null when a person
    excludes a word. Give it one of the three instead and
    `EXCLUDES Dormant` drops runs finished years ago.
    """
    word = models.CharField(null=True)
    return Case(
        When(completion_recorded_at__isnull=False, then=Value(None, output_field=word)),
        When(
            activity_day__isnull=True,
            then=Value(RunActivity.NEVER_PLAYED, output_field=word),
        ),
        When(
            activity_day__gte=clock.boundary_day,
            then=Value(RunActivity.PLAYING, output_field=word),
        ),
        default=Value(RunActivity.DORMANT, output_field=word),
        output_field=word,
    )


def recency_phrase(day: date, today: date) -> str:
    """How long ago that day was."""
    days = (today - day).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    if days < 365:
        #: Capped, so 360 days reads eleven months.
        months = min(days // 30, 11)
        return f"{months} month ago" if months == 1 else f"{months} months ago"
    years = days // 365
    return f"{years} year ago" if years == 1 else f"{years} years ago"
