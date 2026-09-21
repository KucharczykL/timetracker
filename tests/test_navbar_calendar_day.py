"""The navbar counts its days on the library's calendar."""

import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.test import RequestFactory
from django.utils import timezone as django_timezone
from session_rows import duration_only_row, tracked_run

from games.commands.calendar import SetCalendarDayZone
from games.events.dispatch import dispatch
from games.models import Game
from games.reads.calendar import calendar_today
from games.views.general import model_counts

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def elsewhere(owned_user, owned_library) -> str:
    """A calendar provably on another date than the process clock.

    `Pacific/Kiritimati` and `Pacific/Niue` are 25 hours
    apart, so one of them is always on another date. A day
    taken from the process clock is then wrong at every
    hour, not only for the two a night the defaults
    disagree.
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


@pytest.fixture
def run(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    return tracked_run(owned_library, game)


def _figures(owned_user) -> tuple[str, str]:
    request = RequestFactory().get("/")
    request.user = owned_user
    counts = model_counts(request)
    return str(counts["today_played"]), str(counts["last_7_played"])


def test_the_navbar_counts_today_on_the_library_calendar(
    owned_user, owned_library, elsewhere, run
):
    """A day the library is on is today, whatever the process reads."""
    duration_only_row(run, calendar_today(owned_library), timedelta(hours=1))

    today_html, _ = _figures(owned_user)

    assert "1 h 00 m" in today_html


def test_the_navbar_week_ends_on_the_calendar_day(
    owned_user, owned_library, elsewhere, run
):
    """Seven calendar days, both ends counted on the calendar.

    A window a day out drops one end or the other,
    whichever way the two zones differ right now, so both
    ends are stated here.
    """
    today = calendar_today(owned_library)
    duration_only_row(run, today, timedelta(hours=1))
    duration_only_row(run, today - timedelta(days=6), timedelta(hours=1))

    _, last_7_html = _figures(owned_user)

    assert "2 h 00 m" in last_7_html
