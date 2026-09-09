"""The clock that says whether a run is being played."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone as django_timezone

from games.models import UserPreferences
from games.reads.playthrough_activity import activity_clock, recency_phrase
from timetracker import settings_resolver


def _today_in(zone: ZoneInfo) -> date:
    return django_timezone.now().astimezone(zone).date()


@pytest.mark.django_db
def test_the_clock_reads_thirty_days_by_default(owned_library):
    clock = activity_clock(owned_library)

    assert clock.threshold_days == 30
    assert clock.boundary_day == _today_in(clock.zone) - timedelta(days=30)


@pytest.mark.django_db
def test_a_personal_threshold_moves_the_boundary(owned_user, owned_library):
    UserPreferences.objects.filter(user=owned_user).update(
        extra_preferences={"DORMANT_AFTER_DAYS": 7}
    )
    settings_resolver.clear_cache()

    clock = activity_clock(owned_library)

    assert clock.threshold_days == 7
    assert clock.boundary_day == _today_in(clock.zone) - timedelta(days=7)


@pytest.mark.django_db
def test_the_clock_reads_the_viewers_zone(owned_user, owned_library):
    UserPreferences.objects.filter(user=owned_user).update(
        display_time_zone="Pacific/Kiritimati"
    )
    settings_resolver.clear_cache()

    assert activity_clock(owned_library).zone == ZoneInfo("Pacific/Kiritimati")


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 9, 9), "today"),
        (date(2026, 9, 8), "yesterday"),
        (date(2026, 9, 5), "4 days ago"),
        (date(2026, 8, 9), "1 month ago"),
        (date(2026, 6, 9), "3 months ago"),
        (date(2025, 9, 9), "1 year ago"),
        (date(2023, 9, 9), "3 years ago"),
    ],
)
def test_the_recency_phrase_reads_the_distance(day: date, expected: str):
    assert recency_phrase(day, date(2026, 9, 9)) == expected


def test_a_day_in_the_future_reads_today():
    assert recency_phrase(date(2026, 9, 10), date(2026, 9, 9)) == "today"
