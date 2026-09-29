"""The seeding helper clock-bound tests lean on.

Asserted against a calendar the process clock provably disagrees with,
because agreeing zones prove nothing.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from calendar_days import (
    DISPLACED_ZONES,
    displace_calendar,
    library_noon,
    other_displaced_zone,
    process_day,
)
from django.test import RequestFactory
from session_rows import session_row

from games.models import Game, UserLibrary
from games.reads.calendar import calendar_today
from games.reads.days import DayInterval
from games.reads.playtime import playtime_between_each
from games.views.general import model_counts

pytestmark = pytest.mark.django_db(transaction=True)

HOUR = timedelta(hours=1)


@pytest.fixture
def displaced(owned_user, owned_library) -> str:
    return displace_calendar(owned_user, owned_library)


def _played_today(library: UserLibrary) -> timedelta:
    """The figure the navbar's today reads."""
    (today,) = playtime_between_each(
        library, [DayInterval.single(calendar_today(library))]
    )
    return today.total


def _navbar_today(owned_user) -> str:
    request = RequestFactory().get("/")
    request.user = owned_user
    return str(model_counts(request)["today_played"])


def test_the_fixture_puts_the_clocks_a_day_apart(owned_library, displaced):
    """Guards the guard: agreeing clocks would pass every test below."""
    assert calendar_today(owned_library) != process_day()


def test_noon_lands_on_the_librarys_day(owned_library, displaced):
    noon = library_noon(owned_library)

    assert noon.date() == calendar_today(owned_library)
    assert noon.tzinfo == ZoneInfo(displaced)


def test_days_ago_steps_back_on_the_calendar(owned_library, displaced):
    stepped = library_noon(owned_library, days_ago=6)

    assert stepped.date() == calendar_today(owned_library) - timedelta(days=6)
    assert stepped.tzinfo == ZoneInfo(displaced)


def test_the_other_displaced_zone_is_never_on_the_same_date():
    """What makes a row stated in it provably miss the calendar's day."""
    midnight = datetime(2026, 7, 1, tzinfo=UTC)
    for zone in DISPLACED_ZONES:
        other = ZoneInfo(other_displaced_zone(zone))
        for half_hours in range(48):
            instant = midnight + timedelta(minutes=30 * half_hours)
            assert (
                instant.astimezone(ZoneInfo(zone)).date()
                != instant.astimezone(other).date()
            ), (zone, instant)


def test_a_session_seeded_at_noon_is_counted_by_todays_reader(
    owned_user, owned_library, displaced
):
    """The seeded row and the reader name one day.

    `effective_day` is computed from the row's own `day_zone`, which
    `session_row` takes from the calendar unless one is named.
    """
    game = Game.objects.create(library=owned_library, name="Tunic")
    noon = library_noon(owned_library)
    row = session_row(game, started_at=noon, ended_at=noon + HOUR)

    assert row.day_zone == displaced
    assert _played_today(owned_library) == HOUR
    assert "1 h 00 m" in _navbar_today(owned_user)


def test_a_row_stating_another_zone_misses_the_day(owned_library, displaced):
    """Why a row's zone travels with its instant, stated as a test.

    The same noon, stated in a zone never on the calendar's date, is
    filed under another day and today's reader does not count it.
    """
    game = Game.objects.create(library=owned_library, name="Tunic")
    noon = library_noon(owned_library)
    session_row(
        game,
        started_at=noon,
        ended_at=noon + HOUR,
        day_zone=other_displaced_zone(displaced),
    )

    assert _played_today(owned_library) == timedelta(0)
