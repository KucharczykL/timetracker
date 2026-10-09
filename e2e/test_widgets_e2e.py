"""Widget scripts and their onReady() lifecycle.

These run a real Chromium via pytest-playwright against pytest-django's
``live_server``. All JavaScript under test is served locally from
``games/static/js/`` (Alpine is vendored and the widget files are compiled
to ``dist/``), so no network access is needed beyond the live server itself.
"""

import re

import pytest
from devices import create_device
from django.urls import reverse
from graphs import default_graph
from playwright.sync_api import Page, expect

from e2e.helpers import log_in, open_facet, pick_choice
from games.models import Device, Game, Platform


@pytest.fixture
def touch_page(live_server, browser, e2e_user):
    """A logged-in page in a touch-enabled context (so locator.tap() works and
    pointer events report pointerType "touch"). Uses a desktop-width viewport."""
    context = browser.new_context(has_touch=True)
    page = context.new_page()
    log_in(page, live_server)
    yield page
    context.close()


def open_status_facet(page: Page) -> None:
    """Open the games quick bar's Status facet dropdown."""
    page.click("#quick-status-dropdownLink")
    expect(page.locator("#quick-status-dropdown")).to_be_visible()


def status_filter_widget(page: Page):
    return page.locator('quick-filter-bar search-select[name="status"]')


def test_search_select_initializes_on_page_load(authenticated_page: Page, live_server):
    """A FilterSelect opens after the first load."""
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
    widget.locator('[data-search-select-option][data-label="Completed"]').click()

    pill = widget.locator("[data-search-select-pills] [data-pill]")
    expect(pill).to_have_count(1)
    expect(pill).to_contain_text("Completed")


def test_number_filter_between_reveals_second_input(
    authenticated_page: Page, live_server
):
    """Selecting the BETWEEN modifier on a NumberFilter reveals its second
    (value2) input — proof that setupNumberFilters wired the modifier radios on
    the initial page load."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    open_facet(page, "year_released")

    value2 = page.locator('input[name="quick-year_released-value2"]')
    expect(value2).to_be_hidden()

    pick_choice(page, "quick-year_released-modifier", "BETWEEN")
    expect(value2).to_be_visible()


def test_widgets_initialize_inside_inserted_content(
    authenticated_page: Page, live_server
):
    """Custom elements inserted after load wire themselves."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    page.evaluate(
        """async () => {
            const response = await fetch(window.location.pathname);
            const fetched = new DOMParser().parseFromString(
                await response.text(), "text/html"
            );
            document.querySelector("quick-filter-bar").replaceWith(
                document.importNode(fetched.querySelector("quick-filter-bar"), true)
            );
        }"""
    )
    # Opening a facet dropdown proves the swap happened and the fresh DOM
    # (re-upgraded custom elements) is in place.
    open_status_facet(page)

    widget = status_filter_widget(page)
    expect(widget.locator("[data-search-select-options]")).to_be_visible()

    open_facet(page, "year_released")
    value2 = page.locator('input[name="quick-year_released-value2"]')
    expect(value2).to_be_hidden()
    pick_choice(page, "quick-year_released-modifier", "BETWEEN")
    expect(value2).to_be_visible()


def _open_add_to_library(page: Page, live_server, library) -> None:
    """A picker beside native inputs."""
    game = default_graph(Game(library=library, name="Tunic"), library).game
    page.goto(f"{live_server.url}{reverse('games:add_to_library')}?game={game.pk}")


def test_searchselect_border_matches_native_input(
    authenticated_page: Page, live_server, e2e_library
):
    """Field box borders like a native input."""
    page = authenticated_page
    _open_add_to_library(page, live_server, e2e_library)
    amount = page.locator("#id_amount")  # a native input
    wrapper = page.locator("search-select[name='release'] [data-search-select-box]")
    search_input = page.locator("#id_release")
    border = "el => getComputedStyle(el).borderColor"

    rest = amount.evaluate(border)
    assert wrapper.evaluate(border) == rest  # same border at rest

    search_input.focus()
    focused_wrapper = wrapper.evaluate(border)
    amount.focus()
    focused_input = amount.evaluate(border)
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
    create_device(name="Nintendo Switch", type=Device.HANDHELD, library=e2e_library)
    page.goto(f"{live_server.url}{reverse('games:add_session')}")

    wrapper = page.locator("search-select[name='device']")
    field_box = wrapper.locator("[data-search-select-box]")
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
    assert field_box.evaluate(border_style) == "solid"
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
    assert field_box.evaluate(border_style) == "dashed"
    assert box.evaluate(font_style) == "italic"
    expect(pencil).to_be_visible()
    # The assistive channel: status text + describedby wiring.
    expect(status).to_have_text("No option selected")
    assert box.get_attribute("aria-describedby") == status.get_attribute("id")

    # Focused again, the cues yield to the focus ring (user is mid-pick).
    box.click()
    assert field_box.evaluate(border_style) == "solid"
    assert box.evaluate(font_style) == "normal"
    expect(pencil).to_be_hidden()

    # An explicit pick clears the cue and the announcement.
    option.click()
    expect(hidden).to_have_count(1)
    assert wrapper.get_attribute("data-uncommitted") is None
    expect(status).to_have_text("")
    page.locator("#id_note").click()
    assert field_box.evaluate(border_style) == "solid"


