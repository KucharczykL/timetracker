"""Browser tests for widget JavaScript (search_select.js, quick-filter-bar.js,
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

from games.models import Device, Game, Platform


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
def touch_page(live_server, browser, e2e_user):
    """A logged-in page in a touch-enabled context (so locator.tap() works and
    pointer events report pointerType "touch"). Uses a desktop-width viewport."""
    context = browser.new_context(has_touch=True)
    page = context.new_page()
    _login(page, live_server)
    yield page
    context.close()


def open_status_facet(page: Page) -> None:
    """Open the games quick bar's Status facet dropdown."""
    page.click("#quick-status-dropdownLink")
    expect(page.locator("#quick-status-dropdown")).to_be_visible()


def status_filter_widget(page: Page):
    return page.locator('quick-filter-bar search-select[name="status"]')


def test_search_select_initializes_on_page_load(authenticated_page: Page, live_server):
    """Clicking into a FilterSelect search box opens its options panel —
    proof that onSwap ran the widget initializer on the initial page load."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    open_status_facet(page)

    widget = status_filter_widget(page)
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
    open_status_facet(page)

    widget = status_filter_widget(page)
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
    page.click("#quick-year_released-dropdownLink")

    value2 = page.locator('input[name="quick-year_released-value2"]')
    expect(value2).to_be_hidden()

    page.locator('select[name="quick-year_released-modifier"]').select_option("BETWEEN")
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
        "{target: 'quick-filter-bar', select: 'quick-filter-bar', "
        "swap: 'outerHTML'})"
    )
    # Opening a facet dropdown proves the swap happened and the fresh DOM
    # (re-upgraded custom elements) is in place.
    open_status_facet(page)

    widget = status_filter_widget(page)
    expect(widget.locator("[data-search-select-options]")).to_be_visible()

    page.click("#quick-year_released-dropdownLink")
    value2 = page.locator('input[name="quick-year_released-value2"]')
    expect(value2).to_be_hidden()
    page.locator('select[name="quick-year_released-modifier"]').select_option("BETWEEN")
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


def test_uncommitted_single_select_shows_draft_cue(
    authenticated_page: Page, live_server, e2e_library
):
    """Issue #450: box text with no committed value gets the "draft" cue —
    dashed wrapper border, muted-italic text, pencil glyph — at rest only, plus
    the sr-only status announcement. Re-typing a committed label without
    picking is exactly the trap: the text looks committed but saves NULL."""
    page = authenticated_page
    Device.objects.create(
        name="Nintendo Switch", type=Device.HANDHELD, library=e2e_library
    )
    page.goto(f"{live_server.url}{reverse('games:add_session')}")

    wrapper = page.locator("search-select[name='device']")
    box = page.locator("#id_device")
    pencil = wrapper.locator("[data-search-select-marker]")
    status = wrapper.locator("[data-search-select-status]")
    hidden = wrapper.locator('[data-search-select-pills] input[type="hidden"]')
    border_style = "el => getComputedStyle(el).borderStyle"
    font_style = "el => getComputedStyle(el).fontStyle"

    # Commit a pick, then rest: no cue anywhere.
    box.click()
    option = wrapper.locator("[data-search-select-option]", has_text="Nintendo Switch")
    option.click()
    committed_label = box.input_value()
    page.locator("#id_note").click()  # blur the combobox
    expect(hidden).to_have_count(1)
    assert wrapper.get_attribute("data-uncommitted") is None
    assert wrapper.evaluate(border_style) == "solid"
    assert box.evaluate(font_style) == "normal"
    expect(pencil).to_be_hidden()
    expect(status).to_have_text("")

    # Re-type the committed label without picking: the #450 trap. Focus selects
    # the label whole, so typing replaces it; the first keystroke drops the
    # committed value.
    box.click()
    box.type(committed_label)
    page.locator("#id_note").click()
    expect(wrapper).to_have_attribute("data-uncommitted", "")
    expect(hidden).to_have_count(0)
    expect(box).to_have_value(committed_label)  # text still masquerades
    assert wrapper.evaluate(border_style) == "dashed"
    assert box.evaluate(font_style) == "italic"
    expect(pencil).to_be_visible()
    # The assistive channel: status text + describedby wiring.
    expect(status).to_have_text("No option selected")
    assert box.get_attribute("aria-describedby") == status.get_attribute("id")

    # Focused again, the cues yield to the focus ring (user is mid-pick).
    box.click()
    assert wrapper.evaluate(border_style) == "solid"
    assert box.evaluate(font_style) == "normal"
    expect(pencil).to_be_hidden()

    # An explicit pick clears the cue and the announcement.
    option.click()
    expect(hidden).to_have_count(1)
    assert wrapper.get_attribute("data-uncommitted") is None
    expect(status).to_have_text("")
    page.locator("#id_note").click()
    assert wrapper.evaluate(border_style) == "solid"


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


# ── Sortable column headers (issue #73) ──────────────────────────────────────
# The <sort-header> custom element augments header links: plain click navigates
# the link (single-column sort, server-computed); shift-click navigates to the
# pre-baked multi-column target. connectedCallback wires this on parse and on
# any htmx-swapped fragment.


def _open_games_list(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('games:list_games')}")


def test_sort_header_plain_click_toggles_direction(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    _open_games_list(page, live_server)

    # Inactive column → ascending.
    page.get_by_role("link", name="Name", exact=True).click()
    expect(page).to_have_url(re.compile(r"sort=name(?:&|$)"))

    # Sole-active ascending → flips to descending.
    page.get_by_role("link", name="Name", exact=True).click()
    expect(page).to_have_url(re.compile(r"sort=-name(?:&|$)"))


def test_sort_header_shift_click_appends_column(authenticated_page: Page, live_server):
    page = authenticated_page
    _open_games_list(page, live_server)

    page.get_by_role("link", name="Name", exact=True).click()
    expect(page).to_have_url(re.compile(r"sort=name(?:&|$)"))

    # Shift-click a second column appends it (",": "%2C" once urlencoded).
    page.get_by_role("link", name="Year", exact=True).click(modifiers=["Shift"])
    expect(page).to_have_url(re.compile(r"sort=name(?:%2C|,)year"))


def test_sort_header_shift_click_removes_descending_column(
    authenticated_page: Page, live_server
):
    page = authenticated_page
    _open_games_list(page, live_server)

    page.get_by_role("link", name="Name", exact=True).click()  # name asc
    page.get_by_role("link", name="Name", exact=True).click()  # -name desc (sole)

    # Shift-clicking a descending column drops it; with nothing left the sort
    # param disappears and the view's default order applies.
    page.get_by_role("link", name="Name", exact=True).click(modifiers=["Shift"])
    expect(page).not_to_have_url(re.compile(r"sort="))


def test_add_purchase_game_selection_autofills_platform(
    authenticated_page: Page, live_server, e2e_library
):
    """Selecting a game in the Games SearchSelect auto-fills the Platform
    SearchSelect with the game's platform: the visible box shows the platform
    *label* and the committed hidden input carries the id. Guards issue #259,
    where the raw platform id was written into the visible search box (and no
    hidden value was committed at all)."""
    platform = Platform.objects.create(name="Steam", library=e2e_library)
    Game.objects.create(
        name="Crosscode", sort_name="Crosscode", platform=platform, library=e2e_library
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")

    games_widget = page.locator('search-select[name="games"]')
    games_widget.locator("[data-search-select-search]").click()
    games_widget.locator("[data-search-select-search]").type("Cross")
    games_widget.locator("[data-search-select-option][data-value]").first.click()

    expect(page.locator("#id_platform")).to_have_value("Steam")
    platform_widget = page.locator('search-select[name="platform"]')
    expect(
        platform_widget.locator('[data-search-select-pills] input[type="hidden"]')
    ).to_have_value(str(platform.id))

    # Removing the game fires search-select:change with last=null; the handler
    # must leave the committed platform untouched (and not throw, which would
    # also kill the price-mode toggle living in the same listener).
    games_widget.locator("[data-pill] [data-pill-remove]").click()
    expect(games_widget.locator("[data-pill]")).to_have_count(0)
    expect(page.locator("#id_platform")).to_have_value("Steam")
    expect(
        platform_widget.locator('[data-search-select-pills] input[type="hidden"]')
    ).to_have_value(str(platform.id))


def _pick_game(page: Page, widget_name: str, query: str) -> None:
    # Click the matching row, not `.first`: the panel keeps a currently
    # selected value's row at the top even when the query filters it out.
    widget = page.locator(f'search-select[name="{widget_name}"]')
    widget.locator("[data-search-select-search]").click()
    widget.locator("[data-search-select-search]").type(query)
    widget.locator("[data-search-select-option][data-value]").filter(
        has_text=query
    ).first.click()


def test_add_purchase_related_game_autofills_from_games_selection(
    authenticated_page: Page, live_server, e2e_library
):
    """For add-on types (DLC/Season Pass/Battle Pass) Related game auto-fills
    from the Games selection — re-picking the base game was pure double-entry.
    The auto-fill follows the games selection while the field is empty or holds
    a previous auto-fill, is dropped when the type returns to plain "game"
    (so no stale hidden input submits), and never overwrites a user's own pick."""
    platform = Platform.objects.create(name="Steam", library=e2e_library)
    base = Game.objects.create(
        name="Vampire Survivors",
        sort_name="Vampire Survivors",
        platform=platform,
        library=e2e_library,
    )
    other = Game.objects.create(
        name="Brotato", sort_name="Brotato", platform=platform, library=e2e_library
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")

    related_search = page.locator("#id_related_game")
    related_hidden = page.locator(
        'search-select[name="related_game"] '
        '[data-search-select-pills] input[type="hidden"]'
    )

    # Type "game" (the default): selecting a game must not fill Related game.
    _pick_game(page, "games", "Vampire")
    expect(related_hidden).to_have_count(0)

    # Switching to an add-on type anchors Related game to the selected game:
    # the visible box shows the pill's label (game + platform, the same label a
    # manual pick would commit), the hidden input carries the id.
    page.select_option("#id_type", "dlc")
    expect(related_search).to_have_value("Vampire Survivors (Steam)")
    expect(related_hidden).to_have_value(str(base.id))

    # While the value is an auto-fill it follows the games selection.
    games_widget = page.locator('search-select[name="games"]')
    games_widget.locator("[data-pill] [data-pill-remove]").click()
    expect(related_hidden).to_have_count(0)
    _pick_game(page, "games", "Brotato")
    expect(related_search).to_have_value("Brotato (Steam)")
    expect(related_hidden).to_have_value(str(other.id))

    # Back to plain "game": the auto-fill is dropped, not left to submit.
    page.select_option("#id_type", "game")
    expect(related_hidden).to_have_count(0)

    # A value the user picked themselves is never overwritten by the auto-fill.
    page.select_option("#id_type", "season_pass")
    _pick_game(page, "related_game", "Vampire")
    expect(related_hidden).to_have_value(str(base.id))
    games_widget.locator("[data-pill] [data-pill-remove]").click()
    _pick_game(page, "games", "Brotato")
    expect(related_search).to_have_value("Vampire Survivors (Steam)")
    expect(related_hidden).to_have_value(str(base.id))


def test_add_purchase_related_game_edit_clears_autofill(
    authenticated_page: Page, live_server, e2e_library
):
    """Editing an auto-filled Related game clears its committed value (a value
    is committed only by a pick) and hands the field to the user: the typed
    text stays, and a later Games change must not overwrite it with a fresh
    auto-fill."""
    platform = Platform.objects.create(name="Steam", library=e2e_library)
    base = Game.objects.create(
        name="Vampire Survivors",
        sort_name="Vampire Survivors",
        platform=platform,
        library=e2e_library,
    )
    Game.objects.create(
        name="Brotato", sort_name="Brotato", platform=platform, library=e2e_library
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")

    related_search = page.locator("#id_related_game")
    related_hidden = page.locator(
        'search-select[name="related_game"] '
        '[data-search-select-pills] input[type="hidden"]'
    )

    _pick_game(page, "games", "Vampire")
    page.select_option("#id_type", "dlc")
    expect(related_hidden).to_have_value(str(base.id))

    # The first keystroke clears the auto-filled value; the typed text stays.
    related_search.click()
    related_search.type("Bro")
    expect(related_hidden).to_have_count(0)
    expect(related_search).to_have_value("Bro")

    # Mid-edit the field belongs to the user: a Games change no longer refills it.
    games_widget = page.locator('search-select[name="games"]')
    games_widget.locator("[data-pill] [data-pill-remove]").click()
    _pick_game(page, "games", "Brotato")
    expect(related_search).to_have_value("Bro")
    expect(related_hidden).to_have_count(0)


def test_quick_bar_preset_pick_navigates_to_filtered_list(
    authenticated_page: Page, live_server, e2e_library
):
    """Picking a preset in the quick bar's Load-preset combobox navigates to the
    list URL carrying ?filter= — the bar consumer's pick semantics."""
    from games.models import FilterPreset

    platform = Platform.objects.create(name="PC", icon="pc", library=e2e_library)
    Game.objects.create(name="Halo", platform=platform, library=e2e_library)
    Game.objects.create(name="Doom", platform=platform, library=e2e_library)
    stored_filter = {"name": {"modifier": "INCLUDES", "value": "halo"}}
    FilterPreset.objects.create(
        library=e2e_library, name="HaloOnly", mode="games", object_filter=stored_filter
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    picker = page.locator("quick-filter-bar [data-preset-picker]")
    picker.locator("[data-toggle]").click()
    row = picker.locator("[data-search-select-option]").filter(has_text="HaloOnly")
    expect(row).to_be_visible(timeout=5_000)

    with page.expect_navigation():
        row.click()

    assert "?filter=" in page.url
    # The navigated list is actually narrowed by the preset's filter.
    expect(page.locator("table")).to_contain_text("Halo")
    expect(page.locator("table")).not_to_contain_text("Doom")
