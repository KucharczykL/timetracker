"""Browser test for the session-list "Finish session now" action (issue #53).

Finishing now drives PATCH /api/session/<id> and swaps the row in place via the
<session-actions> custom element + renderSessionRow — no full-page reload. This
test asserts the row updates without navigation and the PATCH succeeds (200, not
403 — the real-browser CSRF path).
"""

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Browser, Page, expect

from games.models import Device, Game, Platform, Session, UserPreferences


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

    # A sentinel that a full-page reload would wipe — proves the swap is in-place.
    page.evaluate("window.__noReload = true")

    with page.expect_response(
        lambda response: (
            "/api/session/" in response.url
            and "/device" not in response.url
            and response.request.method == "PATCH"
        )
    ) as response_info:
        row.locator("button[data-finish]").click()

    assert response_info.value.status == 200, (
        f"finish PATCH returned {response_info.value.status}; expected 200 "
        "(403 would mean CSRF was rejected in the browser)."
    )

    # The same row (same id) now shows the end time and loses the finish/reset
    # controls — all without navigating.
    row = page.locator(f"#session-row-{session.pk}")
    expect(row).to_contain_text("—")
    expect(row.locator("button[data-finish]")).to_have_count(0)
    expect(row.locator("button[data-reset]")).to_have_count(0)
    assert page.evaluate("window.__noReload") is True, (
        "page reloaded — expected in-place swap"
    )

    session.refresh_from_db()
    assert session.timestamp_end is not None


def test_finish_preserves_server_rendered_start_across_browser_timezone(
    authenticated_page: Page, browser: Browser, live_server, django_user_model
):
    """The rebuilt row must retain Django's text despite the browser's zone."""
    UserPreferences.objects.create(
        user=django_user_model.objects.get(username="tester"),
        display_time_zone="Europe/Prague",
    )
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Tunic", platform=platform)
    session = Session.objects.create(
        game=game,
        timestamp_start=dt.datetime(2026, 1, 1, 0, 30, tzinfo=dt.UTC),
    )

    context = browser.new_context(timezone_id="Pacific/Honolulu")
    try:
        page = context.new_page()
        page.goto(f"{live_server.url}{reverse('login')}")
        page.fill('input[name="username"]', "tester")
        page.fill('input[name="password"]', "secret123")
        page.click('button:has-text("Login")')
        page.wait_for_url(f"{live_server.url}/tracker**")
        assert (
            page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            == "Pacific/Honolulu"
        )

        page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
        row = page.locator(f"#session-row-{session.pk}")
        time_cell = row.locator("td").nth(0)
        expect(time_cell).to_have_text("01/01/2026 01:30")
        server_rendered_start = time_cell.inner_text()

        with page.expect_response(
            lambda response: (
                "/api/session/" in response.url
                and "/device" not in response.url
                and response.request.method == "PATCH"
            )
        ) as response_info:
            row.locator("button[data-finish]").click()

        assert response_info.value.status == 200

        row = page.locator(f"#session-row-{session.pk}")
        expect(row.locator("button[data-finish]")).to_have_count(0)
        rendered_start, separator, _ = (
            row.locator("td").nth(0).inner_text().partition(" — ")
        )
        assert separator == " — "
        assert rendered_start.encode() == server_rendered_start.encode()
    finally:
        context.close()


def test_device_selector_still_works_after_finish(
    authenticated_page: Page, live_server
):
    """Guards the device-node clone: after the row is rebuilt, the cloned
    <drop-down> must re-wire and its PATCH still succeed (204)."""
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Tunic", platform=platform)
    desktop = Device.objects.create(name="Desktop")
    deck = Device.objects.create(name="Deck")
    session = Session.objects.create(
        game=game, device=desktop, timestamp_start=timezone.now()
    )

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    row = page.locator(f"#session-row-{session.pk}")
    row.locator("button[data-finish]").click()
    expect(row).to_contain_text("—")  # wait for the swap to land

    # Now drive the cloned device selector and assert its PATCH succeeds.
    host = row.locator('drop-down[behavior="select"]')
    host.wait_for(state="attached")
    host.locator("[data-toggle]").click()
    host.locator("[data-menu]").wait_for(state="visible")
    with page.expect_response(
        lambda response: (
            "/device" in response.url and response.request.method == "PATCH"
        )
    ) as response_info:
        host.locator(f'[data-option][data-value="{deck.id}"]').click()
    assert response_info.value.status < 400, (
        f"device PATCH after finish returned {response_info.value.status}; "
        "the cloned drop-down did not re-wire."
    )
    session.refresh_from_db()
    assert session.device_id == deck.id