def test_add_game_syncs_sort_name_from_name(authenticated_page: Page, live_server):
    """Typing into Name live-fills Sort name (sync bound to the add form, not
    the navbar logout form which is the first <form> on the page)."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_game')}")
    page.locator("#id_name").click()
    page.locator("#id_name").type("Halo")
    expect(page.locator("#id_sort_name")).to_have_value("Halo")


def test_a_disabled_search_select_looks_like_a_disabled_input(
    authenticated_page: Page, live_server, e2e_library
):
    """Both fade over the same surface."""
    page = authenticated_page
    _open_add_to_library(page, live_server, e2e_library)
    page.wait_for_function("() => !!customElements.get('search-select')")
    search_input = page.locator("#id_release")
    wrapper = page.locator("search-select[name='release'] [data-search-select-box]")
    amount = page.locator("#id_amount")
    opacity = "el => getComputedStyle(el).opacity"
    bg = "el => getComputedStyle(el).backgroundColor"

    for control in (search_input, amount):
        control.evaluate("el => { el.disabled = true; }")
    assert wrapper.evaluate(opacity) == "0.5"
    assert amount.evaluate(opacity) == "0.5"
    assert wrapper.evaluate(bg) == amount.evaluate(bg)
    # The inner input stays transparent (no nested box) with the same not-allowed
    # cursor (no flicker across the widget).
    assert search_input.evaluate(bg) == "rgba(0, 0, 0, 0)"
    assert search_input.evaluate("el => getComputedStyle(el).cursor") == "not-allowed"

    for control in (search_input, amount):
        control.evaluate("el => { el.disabled = false; }")
    assert wrapper.evaluate(opacity) == "1"
    assert amount.evaluate(opacity) == "1"


def test_label_click_focuses_search_select(
    authenticated_page: Page, live_server, e2e_library
):
    """Clicking a <label for="id_X"> on a SearchSelect field must focus the
    search input — confirmed now that id is on the real <input> control."""
    page = authenticated_page
    _open_add_to_library(page, live_server, e2e_library)
    label = page.locator("label[for='id_release']")
    search_input = page.locator("#id_release")
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


def test_add_game_submit_and_add_to_library_redirects(
    authenticated_page: Page, live_server
):
    """Saves, then opens Add to library."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_game')}")
    page.fill("#id_name", "E2E Library Game")
    page.click('button[name="submit_and_add_to_library"]')
    page.wait_for_url(f"{live_server.url}/tracker/library/add?game=*")
    expect(page).to_have_title(re.compile("Add to library"))
    expect(page.locator('[data-field-row="game"] dd')).to_contain_text(
        "E2E Library Game"
    )


# ── Sortable column headers (issue #73) ──────────────────────────────────────
# The <sort-header> custom element augments header links: plain click navigates
# the link (single-column sort, server-computed); shift-click navigates to the
# pre-baked multi-column target. connectedCallback wires this on parse and on
# any inserted fragment.


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


def test_quick_bar_preset_pick_navigates_to_filtered_list(
    authenticated_page: Page, live_server, e2e_library
):
    """Picking a preset in the quick bar's Presets panel navigates to the
    list URL carrying ?filter= — the bar consumer's pick semantics."""
    from games.models import FilterPreset

    platform = Platform.objects.create(name="PC", icon="steam", library=e2e_library)
    Game.objects.create(name="Halo", platform=platform, library=e2e_library)
    Game.objects.create(name="Doom", platform=platform, library=e2e_library)
    stored_filter = {"name": {"modifier": "INCLUDES", "value": "halo"}}
    FilterPreset.objects.create(
        library=e2e_library, name="HaloOnly", mode="games", object_filter=stored_filter
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    picker = page.locator("quick-filter-bar drop-down:has(preset-panel)")
    picker.locator("[data-toggle]").click()
    row = picker.locator("[data-search-select-option]").filter(has_text="HaloOnly")
    expect(row).to_be_visible(timeout=5_000)

    with page.expect_navigation():
        row.click()

    assert "?filter=" in page.url
    # The navigated list is actually narrowed by the preset's filter.
    expect(page.locator("table")).to_contain_text("Halo")
    expect(page.locator("table")).not_to_contain_text("Doom")
