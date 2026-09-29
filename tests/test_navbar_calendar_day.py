"""The navbar counts days on the calendar."""

from datetime import timedelta

import pytest
from calendar_days import displace_calendar
from django.test import RequestFactory
from session_rows import duration_only_row, tracked_run

from games.events.playersession import ZoneName
from games.models import Game
from games.reads.calendar import calendar_today
from games.views.general import model_counts

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def elsewhere(owned_library) -> ZoneName:
    return displace_calendar(owned_library)


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
    """The library's day is today, not the process."""
    duration_only_row(run, calendar_today(owned_library), timedelta(hours=1))

    today_html, _ = _figures(owned_user)

    assert "1 h 00 m" in today_html


def test_the_navbar_week_ends_on_the_calendar_day(
    owned_user, owned_library, elsewhere, run
):
    """Seven days, both ends on the calendar.

    A window a day out drops one end or the other,
    whichever way the zones differ, so both are stated.
    """
    today = calendar_today(owned_library)
    duration_only_row(run, today, timedelta(hours=1))
    duration_only_row(run, today - timedelta(days=6), timedelta(hours=1))

    _, last_7_html = _figures(owned_user)

    assert "2 h 00 m" in last_7_html
