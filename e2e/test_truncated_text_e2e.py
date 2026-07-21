"""Real-layout coverage for width-based name clipping and reveal behavior."""

from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page, expect

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
    assert "gradient" in long_clip.evaluate(
        "element => getComputedStyle(element).maskImage"
    )
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


def test_unlinked_sort_name_gets_only_an_overflow_tab_stop(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(name="Long sort", sort_name=LONG_NAME, platform=platform)
    Game.objects.create(name="Short sort", sort_name="Tiny", platform=platform)

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    _wait_for_fonts(page)
    sort_host = _host(page, LONG_NAME)
    sort_clip = sort_host.locator("[data-truncated-clip]")
    sort_panel = sort_host.locator("[data-pop-over-panel]")
    expect(sort_clip).to_have_attribute("tabindex", "0")
    sort_clip.focus()
    expect(sort_panel).to_be_visible()
    page.keyboard.press("Escape")
    expect(sort_panel).to_be_hidden()

    short_sort = _host(page, "Tiny").locator("[data-truncated-clip]")
    assert short_sort.get_attribute("tabindex") is None


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
                < 384
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
    name = "Medium Length Name For A Responsive Resize"
    Game.objects.create(name=name, platform=platform)
    page.set_viewport_size({"width": 240, "height": 844})
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    _wait_for_fonts(page)

    host = _host(page, name)
    button = host.locator("[data-truncated-reveal]")
    panel = host.locator("[data-pop-over-panel]")
    expect(host).to_have_attribute("data-overflowing", "")
    expect(button).to_be_visible()
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
