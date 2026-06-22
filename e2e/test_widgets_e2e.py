"""Browser tests for widget JavaScript (search_select.js, filter-bar.js,
add_purchase.js) and their onSwap() initialization lifecycle.

These run a real Chromium via pytest-playwright against pytest-django's
``live_server``. All JavaScript under test is served locally from
``games/static/js/`` (htmx, Alpine, Flowbite and the widget files are
vendored), so no network access is needed beyond the live server itself.

Browser binaries must be installed once: ``uv run playwright install chromium``.
"""

import re

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    _login(page, live_server)
    return page


@pytest.fixture
def touch_page(live_server, browser, django_user_model):
    """A logged-in page in a touch-enabled context (so locator.tap() works and
    pointer events report pointerType "touch"). Desktop-width viewport so the
    navbar menu is visible (md:block) rather than collapsed in the hamburger."""
    django_user_model.objects.create_user(username="tester", password="secret123")
    context = browser.new_context(has_touch=True)
    page = context.new_page()
    _login(page, live_server)
    yield page
    context.close()


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


def test_number_filter_between_reveals_second_input(
    authenticated_page: Page, live_server
):
    """Selecting the BETWEEN modifier on a NumberFilter reveals its second
    (value2) input — proof that setupNumberFilters wired the modifier radios on
    the initial page load."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    open_filter_bar(page)

    value2 = page.locator('input[name="filter-year-value2"]')
    expect(value2).to_be_hidden()

    page.locator('input[name="filter-year-modifier"][value="BETWEEN"]').check()
    expect(value2).to_be_visible()


def test_widgets_initialize_inside_htmx_swapped_content(
    authenticated_page: Page, live_server
):
    """Widgets arriving via an htmx swap initialize without a page load.

    The filter bar is re-fetched and swapped in with htmx.ajax — fresh,
    uninitialized DOM. The swapped-in FilterSelect must open its panel and the
    swapped-in NumberFilter must reveal its second input on BETWEEN, proving the
    htmx:load half of onSwap and the once-per-element guard."""
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

    value2 = page.locator('input[name="filter-year-value2"]')
    expect(value2).to_be_hidden()
    page.locator('input[name="filter-year-modifier"][value="BETWEEN"]').check()
    expect(value2).to_be_visible()


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


def test_add_game_submit_and_create_session_redirects(
    authenticated_page: Page, live_server
):
    """Submit & Create Session saves the game and redirects to add-session with
    the new game pre-selected in the game SearchSelect."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_game')}")
    page.fill("#id_name", "E2E Session Game")
    page.click('button[name="submit_and_create_session"]')
    page.wait_for_url(f"{live_server.url}/tracker/session/add/for-game/**")
    expect(page.locator("#id_game")).to_have_value(re.compile(r"^E2E Session Game"))


# ── Navbar Dropdown (the generic <dropdown-menu> custom element) ──────────────
# The navbar's single entity "Menu" (with per-entity submenus) is on every page,
# so it exercises the real component including the nested-submenu path.


def test_navbar_menu_opens_and_closes_on_toggle(authenticated_page: Page, live_server):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    toggle = page.locator("#navbarMenuLink")
    menu = page.locator("#navbarMenu")
    expect(menu).to_be_hidden()
    toggle.click()
    expect(menu).to_be_visible()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    toggle.click()
    expect(menu).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")


