"""Whether an unfinished run is being played."""

from datetime import date, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.db import models
from django.db.models import Case, F, OuterRef, Subquery, Value, When
from django.db.models.expressions import Combinable
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone as django_timezone

from games.models import Session, UserLibrary
from timetracker.settings_registry import DEFAULT_DORMANT_AFTER_DAYS
from timetracker.settings_resolver import resolve_for_user, resolve_str_for_user


class RunActivity(models.TextChoices):
    """The three words a clock counts."""

    PLAYING = "playing", "Playing"
    DORMANT = "dormant", "Dormant"
    NEVER_PLAYED = "never_played", "Never played"


class ActivityClock(NamedTuple):
    """How long is too long, today."""

    threshold_days: int
    zone: ZoneInfo
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
    zone = ZoneInfo(resolve_str_for_user(user, "DISPLAY_TIME_ZONE"))
    return _clock(threshold_days, zone)


def default_activity_clock() -> ActivityClock:
    """The registry default in UTC, no viewer."""
    return _clock(DEFAULT_DORMANT_AFTER_DAYS, ZoneInfo("UTC"))


def _clock(threshold_days: int, zone: ZoneInfo) -> ActivityClock:
    today = django_timezone.now().astimezone(zone).date()
    return ActivityClock(
        threshold_days=threshold_days,
        zone=zone,
        boundary_day=today - timedelta(days=threshold_days),
    )


def activity_day_expression(clock: ActivityClock) -> Combinable:
    """The day the word reads.

    The subquery states the run's own library column, so
    a run at a shared catalog game reads no session. Drop
    it and one library's play moves another's word.
    """
    latest_session_day = (
        Session.objects.alive()
        .filter(
            game=OuterRef("player_game__game"),
            game__library=OuterRef("library"),
            game__removed_at__isnull=True,
        )
        .annotate(played_day=TruncDate("timestamp_start", tzinfo=clock.zone))
        .order_by("-timestamp_start")
        .values("played_day")[:1]
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
