"""A date preset names the day the server answers in, not the browser's.

The browser here runs 25 hours behind the display zone (Pacific/Niue against
Pacific/Kiritimati), so the two never share a calendar date. A preset computed
from `new Date()` therefore always names a day the filter does not (#949).
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Platform, Session
from timetracker.settings_commands import change_user_setting

DISPLAY_ZONE = "Pacific/Kiritimati"
BROWSER_ZONE = "Pacific/Niue"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "timezone_id": BROWSER_ZONE}


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    change_user_setting(e2e_user, "DISPLAY_TIME_ZONE", DISPLAY_ZONE)
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_today_preset_uses_the_display_zone(
    authenticated_page: Page, live_server, e2e_library
):
    platform = Platform.objects.create(library=e2e_library, name="PC", icon="pc")
    game = Game.objects.create(library=e2e_library, name="Doom", platform=platform)
    now = dt.datetime.now(dt.UTC)
    session = Session.objects.create(
        game=game, timestamp_start=now, timestamp_end=now + dt.timedelta(minutes=30)
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    page.locator("#quick-timestamp_start-dropdownLink").click()
    panel = page.locator("#quick-timestamp_start-dropdown")
    panel.locator('[data-date-range-preset="today"]').click()

    display_today = now.astimezone(ZoneInfo(DISPLAY_ZONE)).date().isoformat()
    browser_today = now.astimezone(ZoneInfo(BROWSER_ZONE)).date().isoformat()
    assert display_today != browser_today
    expect(panel.locator("[data-range-min]")).to_have_value(display_today)
    expect(panel.locator("[data-range-max]")).to_have_value(display_today)

    page.locator('quick-filter-bar button[type="submit"]').click()
    page.wait_for_url("**filter=**")
    expect(page.locator(f"#session-row-{session.pk}")).to_be_visible()
