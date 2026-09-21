"""Which year a page offers, and whose."""

import uuid
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse

from common.time import available_stats_year_range
from games.commands.calendar import SetCalendarDayZone
from games.events.dispatch import dispatch
from games.reads.calendar import calendar_today
from games.views.general import global_current_year
from timetracker.settings_commands import change_user_setting

#: New Year east of UTC-4; Niue is behind.
NEW_YEAR = datetime(2031, 1, 1, 5, 0, tzinfo=ZoneInfo("UTC"))
BEHIND = "Pacific/Niue"


@pytest.fixture
def new_year(owned_user, owned_library):
    """The library a year behind the process."""
    dispatch(
        SetCalendarDayZone(day_zone=BEHIND),
        actor=owned_user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )
    with patch("django.utils.timezone.now", return_value=NEW_YEAR):
        yield


@pytest.fixture
def logged_in(client, owned_user, settings):
    #: Years ahead below; a real-now session expires.
    settings.SESSION_COOKIE_AGE = 60 * 60 * 24 * 365 * 20
    client.force_login(owned_user)
    return client


def test_the_year_range_starts_at_the_day_it_is_given():
    """The range is stated, not read."""
    years = available_stats_year_range(date(2031, 2, 3))

    assert years[0] == 2031
    assert years[-1] == 2000


@pytest.mark.django_db(transaction=True)
def test_the_global_year_is_the_library_year(owned_user, owned_library, new_year):
    """One library, one year, not the process's."""
    request = RequestFactory().get("/")
    request.user = owned_user

    published = global_current_year(request)

    assert published == {"global_current_year": 2030}
    assert calendar_today(owned_library).year == 2030


@pytest.mark.django_db
def test_the_global_year_stands_without_a_library():
    """A viewer with no library gets one."""
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    published = global_current_year(request)

    assert published["global_current_year"] >= 2026


@pytest.mark.django_db(transaction=True)
def test_the_landing_redirect_names_the_library_year(
    logged_in, owned_user, owned_library, new_year
):
    """A landing lands on the library's year."""
    change_user_setting(owned_user, "DEFAULT_LANDING_PAGE", "games:stats_by_year")

    response = logged_in.get(reverse("games:index"))

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("games:stats_by_year", args=[2030])
