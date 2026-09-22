"""A person turns a column off in the browser, and it stays off."""

import datetime as dt

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import timed_row, tracked_run

from games.models import Device, Game, Platform

STARTED_AT = dt.datetime(2026, 3, 5, 10, tzinfo=dt.UTC)


@pytest.fixture
def one_session(e2e_library):
    platform = Platform.objects.create(
        library=e2e_library, name="PC", icon="pc", group="PC"
    )
    game = Game.objects.create(library=e2e_library, name="Tunic", platform=platform)
    device = Device.objects.create(library=e2e_library, name="Steam Deck")
    timed_row(
        tracked_run(e2e_library, game),
        STARTED_AT,
        STARTED_AT + dt.timedelta(hours=1),
        device=device,
    )
    return game


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.set_viewport_size({"width": 1400, "height": 1000})
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _open_the_panel(page: Page):
    page.click('button[aria-label="Choose columns"]')
    panel = page.locator('[role="dialog"][aria-label="Choose columns"]')
    expect(panel).to_be_visible()
    return panel


def _header(page: Page, label: str):
    """The header cell naming that column, never the panel that lists them all."""
    return (
        page.locator("thead th")
        .filter(has_text=label)
        .filter(has_not=page.locator('[role="dialog"]'))
    )


def test_a_column_that_starts_hidden_shows_when_a_person_says_so(
    authenticated_page: Page, live_server, one_session
):
    """Created starts off, so showing it is the statement, not hiding it."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    expect(_header(page, "Created")).to_have_count(0)

    panel = _open_the_panel(page)
    panel.locator('input[name="shown"][value="created"]').check()
    panel.get_by_role("button", name="Apply").click()
    page.wait_for_url("**/session/list**")

    expect(_header(page, "Created")).to_have_count(1)

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    expect(_header(page, "Created")).to_have_count(1)

    panel = _open_the_panel(page)
    panel.get_by_role("button", name="Reset").click()
    page.wait_for_url("**/session/list**")

    expect(_header(page, "Created")).to_have_count(0)


def test_a_column_turned_off_stays_off(
    authenticated_page: Page, live_server, one_session
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    expect(_header(page, "Device")).to_have_count(1)

    panel = _open_the_panel(page)
    panel.locator('input[name="shown"][value="device"]').uncheck()
    panel.get_by_role("button", name="Apply").click()
    page.wait_for_url("**/session/list**")

    expect(_header(page, "Device")).to_have_count(0)

    #: A fresh load reads the row, not the last response.
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    expect(_header(page, "Device")).to_have_count(0)

    panel = _open_the_panel(page)
    panel.get_by_role("button", name="Reset").click()
    page.wait_for_url("**/session/list**")

    expect(_header(page, "Device")).to_have_count(1)


def test_the_panel_opens_clear_of_the_table_that_clips_it(
    authenticated_page: Page, live_server, one_session
):
    """The shell is overflow-clip, so an anchored panel would be sliced."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    panel = _open_the_panel(page)

    fixed = panel.evaluate("panel => getComputedStyle(panel).position")
    inside = panel.evaluate(
        """panel => {
            const shell = panel.closest('[class*="overflow-clip"]');
            if (!shell) return false;
            const box = panel.getBoundingClientRect();
            const edge = shell.getBoundingClientRect();
            return box.bottom > edge.bottom;
        }"""
    )

    assert fixed == "fixed"
    assert inside is not False


OCCLUSION = """
(panel) => {
    const box = panel.getBoundingClientRect();
    let covered = 0;
    let total = 0;
    for (let x = box.left + 6; x < box.right - 6; x += 20) {
        for (let y = box.top + 6; y < box.bottom - 6; y += 20) {
            total += 1;
            if (!panel.contains(document.elementFromPoint(x, y))) covered += 1;
        }
    }
    return [covered, total];
}
"""


def test_the_open_panel_covers_the_rows_own_dropdowns(
    authenticated_page: Page, live_server, one_session
):
    """Every row carries a device selector on its own stratum; a panel that
    states no stratum of its own opens underneath them."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    panel = _open_the_panel(page)

    selectors = page.locator("tbody [data-menu]").count()
    covered, total = panel.evaluate(OCCLUSION)

    assert selectors > 0, "no row dropdown to open over; nothing is measured"
    assert total > 0, "the panel sampled no points"
    assert covered == 0, f"{covered}/{total} points of the panel are covered"


def test_a_column_that_refuses_to_hide_offers_no_choice(
    authenticated_page: Page, live_server, one_session
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    panel = _open_the_panel(page)

    name = panel.locator('input[name="shown"][value="name"]')

    expect(name).to_be_checked()
    expect(name).to_be_disabled()
