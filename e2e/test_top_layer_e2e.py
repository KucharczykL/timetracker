"""Top-layer panels and their one dismissal stack."""

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from playwright.sync_api import Page, expect
from tracked_games import create_tracked_game

from common.components import (
    BottomSheet,
    ButtonDropdown,
    ComboboxDropdown,
    ControlButton,
    DropdownActionItem,
    DropdownSubmenuItem,
    Fragment,
    Popover,
    SearchSelect,
    collect_media,
)
from e2e.helpers import log_in

OPTIONS = [
    {"value": "1", "label": "Hades", "data": {}},
    {"value": "2", "label": "Tunic", "data": {}},
]


def harness_view(request):
    acts = ButtonDropdown(
        label="Acts",
        items=[
            DropdownActionItem()["First"],
            DropdownActionItem()["Second"],
            DropdownActionItem()["Third"],
            DropdownSubmenuItem(
                "More", items=[DropdownActionItem()["Deep"]], id="more"
            ),
        ],
        id="acts",
    )
    facet = ComboboxDropdown(
        label="Game",
        content=SearchSelect(name="game", options=OPTIONS),
        id="facet",
    )
    hint = Popover("Why it is so", wrapped_content="hint")
    sheet = BottomSheet(
        trigger_element=ControlButton()["Sections"].as_element(),
        title="Sections",
        children=ButtonDropdown(
            label="Inside", items=[DropdownActionItem()["Nested"]], id="inside"
        ),
        id="sheet",
    )
    content = Fragment(acts, facet, hint, sheet)
    scripts = "".join(
        f'<script type="module" src="/static/js/{script}"></script>'
        for script in collect_media(content).js
    )
    return HttpResponse(f"""<!DOCTYPE html><html><head>
    <link rel="icon" href="data:,">
    <link rel="stylesheet" href="/static/base.css">
    {scripts}
    </head><body style="padding:24px">
    <!-- A transformed, clipping ancestor traps no panel. -->
    <div id="clipped" style="transform:translateZ(0);overflow:hidden;
        height:48px;width:320px;margin:120px 0 0 240px">{acts}</div>
    <div style="margin-top:24px">{facet}</div>
    <div style="margin-top:24px">{hint}</div>
    <div style="margin-top:24px">{sheet}</div>
    </body></html>""")


urlpatterns = [path("top-layer/", harness_view)]

harness = pytest.mark.django_db
on_harness = override_settings(ROOT_URLCONF="e2e.test_top_layer_e2e")


def _open_acts(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}/top-layer/")
    page.locator("#actsLink").click()
    expect(page.locator("#acts")).to_be_visible()


@harness
@on_harness
def test_a_panel_escapes_a_transformed_clipping_ancestor(live_server, page: Page):
    _open_acts(page, live_server)
    toggle = page.locator("#actsLink").bounding_box()
    panel = page.locator("#acts").bounding_box()
    assert toggle is not None and panel is not None
    assert abs(panel["y"] - (toggle["y"] + toggle["height"])) <= 1
    assert abs(panel["x"] - toggle["x"]) <= 1
    # Taller than the clip; rows hit-testable.
    assert panel["height"] > 48
    third = page.get_by_role("menuitem", name="Third").bounding_box()
    assert third is not None
    hit = page.evaluate(
        "([x, y]) => document.elementFromPoint(x, y)?.textContent?.trim()",
        [third["x"] + 8, third["y"] + third["height"] / 2],
    )
    assert hit == "Third"
    # The UA's popover look stays reset.
    look = page.locator("#acts").evaluate(
        "(panel) => { const style = getComputedStyle(panel);"
        " return [style.backgroundColor, style.marginTop, style.overflow]; }"
    )
    assert look[0] not in ("rgba(0, 0, 0, 0)", "transparent")
    assert look[1] == "0px"
    assert look[2] == "visible"


@harness
@on_harness
def test_a_submenu_aligns_its_first_item_with_its_row(live_server, page: Page):
    _open_acts(page, live_server)
    page.get_by_role("menuitem", name="More").hover()
    deep = page.get_by_role("menuitem", name="Deep")
    expect(deep).to_be_visible()
    row = page.get_by_role("menuitem", name="More").bounding_box()
    first = deep.bounding_box()
    assert row is not None and first is not None
    assert abs(first["y"] - row["y"]) <= 1


