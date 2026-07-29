"""Browser test for the session-list "Reset start to now" action (issue #33).

Reset is a page, not a modal: the row links to a confirmation that posts to
games:reset_session. Reset overwrites the original start time and is only
recoverable by editing the session, which is why it confirms at all. Covers
both the confirm and cancel paths.
"""

import datetime as dt

import pytest
from django.urls import reverse
from playwright.sync_api import Browser, Page, expect

from games.models import Game, Platform, Session

STARTED_AT = dt.datetime(2020, 1, 1, 10, 0, tzinfo=dt.UTC)


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _make_running_session() -> Session:
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Reset Game", platform=platform)
    return Session.objects.create(game=game, timestamp_start=STARTED_AT)


def test_reset_confirms_on_its_own_page_then_returns_to_the_list(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    session = _make_running_session()

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    row = page.locator(f"#session-row-{session.id}")
    expect(row).to_contain_text("2020")

    row.locator('a[href*="/reset"]').click()

    expect(page.locator("body")).to_contain_text("Reset Game")
    page.locator('button:has-text("Reset to now")').click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}*")
    expect(page.locator(f"#session-row-{session.id}")).not_to_contain_text("2020")

    session.refresh_from_db()
    assert session.timestamp_start > STARTED_AT


def test_reset_cancel_leaves_start_unchanged(authenticated_page: Page, live_server):
    page = authenticated_page
    session = _make_running_session()

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    page.locator(f"#session-row-{session.id}").locator('a[href*="/reset"]').click()

    page.locator('a:has-text("Cancel")').click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}*")
    expect(page.locator(f"#session-row-{session.id}")).to_contain_text("2020")
    session.refresh_from_db()
    assert session.timestamp_start == STARTED_AT


def test_reset_stamps_the_browser_zone(
    authenticated_page: Page, browser: Browser, live_server
):
    session = _make_running_session()

    context = browser.new_context(timezone_id="Pacific/Honolulu")
    try:
        page = context.new_page()
        page.goto(f"{live_server.url}{reverse('login')}")
        page.fill('input[name="username"]', "tester")
        page.fill('input[name="password"]', "secret123")
        page.click('button:has-text("Login")')
        page.wait_for_url(f"{live_server.url}/tracker**")

        page.goto(
            f"{live_server.url}{reverse('games:reset_session', args=[session.id])}"
        )
        page.locator('button:has-text("Reset to now")').click()
        page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}*")

        session.refresh_from_db()
        assert session.timestamp_start_timezone == "Pacific/Honolulu"
    finally:
        context.close()