def test_navbar_menu_closes_on_escape_and_refocuses_toggle(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    toggle = page.locator("#navbarMenuLink")
    menu = page.locator("#navbarMenu")
    toggle.click()
    expect(menu).to_be_visible()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(toggle).to_be_focused()


def test_navbar_submenu_opens_without_closing_parent(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    top_menu = page.locator("#navbarMenu")
    game_submenu = page.locator("#navbarMenuGame")

    page.locator("#navbarMenuLink").click()
    expect(top_menu).to_be_visible()
    page.locator("#navbarMenuGameLink").click()
    # The submenu opens and the parent menu stays open (nesting coordination).
    expect(game_submenu).to_be_visible()
    expect(top_menu).to_be_visible()
    expect(game_submenu.get_by_role("menuitem", name="Add game")).to_be_visible()


def test_navbar_menu_keyboard_navigation(authenticated_page: Page, live_server):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    toggle = page.locator("#navbarMenuLink")
    menu = page.locator("#navbarMenu")
    toggle.focus()
    page.keyboard.press("ArrowDown")  # opens and focuses the first item
    expect(menu).to_be_visible()
    # Roving stays on this menu's own rows, not the submenus' hidden items.
    expect(menu.get_by_role("menuitem", name="Device", exact=True)).to_be_focused()
    page.keyboard.press("End")
    expect(menu.get_by_role("menuitem", name="Session", exact=True)).to_be_focused()
    page.keyboard.press("ArrowRight")  # enter the Session submenu
    expect(page.locator("#navbarMenuSession")).to_be_visible()


def test_navbar_menu_arrow_roving(authenticated_page: Page, live_server):
    """ArrowDown/Up rove the parent items (wrapping) and never auto-open a submenu."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    menu = page.locator("#navbarMenu")

    def focused(name: str):
        return menu.get_by_role("menuitem", name=name, exact=True)

    page.locator("#navbarMenuLink").focus()
    page.keyboard.press("ArrowDown")  # open, Device focused
    expect(focused("Device")).to_be_focused()

    page.keyboard.press("ArrowDown")  # -> Game, must NOT open Device's submenu
    expect(focused("Game")).to_be_focused()
    expect(page.locator("#navbarMenuDevice")).to_be_hidden()
    expect(page.locator("#navbarMenuGame")).to_be_hidden()

    page.keyboard.press("ArrowDown")  # -> Platform
    expect(focused("Platform")).to_be_focused()
    page.keyboard.press("ArrowUp")  # -> Game
    expect(focused("Game")).to_be_focused()
    page.keyboard.press("ArrowUp")  # -> Device (first)
    expect(focused("Device")).to_be_focused()
    page.keyboard.press("ArrowUp")  # wrap -> Session (last)
    expect(focused("Session")).to_be_focused()
    page.keyboard.press("ArrowDown")  # wrap -> Device
    expect(focused("Device")).to_be_focused()


def test_navbar_submenu_keyboard_open_close(authenticated_page: Page, live_server):
    """ArrowRight / Enter open a submenu and focus its first item; ArrowLeft closes
    and returns focus to the parent item."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    menu = page.locator("#navbarMenu")
    game_sub = page.locator("#navbarMenuGame")

    page.locator("#navbarMenuLink").focus()
    page.keyboard.press("ArrowDown")  # Device
    page.keyboard.press("ArrowDown")  # Game
    expect(menu.get_by_role("menuitem", name="Game", exact=True)).to_be_focused()

    page.keyboard.press("ArrowRight")  # open Game submenu, focus its first item
    expect(game_sub).to_be_visible()
    expect(
        game_sub.get_by_role("menuitem", name="Add game", exact=True)
    ).to_be_focused()

    page.keyboard.press("ArrowLeft")  # close, refocus the Game parent item
    expect(game_sub).to_be_hidden()
    expect(page.locator("#navbarMenuGameLink")).to_be_focused()

    page.keyboard.press("Enter")  # Enter also opens + focuses the first item
    expect(game_sub).to_be_visible()
    expect(
        game_sub.get_by_role("menuitem", name="Add game", exact=True)
    ).to_be_focused()


def test_navbar_submenu_alignment_consistent(authenticated_page: Page, live_server):
    """Every entity submenu opens flush at the parent *panel's* right edge (same
    x) and with its first item aligned to the hovered toggle row (y). Three
    regressions guarded: (1) opening a low submenu briefly grew a scrollbar in the
    parent menu, shifting the anchor ~15px and overlapping the parent (positionMenu
    now pins `fixed` before unhide); (2) panel padding inset the toggle from the
    panel edge, so a toggle-anchored flyout opened *inside* the padded panel — x
    now anchors to the parent panel's edge; (3) the flyout's panel-top (not its
    first item) was aligned to the toggle, so the panel's top padding pushed the
    first row ~8px low — y now subtracts the measured first-item inset, so any
    padding/border leaves the row aligned. Use a wide viewport so the flyouts open
    to the right rather than flipping left for want of room."""
    page = authenticated_page
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.locator("#navbarMenuLink").click()
    panel_box = page.locator("#navbarMenu").bounding_box()
    assert panel_box
    panel_right = round(panel_box["x"] + panel_box["width"])

    rows = []
    for entity in ["Device", "Game", "Platform", "PlayEvent", "Purchase", "Session"]:
        toggle = page.locator(f"#navbarMenu{entity}Link")
        submenu = page.locator(f"#navbarMenu{entity}")
        toggle.hover()
        expect(submenu).to_be_visible()
        sub_box = submenu.bounding_box()
        tog_box = toggle.bounding_box()
        first_item_box = submenu.locator("[role=menuitem]").first.bounding_box()
        assert sub_box and tog_box and first_item_box  # visible → boxes present
        rows.append(
            (
                entity,
                round(sub_box["x"]),
                panel_right,
                tog_box["y"],
                first_item_box["y"],
            )
        )

    lefts = [x for _, x, _, _, _ in rows]
    assert max(lefts) - min(lefts) <= 1, f"submenu x drift between items: {rows}"
    for entity, x, panel_right_edge, toggle_top, first_item_top in rows:
        assert abs(x - panel_right_edge) <= 1, (
            f"{entity} not flush to panel edge: x={x} panel_right={panel_right_edge}"
        )
        assert abs(first_item_top - toggle_top) <= 2, (
            f"{entity} first item not aligned to toggle row: "
            f"item_top={first_item_top} toggle_top={toggle_top}"
        )


def test_navbar_submenu_stays_open_on_tap(touch_page: Page, live_server):
    """On touch, tapping a submenu open must keep it open. Regression: hover was
    wired to pointerenter/pointerleave, and pointerleave fires on finger lift, so
    the submenu closed on release (now gated to pointerType === 'mouse')."""
    page = touch_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    top_menu = page.locator("#navbarMenu")
    game_submenu = page.locator("#navbarMenuGame")

    page.locator("#navbarMenuLink").tap()
    expect(top_menu).to_be_visible()
    page.locator("#navbarMenuGameLink").tap()
    expect(game_submenu).to_be_visible()
    expect(top_menu).to_be_visible()  # parent stays open

    # Past SUBMENU_CLOSE_DELAY_MS (150): pre-fix the touch-release pointerleave
    # would have closed the submenu by now.
    page.wait_for_timeout(300)
    expect(game_submenu).to_be_visible()
