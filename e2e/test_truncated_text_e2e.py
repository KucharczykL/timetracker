"""Real-layout coverage for width-based name clipping and reveal behavior."""

from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Locator, Page, Route, expect

from games.models import Game, Platform, Purchase, Session

LONG_NAME = (
    "A Deliberately Extraordinary Game Name That Is Much Wider Than Any Practical "
    "Name Column And Therefore Must Be Clipped By Its Rendered Width"
)


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
def touch_page(live_server, browser, django_user_model):
    django_user_model.objects.create_user(username="tester", password="secret123")
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


def _wait_for_fonts(page: Page) -> None:
    page.evaluate("() => document.fonts.ready")


def _host(page: Page, text: str):
    return page.locator("tbody truncated-text", has_text=text).first


def _center_x(locator: Locator) -> float:
    box = locator.bounding_box()
    assert box is not None
    return box["x"] + box["width"] / 2


def test_desktop_overflow_hover_focus_and_short_name_noop(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(name=LONG_NAME, platform=platform)
    Game.objects.create(name="Short", platform=platform)

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    _wait_for_fonts(page)
    long_host = _host(page, LONG_NAME)
    long_clip = long_host.locator("[data-truncated-clip]")
    long_panel = long_host.locator("[data-pop-over-panel]")
    long_button = long_host.locator("[data-truncated-reveal]")

    expect(long_host).to_have_attribute("data-overflowing", "")
    assert long_host.evaluate("element => element.getBoundingClientRect().width") <= 256
    assert "gradient" in long_clip.evaluate(
        "element => getComputedStyle(element).maskImage"
    )
    expect(long_button).to_have_attribute("data-truncated-reveal", "ellipsis")
    expect(long_button).to_be_hidden()
    long_clip.hover()
    expect(long_panel).to_be_visible()
    page.mouse.move(0, 0)
    expect(long_panel).to_be_hidden()

    long_host.locator("a").focus()
    expect(long_panel).to_be_visible()
    page.keyboard.press("Escape")
    expect(long_panel).to_be_hidden()
    expect(long_panel).to_have_attribute("aria-hidden", "true")
    assert long_panel.get_attribute("id") is None
    assert long_host.locator("a").get_attribute("aria-describedby") is None

    short_host = _host(page, "Short")
    short_clip = short_host.locator("[data-truncated-clip]")
    short_panel = short_host.locator("[data-pop-over-panel]")
    assert not short_host.evaluate(
        "element => element.hasAttribute('data-overflowing')"
    )
    assert short_clip.get_attribute("tabindex") is None
    short_clip.hover()
    expect(short_panel).to_be_hidden()
    short_host.locator("a").focus()
    expect(short_panel).to_be_hidden()


def test_different_sort_name_moves_into_the_name_tooltip(touch_page: Page, live_server):
    page = touch_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    display_name = "Short Display Name"
    sort_name = "Display Name, Short"
    Game.objects.create(name=display_name, sort_name=sort_name, platform=platform)
    long_sort_name = "Extraordinary Game Name, A Deliberately"
    Game.objects.create(name=LONG_NAME, sort_name=long_sort_name, platform=platform)
    Game.objects.create(name="Same Name", sort_name="Same Name", platform=platform)

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    _wait_for_fonts(page)

    expect(
        page.get_by_role("columnheader", name="Sort Name", exact=True)
    ).to_have_count(0)

    name_host = _host(page, display_name)
    name_panel = name_host.locator("[data-pop-over-panel]")
    name_button = name_host.locator("[data-truncated-reveal]")
    expect(name_host).to_have_attribute("reveal", "always")
    expect(name_button).to_have_attribute("data-truncated-reveal", "info")
    expect(name_button).to_be_visible()
    assert (
        name_host.locator("[data-truncated-clip]").evaluate(
            "element => getComputedStyle(element).paddingInlineEnd"
        )
        == "24px"
    )
    name_button.tap()
    expect(name_panel).to_be_visible()
    name_arrow = name_panel.locator("[data-pop-over-arrow]")
    assert abs(_center_x(name_button) - _center_x(name_arrow)) < 1
    expect(name_panel.locator('[data-truncated-detail="name"]')).to_be_hidden()
    sort_detail = name_panel.locator('[data-truncated-detail="sort-name"]')
    expect(sort_detail).to_be_visible()
    expect(sort_detail).to_contain_text("Sort name")
    expect(sort_detail).to_contain_text(sort_name)
    panel_id = name_panel.get_attribute("id")
    assert panel_id
    expect(name_host.locator("a")).to_have_attribute("aria-describedby", panel_id)
    page.keyboard.press("Escape")
    expect(name_panel).to_be_hidden()

    long_host = _host(page, LONG_NAME)
    expect(long_host).to_have_attribute("data-overflowing", "")
    long_button = long_host.locator("[data-truncated-reveal]")
    expect(long_button).to_have_attribute("data-truncated-reveal", "info")
    expect(long_button).to_be_visible()
    long_panel = long_host.locator("[data-pop-over-panel]")
    long_name_detail = long_panel.locator('[data-truncated-detail="name"]')
    assert (
        long_name_detail.evaluate("element => getComputedStyle(element).display")
        == "block"
    )
    expect(long_name_detail).to_contain_text("Name")
    expect(long_name_detail).to_contain_text(LONG_NAME)
    expect(long_panel.locator('[data-truncated-detail="sort-name"]')).to_contain_text(
        long_sort_name
    )

    same_host = _host(page, "Same Name")
    same_panel = same_host.locator("[data-pop-over-panel]")
    same_button = same_host.locator("[data-truncated-reveal]")
    expect(same_host).to_have_attribute("reveal", "auto")
    expect(same_button).to_have_attribute("data-truncated-reveal", "ellipsis")
    expect(same_button).to_be_hidden()
    assert (
        same_host.locator("[data-truncated-clip]").evaluate(
            "element => getComputedStyle(element).paddingInlineEnd"
        )
        == "0px"
    )
    expect(same_panel).to_be_hidden()
    expect(same_panel).to_have_attribute("aria-hidden", "true")


def test_table_constraints_hold_at_mobile_and_intermediate_widths(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(name=LONG_NAME, platform=platform)
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    for width in (390, 640, 768):
        page.set_viewport_size({"width": width, "height": 844})
        _wait_for_fonts(page)
        host = _host(page, LONG_NAME)
        wrapper = host.locator(
            "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), "
            "' overflow-x-auto ')][1]"
        )
        dimensions = wrapper.evaluate(
            "element => ({client: element.clientWidth, scroll: element.scrollWidth})"
        )
        assert dimensions["scroll"] <= dimensions["client"]

        row = host.locator("xpath=ancestor::tr[1]")
        action_cell = row.locator("td").last
        expect(action_cell).to_be_visible()
        if width == 390:
            assert (
                host.locator("[data-truncated-clip]").evaluate(
                    "element => element.clientWidth"
                )
                < 256
            )
            host_box = host.bounding_box()
            action_box = action_cell.bounding_box()
            assert host_box is not None and action_box is not None
            assert host_box["x"] + host_box["width"] <= action_box["x"]
        elif width == 768:
            expect(row.locator("td").first).to_be_visible()
        else:
            expect(row.locator("td").first).to_be_hidden()


def test_touch_resize_closes_open_panel_when_text_starts_fitting(
    touch_page: Page, live_server
):
    page = touch_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    name = "Medium Length Name For Resize"
    Game.objects.create(name=name, platform=platform)
    page.set_viewport_size({"width": 240, "height": 844})
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    _wait_for_fonts(page)

    host = _host(page, name)
    button = host.locator("[data-truncated-reveal]")
    panel = host.locator("[data-pop-over-panel]")
    expect(host).to_have_attribute("data-overflowing", "")
    expect(button).to_have_attribute("data-truncated-reveal", "ellipsis")
    expect(button).to_be_visible()
    mask = host.locator("[data-truncated-clip]").evaluate(
        "element => getComputedStyle(element).maskImage"
    )
    assert "48px" in mask and "24px" in mask
    button.tap()
    expect(panel).to_be_visible()

    page.set_viewport_size({"width": 600, "height": 844})
    expect(host).not_to_have_attribute("data-overflowing", "")
    expect(button).to_be_hidden()
    expect(panel).to_be_hidden()


def test_multi_game_purchase_has_one_always_available_informational_tooltip(
    touch_page: Page, live_server
):
    page = touch_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    first = Game.objects.create(name="Bundle Game One", platform=platform)
    second = Game.objects.create(name="Bundle Game Two", platform=platform)
    bundle = Purchase.objects.create(
        name=LONG_NAME,
        date_purchased=date(2026, 1, 1),
        platform=platform,
    )
    bundle.games.set([first, second])

    page.goto(f"{live_server.url}{reverse('games:list_purchases')}")
    host = _host(page, LONG_NAME)
    expect(host).to_have_attribute("reveal", "always")
    expect(host.locator("[data-pop-over-panel]")).to_have_count(1)
    expect(host.locator("pop-over")).to_have_count(0)
    button = host.locator("[data-truncated-reveal]")
    expect(button).to_have_attribute("data-truncated-reveal", "info")
    expect(button).to_be_visible()
    button.tap()
    panel = host.locator("[data-pop-over-panel]")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("Bundle Game One")
    expect(panel).to_contain_text("Bundle Game Two")
    panel_id = panel.get_attribute("id")
    assert panel_id
    expect(host.locator("a")).to_have_attribute("aria-describedby", panel_id)
    expect(button).to_have_attribute("aria-describedby", panel_id)


def test_fallback_font_is_measured_when_webfonts_are_blocked(
    live_server, browser, django_user_model
):
    django_user_model.objects.create_user(
        username="fallback-font", password="secret123"
    )
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(name=LONG_NAME, platform=platform)

    context = browser.new_context(viewport={"width": 1280, "height": 844})
    page = context.new_page()
    blocked_fonts: list[str] = []

    def block_font(route: Route) -> None:
        blocked_fonts.append(route.request.url)
        route.abort()

    page.route("**/*.woff2", block_font)
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "fallback-font")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    host = _host(page, LONG_NAME)
    expect(host).to_have_attribute("data-overflowing", "")
    expect(host.locator("[data-truncated-reveal]")).to_have_attribute(
        "data-truncated-reveal", "ellipsis"
    )
    assert blocked_fonts
    context.close()


def test_navbar_menu_name_is_hover_only_and_has_no_nested_button(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game = Game.objects.create(name=LONG_NAME, platform=platform)
    Session.objects.create(game=game, timestamp_start=timezone.now())

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.locator("#navbar-log-desktopLink").click()
    menu = page.locator("#navbar-log-desktop")
    expect(menu).to_be_visible()
    host = menu.locator("truncated-text")
    expect(host.locator("button")).to_have_count(0)
    host.hover()
    expect(host.locator("[data-pop-over-panel]")).to_be_visible()
