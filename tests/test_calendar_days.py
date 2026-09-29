"""The seeding helper every clock-bound test now leans on.

`test_calendar_clock_guard.py` sends a test here instead of the process
clock, so this is where the claim is proved: a fixture built from
`library_noon()` lands on the day a reader asks for, at every hour and
under any calendar zone. Asserted against a calendar the process clock
provably disagrees with, because agreeing zones prove nothing.
"""

import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from calendar_days import library_day_zone, library_noon
from django.test import RequestFactory
from django.utils import timezone as django_timezone
from session_rows import session_row

from games.commands.calendar import SetCalendarDayZone
from games.events.dispatch import dispatch
from games.models import Game
from games.reads.calendar import calendar_today
from games.views.general import model_counts

pytestmark = pytest.mark.django_db(transaction=True)

HOUR = timedelta(hours=1)


@pytest.fixture
def displaced(owned_user, owned_library) -> str:
    """A calendar provably on another date than the process clock.

    The two candidates are 25 hours apart, so one of them always is,
    which makes the assertions below fail at any hour rather than only
    inside the window the defaults disagree in.
    """
    zone = next(
        name
        for name in ("Pacific/Kiritimati", "Pacific/Niue")
        if django_timezone.now().astimezone(ZoneInfo(name)).date()
        != django_timezone.localdate()
    )
    dispatch(
        SetCalendarDayZone(day_zone=zone),
        actor=owned_user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )
    return zone


def test_the_fixture_puts_the_clocks_a_day_apart(owned_library, displaced):
    """Guards the guard: agreeing clocks would pass every test below."""
    assert calendar_today(owned_library) != django_timezone.localdate()


def test_noon_lands_on_the_librarys_day(owned_library, displaced):
    assert library_noon(owned_library).date() == calendar_today(owned_library)


def test_days_ago_steps_back_on_the_calendar(owned_library, displaced):
    stepped = library_noon(owned_library, days_ago=6)

    assert stepped.date() == calendar_today(owned_library) - timedelta(days=6)
    assert stepped.tzinfo == library_noon(owned_library).tzinfo


def test_a_session_seeded_at_noon_is_counted_by_todays_reader(
    owned_user, owned_library, displaced
):
    """The whole point: the seeded row and the reader name one day.

    `effective_day` is computed from the row's own `day_zone`, so the
    zone travels with the instant -- an instant alone would land a day
    out wherever the row's zone and the calendar's differ.
    """
    game = Game.objects.create(library=owned_library, name="Tunic")
    noon = library_noon(owned_library)
    session_row(
        game,
        started_at=noon,
        ended_at=noon + HOUR,
        day_zone=library_day_zone(owned_library),
    )
    request = RequestFactory().get("/")
    request.user = owned_user

    assert "1 h 00 m" in str(model_counts(request)["today_played"])


def test_an_instant_without_its_zone_can_miss_the_day(
    owned_user, owned_library, displaced
):
    """Why `library_day_zone()` exists, stated as a test.

    The default zone `session_rows` stamps is not the displaced
    calendar's, so the same instant is filed under another day and
    today's reader does not see it.
    """
    game = Game.objects.create(library=owned_library, name="Tunic")
    noon = library_noon(owned_library)
    #: No day_zone: the row keeps the helper's own default.
    session_row(game, started_at=noon, ended_at=noon + HOUR)
    request = RequestFactory().get("/")
    request.user = owned_user

    assert "1 h 00 m" not in str(model_counts(request)["today_played"])
