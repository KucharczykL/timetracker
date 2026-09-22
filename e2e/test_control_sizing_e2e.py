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
from session_rows import session_row

from games.models import Device, Game, Platform, PlayerSession


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _make_session(library) -> PlayerSession:
    platform = Platform.objects.create(
        library=library, name="PC", icon="pc", group="PC"
    )
    game = Game.objects.create(library=library, name="Sized Game", platform=platform)
    Device.objects.create(library=library, name="Handheld", type=Device.HANDHELD)
    # running (no end) so the row shows the finish/reset icon actions
    return session_row(
        game,
        started_at=dt.datetime(2020, 1, 1, 10, 0, tzinfo=dt.UTC),
    )


def test_selector_trigger_and_the_row_menu_share_height(
    authenticated_page: Page, live_server, e2e_library
):
    """The row's two controls stand the same height.

    The icon action group this compared against is gone: a row states its
    acts behind one trigger now, and that trigger is the control the device
    selector stands beside.
    """
    page = authenticated_page
    session = _make_session(e2e_library)

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    row = page.locator(f"#session-row-{session.id}")
    expect(row).to_be_visible()

    selector_trigger = row.locator("drop-down [data-toggle]").first
    menu_trigger = row.locator(f"#session-menu-{session.id}Link")
    expect(selector_trigger).to_be_visible()
    expect(menu_trigger).to_be_visible()

    trigger_box = selector_trigger.bounding_box()
    menu_box = menu_trigger.bounding_box()
    assert trigger_box is not None and menu_box is not None
    assert abs(trigger_box["height"] - menu_box["height"]) <= 1, (
        f"device selector trigger is {trigger_box['height']}px tall but the "
        f"row menu trigger is {menu_box['height']}px"
    )
