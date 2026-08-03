"""Browser coverage for the in-house stats YearPicker."""

from datetime import UTC, datetime, timedelta

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


@pytest.fixture
def stats_data(db) -> None:
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name="Year Picker Game", platform=platform)
    for year in (2024, 2025):
        started = datetime(year, 6, 15, 12, 0, tzinfo=UTC)
        Session.objects.create(
            game=game,
            timestamp_start=started,
            timestamp_end=started + timedelta(hours=1),
        )


def test_stats_year_picker_renders_and_keeps_tab_focus_inside(
    authenticated_page: Page, live_server, stats_data
):
    page = authenticated_page
    requested_urls: list[str] = []
    page.on("request", lambda request: requested_urls.append(request.url))
    page.goto(f"{live_server.url}{reverse('games:stats_alltime')}")

    legacy_bundle = "date" + "picker" + "." + "umd" + "." + "js"
    assert not any(legacy_bundle in url for url in requested_urls)

    picker = page.locator("year-picker")
    toggle = picker.locator("[data-year-picker-toggle]")
    popup = picker.locator("[data-year-picker-popup]")
    grid = picker.locator("[data-year-picker-grid]")
    expect(toggle).to_be_visible()
    toggle.press("ArrowDown")
    expect(toggle).to_be_focused()
    expect(popup).to_be_visible()
    expect(grid.locator("button[data-year]")).to_have_count(12)
    assert "grid-cols-4" in (grid.get_attribute("class") or "")
    popup_box = popup.bounding_box()
    grid_box = grid.bounding_box()
    assert popup_box is not None
    assert grid_box is not None
    assert grid_box["x"] >= popup_box["x"]
    assert grid_box["x"] + grid_box["width"] <= popup_box["x"] + popup_box["width"]
    expect(picker.locator("[data-year-picker-period]")).to_have_text("2020-2029")
    expect(picker.locator("[data-year-picker-prev]")).to_have_accessible_name(
        "Previous decade"
    )
    expect(picker.locator("[data-year-picker-next]")).to_have_accessible_name(
        "Next decade"
    )
    expect(grid.locator('[aria-current="page"]')).to_have_count(0)
    expect(grid.locator("button[disabled]")).to_have_count(4)

    previous = picker.locator("[data-year-picker-prev]")
    first_year = grid.locator("button[data-year]").first
    second_year = grid.locator("button[data-year]").nth(1)
    previous.focus()
    page.keyboard.press("Tab")
    expect(first_year).to_be_focused()
    expect(popup).to_be_visible()
    page.keyboard.press("Tab")
    expect(second_year).to_be_focused()
    expect(popup).to_be_visible()

    previous.focus()
    page.keyboard.press("Shift+Tab")
    expect(toggle).to_be_focused()
    expect(popup).to_be_hidden()

    toggle.click()
    last_enabled_year = grid.locator("button[data-year]:not([disabled])").last
    last_enabled_year.focus()
    page.keyboard.press("Tab")
    expect(popup).to_be_hidden()


def test_stats_year_picker_activates_a_year_with_native_keyboard(
    authenticated_page: Page, live_server, stats_data
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:stats_alltime')}")
    picker = page.locator("year-picker")
    picker.locator("[data-year-picker-toggle]").click()

    year_button = picker.locator('[data-year-picker-grid] button[data-year="2024"]')
    year_button.focus()
    with page.expect_navigation():
        page.keyboard.press("Space")
    expect(page).to_have_url(
        f"{live_server.url}{reverse('games:stats_by_year', args=[2024])}"
    )
