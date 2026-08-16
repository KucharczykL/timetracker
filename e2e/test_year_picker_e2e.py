"""Browser coverage for the in-house stats YearPicker."""

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Platform, Session


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.fixture
def stats_data(e2e_library) -> None:
    platform = Platform.objects.create(
        library=e2e_library, name="PC", icon="pc", group="PC"
    )
    game = Game.objects.create(
        library=e2e_library, name="Year Picker Game", platform=platform
    )
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
    _assert_year_picker_geometry(page, popup, grid)
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


def _assert_year_picker_geometry(page, popup, grid):
    popup_box = popup.bounding_box()
    grid_box = grid.bounding_box()
    assert popup_box is not None
    assert grid_box is not None
    left_gap = grid_box["x"] - popup_box["x"]
    right_gap = (
        popup_box["x"] + popup_box["width"] - (grid_box["x"] + grid_box["width"])
    )
    assert abs(left_gap - right_gap) <= 1

    cells = grid.locator("button[data-year]").evaluate_all(
        """
        (elements) => elements.map((element) => {
          const box = element.getBoundingClientRect();
          return { x: box.x, y: box.y, width: box.width };
        })
        """
    )
    widths = [cell["width"] for cell in cells]
    assert max(widths) - min(widths) <= 1

    rows: list[list[dict[str, float]]] = []
    for cell in cells:
        row = next(
            (
                candidate
                for candidate in rows
                if abs(candidate[0]["y"] - cell["y"]) <= 1
            ),
            None,
        )
        if row is None:
            rows.append([cell])
        else:
            row.append(cell)
    assert len(rows) == 3
    for row in rows:
        row.sort(key=lambda cell: cell["x"])
        assert len(row) == 4
    for column in range(4):
        positions = [row[column]["x"] for row in rows]
        assert max(positions) - min(positions) <= 1


def test_stats_year_picker_geometry_scales_and_clamps(
    authenticated_page: Page, live_server, stats_data
):
    page = authenticated_page
    page.set_viewport_size({"width": 600, "height": 800})
    page.goto(f"{live_server.url}{reverse('games:stats_alltime')}")
    picker = page.locator("year-picker")
    toggle = picker.locator("[data-year-picker-toggle]")
    popup = picker.locator("[data-year-picker-popup]")
    grid = picker.locator("[data-year-picker-grid]")
    toggle.click()

    for font_size in ("12px", "16px", "24px"):
        page.locator("html").evaluate(
            "(element, value) => element.style.fontSize = value", font_size
        )
        page.wait_for_timeout(50)
        _assert_year_picker_geometry(page, popup, grid)

    page.set_viewport_size({"width": 360, "height": 800})
    page.locator("html").evaluate("(element) => element.style.fontSize = '16px'")
    page.wait_for_timeout(50)
    popup_box = popup.bounding_box()
    assert popup_box is not None
    assert popup_box["x"] >= 8
    assert popup_box["x"] + popup_box["width"] <= 360 - 8


def test_stats_year_picker_keeps_open_while_clicking_decade_navigation(
    authenticated_page: Page, live_server, stats_data
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:stats_alltime')}")
    picker = page.locator("year-picker")
    toggle = picker.locator("[data-year-picker-toggle]")
    popup = picker.locator("[data-year-picker-popup]")
    previous = picker.locator("[data-year-picker-prev]")
    next_decade = picker.locator("[data-year-picker-next]")

    toggle.click()
    expect(popup).to_be_visible()
    previous.click()
    expect(popup).to_be_visible()
    expect(picker.locator("[data-year-picker-period]")).to_have_text("2010-2019")
    next_decade.click()
    expect(popup).to_be_visible()
    expect(picker.locator("[data-year-picker-period]")).to_have_text("2020-2029")


def test_stats_selected_year_picker_keeps_open_while_clicking_decade_navigation(
    authenticated_page: Page, live_server, stats_data
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:stats_by_year', args=[2024])}")
    picker = page.locator("year-picker")
    toggle = picker.locator("[data-year-picker-toggle]")
    popup = picker.locator("[data-year-picker-popup]")
    previous = picker.locator("[data-year-picker-prev]")
    next_decade = picker.locator("[data-year-picker-next]")

    toggle.click()
    expect(popup).to_be_visible()
    previous.click()
    expect(popup).to_be_visible()
    expect(picker.locator("[data-year-picker-period]")).to_have_text("2010-2019")
    next_decade.click()
    expect(popup).to_be_visible()
    expect(picker.locator("[data-year-picker-period]")).to_have_text("2020-2029")


def test_stats_year_picker_stays_open_for_repeated_previous_clicks(
    authenticated_page: Page, live_server, stats_data
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:stats_by_year', args=[2024])}")
    picker = page.locator("year-picker")
    toggle = picker.locator("[data-year-picker-toggle]")
    popup = picker.locator("[data-year-picker-popup]")
    previous = picker.locator("[data-year-picker-prev]")

    toggle.click()
    for expected_period in ("2010-2019", "2000-2009", "1990-1999"):
        previous.click()
        page.wait_for_timeout(100)
        expect(popup).to_be_visible()
        expect(picker.locator("[data-year-picker-period]")).to_have_text(
            expected_period
        )


def test_stats_year_picker_narrow_viewport_pointer_navigation(
    authenticated_page: Page, live_server, stats_data
):
    page = authenticated_page
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{live_server.url}{reverse('games:stats_by_year', args=[2024])}")
    picker = page.locator("year-picker")
    toggle = picker.locator("[data-year-picker-toggle]")
    popup = picker.locator("[data-year-picker-popup]")
    previous = picker.locator("[data-year-picker-prev]")
    next_decade = picker.locator("[data-year-picker-next]")

    toggle.click()
    for control, expected_period in (
        (previous, "2010-2019"),
        (next_decade, "2020-2029"),
        (previous, "2010-2019"),
    ):
        before = control.bounding_box()
        control.click()
        page.wait_for_timeout(100)
        after = control.bounding_box()
        expect(popup).to_be_visible()
        expect(picker.locator("[data-year-picker-period]")).to_have_text(
            expected_period
        )
        assert before is not None
        assert after is not None


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
