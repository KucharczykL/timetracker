"""Browser test for the session-list "Finish session now" action (issue #53).

Finishing posts to games:finish_session and the sessions list re-renders, so
the assertions here are about the server-rendered page after navigation — the
row loses its finish control and gains an end time.
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


def _finish_control(row):
    return row.locator('form[action*="/finish"] button[type="submit"]')


def test_finish_session_reloads_the_list_with_the_session_closed(
    authenticated_page: Page, live_server
):
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

    _finish_control(row).click()

    # The server-rendered row is the signal the write committed; only then is
    # the database worth reading.
    row = page.locator(f"#session-row-{session.pk}")
    expect(row).to_contain_text("—")
    expect(_finish_control(row)).to_have_count(0)
    expect(row.locator('a[href*="/reset"]')).to_have_count(0)

    session.refresh_from_db()
    assert session.timestamp_end is not None


def test_finish_stamps_the_browser_zone_not_the_account_zone(
    authenticated_page: Page, browser: Browser, live_server, django_user_model
):
    """The end zone records where the user was, which is the whole reason each
    timestamp carries its own zone rather than inheriting the account's."""
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

        page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
        row = page.locator(f"#session-row-{session.pk}")
        _finish_control(row).click()

        expect(page.locator(f"#session-row-{session.pk}")).to_contain_text("—")

        session.refresh_from_db()
        assert session.timestamp_end_timezone == "Pacific/Honolulu"
    finally:
        context.close()


def test_device_selector_still_works_after_finish(
    authenticated_page: Page, live_server
):
    """The device selector is a separate control on the same row; finishing
    must not disturb its PATCH."""
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
    _finish_control(row).click()

    row = page.locator(f"#session-row-{session.pk}")
    expect(row).to_contain_text("—")

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
        f"device PATCH after finish returned {response_info.value.status}."
    )
    session.refresh_from_db()
    assert session.device_id == deck.id
