"""Browser test for the session-list "Finish session now" in-place row swap (issue #53).

Drives the real session list against pytest-django's ``live_server``: clicks the
finish button on a running session and asserts the row is updated in place via
htmx (the row still exists and now shows an end-time em dash separator).
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page, expect

from games.models import Device, Game, Platform, Session


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_finish_session_swaps_row_in_place(authenticated_page: Page, live_server):
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Tunic", platform=platform)
    device = Device.objects.create(name="Desktop")
    session = Session.objects.create(
        game=game, device=device, timestamp_start=timezone.now()
    )

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    row = page.locator(f"#session-row-{session.pk}")
    expect(row).to_be_visible()

    row.locator('button[title="Finish session now"]').click()

    # htmx swaps the row in place; the row still exists and now shows an end
    # time separated by an em dash.
    expect(row).to_contain_text("—")

    session.refresh_from_db()
    assert session.timestamp_end is not None
