"""Browser tests for the Playtime page."""

import pytest
from django.urls import reverse
from historical_playtime_rows import record_row
from playwright.sync_api import Page, expect
from session_rows import tracked_run

from games.models import Game, HistoricalPlaytimeProvenance


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    _login(page, live_server)
    return page


@pytest.fixture
def records(e2e_library):
    measured = tracked_run(
        e2e_library, Game.objects.create(library=e2e_library, name="Measured Game")
    )
    guessed = tracked_run(
        e2e_library, Game.objects.create(library=e2e_library, name="Guessed Game")
    )
    record_row([measured], provenance=HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED)
    record_row([guessed])


def test_the_playtime_tabs_move_between_the_lists(
    authenticated_page: Page, live_server, records
):
    page = authenticated_page
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    tabs = page.get_by_role("navigation", name="Playtime")
    expect(tabs.get_by_role("link", name="Sessions")).to_have_attribute(
        "aria-current", "page"
    )

    tabs.get_by_role("link", name="Historical").click()
    page.wait_for_url(f"**{reverse('games:list_historical_playtime')}")
    tabs = page.get_by_role("navigation", name="Playtime")
    expect(tabs.get_by_role("link", name="Historical")).to_have_attribute(
        "aria-current", "page"
    )
    expect(
        page.locator("[data-truncated-clip]", has_text="Measured Game")
    ).to_be_visible()
    assert errors == []


def test_the_provenance_facet_narrows_the_list(
    authenticated_page: Page, live_server, records
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_historical_playtime')}")

    page.locator("#quick-provenance-dropdownLink").click()
    widget = page.locator('#quick-provenance-dropdown search-select[name="provenance"]')
    widget.locator(
        '[data-search-select-option][data-label="Externally measured"] '
        '[data-search-select-action="include"]'
    ).click()
    page.locator('quick-filter-bar button[type="submit"]').click()

    page.wait_for_url("**filter=**")
    expect(
        page.locator("[data-truncated-clip]", has_text="Measured Game")
    ).to_be_visible()
    expect(
        page.locator("[data-truncated-clip]", has_text="Guessed Game")
    ).to_have_count(0)

    expect(page.get_by_text("Advanced filter active")).to_have_count(0)
    page.locator("#quick-provenance-dropdownLink").click()
    pill = page.locator(
        '#quick-provenance-dropdown search-select[name="provenance"] [data-pill]'
    )
    expect(pill).to_have_count(1)
    expect(pill).to_contain_text("Externally measured")


def test_the_advanced_filter_link_opens_the_builder(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_historical_playtime')}")

    page.get_by_role("link", name="Advanced filter…").click()

    page.wait_for_url(
        f"**{reverse('games:filter_builder', args=['historicalplaytime'])}**"
    )
    expect(page.locator("filter-group")).to_be_attached()
