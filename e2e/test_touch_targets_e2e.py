"""WCAG 2.5.8 touch-target size for small glyph-only controls (#454).

The truncation-reveal button is shown only on no-hover (touch) devices, where it
must be at least 24x24. This drives a mobile, no-hover context and proves the
button is visible, meets the minimum size, and activates on a press.

The calendar's ‹ / › month-nav buttons are the other glyph-only controls small
enough to fail this: their glyphs are ~4px wide, so a padding-only hit area
came out 16px (#485 follow-up). They are sized from the day-cell module instead.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Platform

MIN_TOUCH_TARGET = 24


@pytest.fixture
def touch_page(live_server, browser, e2e_user):
    context = browser.new_context(
        has_touch=True, is_mobile=True, viewport={"width": 390, "height": 844}
    )
    page = context.new_page()
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    yield page
    context.close()


def test_reveal_button_meets_min_touch_target(
    touch_page: Page, live_server, e2e_library
):
    page = touch_page
    platform = Platform.objects.create(
        library=e2e_library,
        name="Steam",
        icon="steam",
        group="PC",
    )
    Game.objects.create(
        library=e2e_library,
        name="A Very Long Game Name That Exceeds The Thirty Char Limit",
        platform=platform,
    )
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    button = page.locator("truncated-text button[data-truncated-reveal]").first
    expect(button).to_be_visible()  # shown on a no-hover device
    box = button.bounding_box()
    assert box is not None
    assert box["width"] >= MIN_TOUCH_TARGET, (
        f"reveal button width {box['width']} too small"
    )
    assert box["height"] >= MIN_TOUCH_TARGET, (
        f"reveal button height {box['height']} too small"
    )

    panel = page.locator("truncated-text [data-pop-over-panel]").first
    expect(panel).to_be_hidden()
    button.tap()
    expect(panel).to_be_visible()


def test_calendar_controls_meet_min_touch_target(touch_page: Page, live_server):
    """The date field's calendar toggle and the popup's ‹/› month-nav buttons
    are all glyph-only, so their hit areas come from explicit sizing, not from
    padding around a ~4px glyph (#485 follow-up)."""
    page = touch_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")

    toggle = page.locator("[data-date-picker-calendar-toggle]").first
    expect(toggle).to_be_visible()
    toggle_box = toggle.bounding_box()
    assert toggle_box is not None
    assert toggle_box["width"] >= MIN_TOUCH_TARGET, (
        f"calendar toggle width {toggle_box['width']} too small"
    )
    assert toggle_box["height"] >= MIN_TOUCH_TARGET, (
        f"calendar toggle height {toggle_box['height']} too small"
    )

    toggle.tap()
    for hook in ("[data-date-range-prev]", "[data-date-range-next]"):
        button = page.locator(hook).first
        expect(button).to_be_visible()
        box = button.bounding_box()
        assert box is not None
        assert box["width"] >= MIN_TOUCH_TARGET, (
            f"{hook} width {box['width']} too small"
        )
        assert box["height"] >= MIN_TOUCH_TARGET, (
            f"{hook} height {box['height']} too small"
        )


def test_datetime_field_controls_meet_min_touch_target(touch_page: Page, live_server):
    """The session form's datetime fields carry two glyph-only controls each: the
    calendar toggle and the copy-to-the-other-timestamp arrow. The arrow is a
    text glyph, so padding alone gave it a 17.6px-wide hit area (#511) — the same
    failure the ‹/› nav buttons had. Both are sized boxes now, and this covers
    the add-session page, which no touch-target test reached before."""
    page = touch_page
    page.goto(f"{live_server.url}{reverse('games:add_session')}")

    for field_name in ("timestamp_start", "timestamp_end"):
        field = f'date-time-field[field-name="{field_name}"]'
        for hook in ("[data-date-picker-calendar-toggle]", "[data-date-time-copy]"):
            button = page.locator(f"{field} {hook}")
            expect(button).to_be_visible()
            box = button.bounding_box()
            assert box is not None
            assert box["width"] >= MIN_TOUCH_TARGET, (
                f"{field_name} {hook} width {box['width']} too small"
            )
            assert box["height"] >= MIN_TOUCH_TARGET, (
                f"{field_name} {hook} height {box['height']} too small"
            )
