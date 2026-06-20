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
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def open_filter_bar(page: Page) -> None:
    page.click("#filter-bar button:has-text('Filters')")
    expect(page.locator("#filter-bar-body")).to_be_visible()


def status_filter_widget(page: Page):
    return page.locator('search-select[name="status"]')


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

    slider = page.locator("range-slider").first
    expect(slider).to_have_attribute("mode", "range")

    slider.locator(".range-mode-toggle").click()
    expect(slider).to_have_attribute("mode", "point")


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

    slider = page.locator("range-slider").first
    expect(slider).to_have_attribute("mode", "range")
    slider.locator(".range-mode-toggle").click()
    expect(slider).to_have_attribute("mode", "point")


def test_add_purchase_type_toggles_disabled_fields(
    authenticated_page: Page, live_server
):
    """add_purchase.js disables name/related-game while type is "game"
    and re-enables them for other types."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")

    name_input = page.locator("#id_name")
    expect(name_input).to_be_disabled()
    # The Name field (a plain input) self-styles its disabled state via the
    # INPUT_CLASS disabled: variants — not a global rule. not-allowed is
    # mode-independent, so it holds in light and dark.
    assert name_input.evaluate("el => getComputedStyle(el).cursor") == "not-allowed"

    page.select_option("#id_type", "dlc")
    expect(name_input).to_be_enabled()
    assert name_input.evaluate("el => getComputedStyle(el).cursor") != "not-allowed"

    page.select_option("#id_type", "game")
    expect(name_input).to_be_disabled()


def test_add_purchase_related_game_is_flat_game_search(
    authenticated_page: Page, live_server
):
    """The DLC/Season-Pass anchor is now a flat game search (related_game),
    wired to the games search API and present regardless of which games are
    selected — not the old parent-purchase dropdown filtered by chosen games."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")

    related = page.locator('search-select[name="related_game"]')
    expect(related).to_have_count(1)
    expect(related).to_have_attribute("search-url", "/api/games/search")


def test_searchselect_border_matches_native_input(
    authenticated_page: Page, live_server
):
    """A SearchSelect's wrapper has the same border as a native input, and turns
    brand on focus (via focus-within on the wrapper, since the inner search box
    is what's focused)."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")
    price = page.locator("#id_price")  # always-enabled native input
    # #id_platform is now on the inner <input>; find the wrapper by name attr.
    wrapper = page.locator("search-select[name='platform']")
    search_input = page.locator("#id_platform")
    border = "el => getComputedStyle(el).borderColor"

    rest = price.evaluate(border)
    assert wrapper.evaluate(border) == rest  # same border at rest

    search_input.focus()
    focused_wrapper = wrapper.evaluate(border)
    price.focus()
    focused_input = price.evaluate(border)
    assert focused_wrapper == focused_input  # same brand border on focus
    assert focused_wrapper != rest  # focus actually changes it


def test_add_game_syncs_sort_name_from_name(authenticated_page: Page, live_server):
    """Typing into Name live-fills Sort name (sync bound to the add form, not
    the navbar logout form which is the first <form> on the page)."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_game')}")
    page.locator("#id_name").click()
    page.locator("#id_name").type("Halo")
    expect(page.locator("#id_sort_name")).to_have_value("Halo")


def test_add_purchase_type_game_disables_related_game_search(
    authenticated_page: Page, live_server
):
    """When Type is 'game', the related-game SearchSelect is disabled.
    #id_related_game is the inner search <input> (the real labelable control),
    and the <search-select> wrapper fades via has-[:disabled]:opacity-50."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")
    # #id_related_game is now on the inner <input data-search-select-search>
    search_input = page.locator("#id_related_game")
    # The wrapper has no id; find it by the stable `name` attribute.
    wrapper = page.locator("search-select[name='related_game']")
    name = page.locator("#id_name")
    opacity = "el => getComputedStyle(el).opacity"
    bg = "el => getComputedStyle(el).backgroundColor"

    page.select_option("#id_type", "game")
    expect(search_input).to_be_disabled()
    # A disabled SearchSelect must look identical to a disabled native input:
    # both fade (opacity-50) over the same surface.
    assert wrapper.evaluate(opacity) == "0.5"
    assert name.evaluate(opacity) == "0.5"
    assert wrapper.evaluate(bg) == name.evaluate(bg)
    # The inner input stays transparent (no nested box) with the same not-allowed
    # cursor (no flicker across the widget).
    assert search_input.evaluate(bg) == "rgba(0, 0, 0, 0)"
    assert search_input.evaluate("el => getComputedStyle(el).cursor") == "not-allowed"

    page.select_option("#id_type", "dlc")
    expect(search_input).to_be_enabled()
    # Enabled, both return to full opacity.
    assert wrapper.evaluate(opacity) == "1"
    assert name.evaluate(opacity) == "1"


def test_label_click_focuses_search_select(authenticated_page: Page, live_server):
    """Clicking a <label for="id_X"> on a SearchSelect field must focus the
    search input — confirmed now that id is on the real <input> control."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")
    # related_game is disabled when type is "game" (the default); switch so it
    # is enabled, otherwise clicking the label for a disabled control fails.
    page.select_option("#id_type", "dlc")
    label = page.locator("label[for='id_related_game']")
    search_input = page.locator("#id_related_game")
    label.click()
    expect(search_input).to_be_focused()


def test_add_game_sync_stops_once_sort_name_edited(
    authenticated_page: Page, live_server
):
    """Name → Sort name mirrors live, but stops the moment the user edits Sort
    name directly (the 'UntilChanged' contract). Editing Name afterwards must
    not clobber the user's manual Sort name."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_game')}")
    name = page.locator("#id_name")
    sort = page.locator("#id_sort_name")

    name.click()
    name.type("Halo")
    expect(sort).to_have_value("Halo")  # live mirror before any manual edit

    sort.fill("Custom Sort")  # user takes over the target → sync drops
    expect(sort).to_have_value("Custom Sort")

    name.click()
    name.press("End")
    name.type(" 2")
    expect(name).to_have_value("Halo 2")
    expect(sort).to_have_value("Custom Sort")  # not clobbered
