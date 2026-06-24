"""Browser test for the session-list "Reset start to now" action (issue #33).

Reset now opens an inline confirm modal (the <session-actions> custom element),
and on confirm drives PATCH /api/session/<id> with timestamp_start=now, swapping
the row in place — no full-page navigation. Covers both the confirm and cancel
paths.
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


def _make_running_session() -> Session:
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Reset Game", platform=platform)
    return Session.objects.create(
        game=game,
        timestamp_start=dt.datetime(2020, 1, 1, 10, 0, tzinfo=dt.timezone.utc),
    )


def test_reset_confirm_swaps_row_in_place(authenticated_page: Page, live_server):
    page = authenticated_page
    session = _make_running_session()

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    row = page.locator(f"#session-row-{session.id}")
    expect(row).to_contain_text("2020")

    page.evaluate("window.__noReload = true")

    # Reset opens a confirm modal (no navigation). While open the modal is
    # portaled to <body> (so it isn't a descendant of the hovered row), so the
    # confirm button is located at page level, not under the row.
    row.locator("button[data-reset]").click()
    confirm = page.locator("button[data-reset-confirm]")
    expect(confirm).to_be_visible()

    with page.expect_response(
        lambda response: (
            "/api/session/" in response.url
            and "/device" not in response.url
            and response.request.method == "PATCH"
        )
    ) as response_info:
        confirm.click()

    assert response_info.value.status == 200
    row = page.locator(f"#session-row-{session.id}")
    expect(row).not_to_contain_text("2020")
    assert page.evaluate("window.__noReload") is True, (
        "page reloaded — expected in-place swap"
    )


def test_reset_cancel_leaves_start_unchanged(authenticated_page: Page, live_server):
    page = authenticated_page
    session = _make_running_session()

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    row = page.locator(f"#session-row-{session.id}")

    row.locator("button[data-reset]").click()
    confirm = page.locator("button[data-reset-confirm]")
    expect(confirm).to_be_visible()
    page.locator("button[data-reset-cancel]").click()
    expect(confirm).to_be_hidden()

    # The start time is untouched.
    expect(row).to_contain_text("2020")
    session.refresh_from_db()
    assert session.timestamp_start == dt.datetime(
        2020, 1, 1, 10, 0, tzinfo=dt.timezone.utc
    )
