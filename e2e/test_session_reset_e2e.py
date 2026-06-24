"""Browser test for the session-list "Reset start to now" button (issue #33).

Drives the real session list against pytest-django's ``live_server``: clicks the
reset link on a running session, confirms on the dedicated confirm page, and
asserts the row's start time is updated after the full-page redirect.
"""

import datetime as dt

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Platform, Session


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_reset_session_start_to_now(authenticated_page: Page, live_server):
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Reset Game", platform=platform)
    session = Session.objects.create(
        game=game,
        timestamp_start=dt.datetime(2020, 1, 1, 10, 0, tzinfo=dt.timezone.utc),
    )

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    row = page.locator(f"#session-row-{session.id}")
    expect(row).to_contain_text("2020")

    # Reset is a link to a dedicated confirm page (full-page, no htmx).
    row.locator('button[title="Reset start to now"]').click()
    page.get_by_role("button", name="Reset to now").click()

    # Back on the list after the redirect; the old 2020 start time is gone.
    page.wait_for_url(f"{live_server.url}{reverse('games:list_sessions')}")
    row = page.locator(f"#session-row-{session.id}")
    expect(row).not_to_contain_text("2020")