@harness
@on_harness
def test_a_dark_submenu_sits_flush_beside_its_panel(live_server, page: Page):
    """The panel's own blur traps no flyout."""
    page.emulate_media(color_scheme="dark")
    page.goto(f"{live_server.url}/top-layer/")
    page.evaluate("() => document.documentElement.classList.add('dark')")
    page.locator("#actsLink").click()
    page.get_by_role("menuitem", name="More").hover()
    expect(page.get_by_role("menuitem", name="Deep")).to_be_visible()
    parent = page.locator("#acts").bounding_box()
    flyout = page.locator("#more").bounding_box()
    row = page.get_by_role("menuitem", name="More").bounding_box()
    deep = page.get_by_role("menuitem", name="Deep").bounding_box()
    assert parent and flyout and row and deep
    assert abs(flyout["x"] - (parent["x"] + parent["width"] + 1)) <= 1
    assert abs(deep["y"] - row["y"]) <= 1


@harness
@on_harness
def test_a_second_click_on_the_toggle_closes_the_menu(live_server, page: Page):
    _open_acts(page, live_server)
    page.locator("#actsLink").click()
    expect(page.locator("#acts")).to_be_hidden()


@harness
@on_harness
def test_escape_closes_a_menu_inside_a_sheet_before_the_sheet(live_server, page: Page):
    page.goto(f"{live_server.url}/top-layer/")
    page.locator("#sheetLink").click()
    dialog = page.locator("dialog[data-bottom-sheet]")
    expect(dialog).to_be_visible()
    page.locator("#insideLink").click()
    expect(page.locator("#inside")).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.locator("#inside")).to_be_hidden()
    assert dialog.evaluate("(element) => element.open")

    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()


@harness
@on_harness
def test_escape_closes_a_tooltip_before_the_menu_under_it(live_server, page: Page):
    _open_acts(page, live_server)
    page.locator("pop-over button").focus()
    tooltip = page.locator("[data-pop-over-panel]")
    expect(tooltip).to_be_visible()

    page.keyboard.press("Escape")
    expect(tooltip).to_be_hidden()
    expect(page.locator("#acts")).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.locator("#acts")).to_be_hidden()


@harness
@on_harness
def test_escape_closes_a_combobox_before_its_facet(live_server, page: Page):
    page.goto(f"{live_server.url}/top-layer/")
    page.locator("#facetLink").click()
    facet = page.locator("#facet")
    expect(facet).to_be_visible()
    page.locator("search-select[name=game] [data-search-select-search]").focus()
    listbox = page.locator("search-select[name=game] [data-search-select-panel]")
    expect(listbox).to_be_visible()

    page.keyboard.press("Escape")
    expect(listbox).to_be_hidden()
    expect(facet).to_be_visible()

    page.keyboard.press("Escape")
    expect(facet).to_be_hidden()


@harness
@on_harness
def test_a_cancelled_touch_keeps_the_menu_open(live_server, page: Page):
    """A scrolling touch is cancelled, not pressed."""
    _open_acts(page, live_server)
    page.evaluate(
        """() => {
            const init = {bubbles: true, composed: true, isPrimary: true,
                button: 0, pointerId: 7, pointerType: "touch"};
            document.body.dispatchEvent(new PointerEvent("pointerdown", init));
            document.body.dispatchEvent(new PointerEvent("pointercancel", init));
            document.body.dispatchEvent(new PointerEvent("pointerup", init));
        }"""
    )
    expect(page.locator("#acts")).to_be_visible()

    page.mouse.click(5, 5)
    expect(page.locator("#acts")).to_be_hidden()


def test_escape_clears_a_selection_under_the_quick_bar(
    live_server, page: Page, e2e_library
):
    """Facet takes first Escape; selection the next."""
    create_tracked_game(e2e_library, "Outer Wilds")
    log_in(page, live_server)
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    box = page.locator("tbody [data-selection-checkbox]").first
    box.click()
    expect(box).to_be_checked()
    page.locator("#quick-status-dropdownLink").click()
    facet = page.locator("#quick-status-dropdown")
    expect(facet).to_be_visible()

    page.keyboard.press("Escape")
    expect(facet).to_be_hidden()
    expect(box).to_be_checked()

    # The table hears keys from inside it.
    box.focus()
    page.keyboard.press("Escape")
    expect(box).not_to_be_checked()
