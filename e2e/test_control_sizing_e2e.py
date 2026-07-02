"""Same-row controls share one rendered height (issue #272 follow-up).

The session-list row mixes a text control (the device-selector trigger, an
outline ControlButton) with icon-only segmented buttons (finish/reset/edit/
delete). Both follow ControlButton's container sizing scale, and button icons
are sized to the text line-height — so an icon-only button must not out-grow
a text one sitting on the same row.
"""

import datetime as dt

import pytest
from django.urls import reverse
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


def _make_session() -> Session:
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Sized Game", platform=platform)
    Device.objects.create(name="Handheld", type=Device.HANDHELD)
    # running (no end) so the row shows the finish/reset icon actions
    return Session.objects.create(
        game=game,
        timestamp_start=dt.datetime(2020, 1, 1, 10, 0, tzinfo=dt.timezone.utc),
    )


def test_selector_trigger_and_icon_actions_share_height(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    session = _make_session()

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    row = page.locator(f"#session-row-{session.id}")
    expect(row).to_be_visible()

    selector_trigger = row.locator("drop-down [data-toggle]").first
    reset_button = row.locator("button[data-reset]")
    expect(selector_trigger).to_be_visible()
    expect(reset_button).to_be_visible()

    trigger_box = selector_trigger.bounding_box()
    action_box = reset_button.bounding_box()
    assert trigger_box is not None and action_box is not None
    assert abs(trigger_box["height"] - action_box["height"]) <= 1, (
        f"device selector trigger is {trigger_box['height']}px tall but the "
        f"icon action button is {action_box['height']}px"
    )
