"""Whether an unfinished run is being played.

A clock answers, not a column. Nothing here is written:
the words are counted from the last day the game was
played and the threshold the person owns.
"""

from datetime import date, timedelta
from typing import NamedTuple, cast
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
    """What an unfinished run's clock says.

    Not `PlayerGameStatus`: a status is stated by a person
    and a condition is counted in days. Never played is
    spelled apart from the status `Unplayed` on purpose,
    because Game detail prints both beside one game.
    """

    PLAYING = "playing", "Playing"
    DORMANT = "dormant", "Dormant"
    NEVER_PLAYED = "never_played", "Never played"


class ActivityClock(NamedTuple):
    """One request's answer to "how long is too long"."""

    threshold_days: int
    zone: ZoneInfo
    boundary_day: date


def activity_clock(library: UserLibrary) -> ActivityClock:
    """The threshold and the zone this library reads by.

    Built from the library, never passed in: a parameter
    lets one call site state the viewer's threshold and
    the next forget it.
    """
    user = library.user
    threshold_days = cast(int, resolve_for_user(user, "DORMANT_AFTER_DAYS"))
    zone = ZoneInfo(resolve_str_for_user(user, "DISPLAY_TIME_ZONE"))
    return _clock(threshold_days, zone)


def default_activity_clock() -> ActivityClock:
    """What a read with no viewer counts by.

    The registry default in UTC. A filter compiled only to
    be validated executes nothing, so the numbers it counts
    with never reach a screen.
    """
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

    The latest live session at the run's game, as this
    library sees sessions, else the run's own start day.
    A preference, not a maximum: a game with sessions
    never reads its start day.

    The library is stated as the run's own column, so a
    run at a shared catalog game reads no session and one
    library's play never moves another's word.
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
    return Coalesce(
        Subquery(latest_session_day, output_field=models.DateField()),
        F("started_lower"),
        output_field=models.DateField(),
    )


def activity_expression(clock: ActivityClock) -> Combinable:
    """One of the three words, or nothing.

    A completed run is not unfinished, so no clock speaks
    about it and the alias is null. That null is what
    `_SetCriterion._not_in_q` keeps when a person excludes
    a word.
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
    """How long ago that day was, in plain words.

    A day ahead of today reads `today`: a session may be
    recorded in a zone ahead of the viewer's.
    """
    days = (today - day).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    if days < 365:
        months = days // 30
        return f"{months} month ago" if months == 1 else f"{months} months ago"
    years = days // 365
    return f"{years} year ago" if years == 1 else f"{years} years ago"
