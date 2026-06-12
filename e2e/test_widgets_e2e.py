"""Browser tests for widget JavaScript (search_select.js, range_slider.js,
add_purchase.js) and their onSwap() initialization lifecycle.

These run a real Chromium via pytest-playwright against pytest-django's
``live_server``. All JavaScript under test is served locally from
``games/static/js/`` (htmx, Alpine, Flowbite and the widget files are
vendored), so no network access is needed beyond the live server itself.

Browser binaries must be installed once: ``uv run playwright install chromium``.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('input[type="submit"]')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def open_filter_bar(page: Page) -> None:
    page.click("#filter-bar button:has-text('Filters')")
    expect(page.locator("#filter-bar-body")).to_be_visible()


def status_filter_widget(page: Page):
    return page.locator('[data-search-select][data-name="status"]')


def test_search_select_initializes_on_page_load(authenticated_page: Page, live_server):
    """Clicking into a FilterSelect search box opens its options panel —
    proof that onSwap ran the widget initializer on the initial page load."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    open_filter_bar(page)

    widget = status_filter_widget(page)
    widget.locator("[data-search-select-search]").click()

    options_panel = widget.locator("[data-search-select-options]")
    expect(options_panel).to_be_visible()
    # The pinned "(Any)" modifier pseudo-option is rendered server-side and
    # only becomes interactable through the initialized panel.
    expect(
        options_panel.locator("[data-search-select-modifier-option]").first
    ).to_have_text("(Any)")


def test_search_select_adds_include_pill(authenticated_page: Page, live_server):
    """Clicking an enum option row adds an include pill (full widget wiring)."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    open_filter_bar(page)

    widget = status_filter_widget(page)
    widget.locator("[data-search-select-search]").click()
    widget.locator('[data-search-select-option][data-label="Finished"]').click()

    pill = widget.locator("[data-search-select-pills] [data-pill]")
    expect(pill).to_have_count(1)
    expect(pill).to_contain_text("Finished")


def test_range_slider_mode_toggle_fires_exactly_once(
    authenticated_page: Page, live_server
):
    """One click on the mode toggle flips the slider from range to point mode
    exactly once. Double-bound listeners (the old force-re-init bug) would
    flip it twice, leaving data-mode unchanged."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    open_filter_bar(page)

    block = page.locator(".range-slider-block").first
    slider = block.locator(".range-slider")
    expect(slider).to_have_attribute("data-mode", "range")

    block.locator(".range-mode-toggle").click()
    expect(slider).to_have_attribute("data-mode", "point")


def test_widgets_initialize_inside_htmx_swapped_content(
    authenticated_page: Page, live_server
):
    """Widgets arriving via an htmx swap initialize without a page load.

    The filter bar is re-fetched and swapped in with htmx.ajax — fresh,
    uninitialized DOM. The swapped-in FilterSelect must open its panel and the
    swapped-in slider must toggle exactly once, proving the htmx:load half of
    onSwap and the once-per-element guard."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    page.evaluate(
        "htmx.ajax('GET', window.location.pathname, "
        "{target: '#filter-bar', select: '#filter-bar', swap: 'outerHTML'})"
    )
    # The swapped-in bar arrives collapsed again; opening it proves the swap
    # happened and the fresh DOM is in place.
    open_filter_bar(page)

    widget = status_filter_widget(page)
    widget.locator("[data-search-select-search]").click()
    expect(widget.locator("[data-search-select-options]")).to_be_visible()

    block = page.locator(".range-slider-block").first
    slider = block.locator(".range-slider")
    expect(slider).to_have_attribute("data-mode", "range")
    block.locator(".range-mode-toggle").click()
    expect(slider).to_have_attribute("data-mode", "point")


def test_add_purchase_type_toggles_disabled_fields(
    authenticated_page: Page, live_server
):
    """add_purchase.js disables name/related-purchase while type is "game"
    and re-enables them for other types."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")

    name_input = page.locator("#id_name")
    expect(name_input).to_be_disabled()

    page.select_option("#id_type", "dlc")
    expect(name_input).to_be_enabled()

    page.select_option("#id_type", "game")
    expect(name_input).to_be_disabled()
