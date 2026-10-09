"""A dropdown panel opens as a bottom sheet below 640 px."""

import json
import re
from urllib.parse import unquote

import pytest
from devices import create_device
from django.urls import reverse
from playwright.sync_api import Locator, Page, ViewportSize, expect

from e2e.helpers import log_in, record_copy, sheet_title, top_sheet
from games.models import Game, Platform
from games.views.filtering import builder_url_for

PHONE = ViewportSize(width=375, height=812)
NARROW = ViewportSize(width=390, height=844)
DESKTOP = ViewportSize(width=1280, height=800)
STARTED = 'drop-down:has(input[name="started"][data-date-picker-hidden])'
SHEET = "dialog[data-dropdown-sheet][open]"
#: A sheet opened inside another sheet (a level), and the first sheet.
LEVEL = "dialog[data-dropdown-sheet][data-sheet-level][open]"
PARENT = "dialog[data-dropdown-sheet][open]:not([data-sheet-level])"
LEAVING = '[data-motion="leaving"]'
FORM_DIALOG = "dialog[data-modal][open]:not([data-dropdown-sheet])"


@pytest.fixture
def errors(page: Page) -> list[str]:
    collected: list[str] = []
    page.on(
        "console",
        lambda message: (
            collected.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: collected.append(str(error)))
    return collected


@pytest.fixture
def phone(live_server, page: Page, e2e_user, errors) -> Page:
    page.set_viewport_size(PHONE)
    log_in(page, live_server)
    return page


def _open_started(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('games:add_playthrough')}")
    page.locator(f"{STARTED} [data-date-picker-calendar-toggle]").click()


def _open_overflow_facet(page: Page, label: str) -> Locator:
    page.locator("[data-quick-overflow-trigger]").click()
    # CSS, not role: a covered level hides it.
    facet = page.locator("drop-down[data-quick-facet]").filter(
        has=page.locator("button", has_text=label)
    )
    facet.get_by_role("button", name=label, exact=True).click()
    return facet


def test_a_date_field_opens_a_sheet_and_a_pick_closes_it(
    phone: Page, live_server, errors
):
    page = phone
    _open_started(page, live_server)
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible()
    expect(sheet.locator("[data-dropdown-sheet-title]")).to_have_text("Started")
    expect(sheet.locator("[data-date-range-calendar]")).to_be_visible()

    sheet.locator("button[data-date]").filter(
        has_text=re.compile(r"^15$")
    ).first.click()
    expect(page.locator(SHEET)).to_have_count(0)
    expect(page.locator(f'{STARTED} input[name="started"]')).to_have_value(
        re.compile(r"-15$")
    )
    expect(
        page.locator(f"{STARTED} [data-date-picker-calendar-toggle]")
    ).to_be_focused()
    expect(page.locator(f"{STARTED} [data-date-range-calendar]")).to_be_hidden()
    assert errors == []


def test_close_leaves_a_datetime_sheet_after_now(phone: Page, live_server, errors):
    page = phone
    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    start = page.locator('drop-down:has(date-time-field[field-name="started_at"])')
    start.locator("[data-date-picker-calendar-toggle]").click()
    sheet = page.locator(SHEET)
    sheet.get_by_role("button", name="Now", exact=True).click()
    expect(sheet).to_be_visible()
    sheet.get_by_role("button", name="Close", exact=True).click()
    expect(page.locator(SHEET)).to_have_count(0)
    expect(start.locator('input[name="started_at"]')).not_to_have_value("")
    assert errors == []


def test_a_desktop_keeps_the_anchored_popup(live_server, page: Page, e2e_user, errors):
    page.set_viewport_size(DESKTOP)
    log_in(page, live_server)
    _open_started(page, live_server)
    calendar = page.locator(f"{STARTED} [data-date-range-calendar]")
    expect(calendar).to_be_visible()
    assert calendar.evaluate("panel => panel.matches(':popover-open')")
    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(calendar.get_by_role("button", name="Close", exact=True)).to_be_hidden()
    assert errors == []


def test_an_open_calendar_survives_a_resize(phone: Page, live_server, errors):
    page = phone
    _open_started(page, live_server)
    calendar = page.locator("[data-date-range-calendar]").first
    expect(page.locator(SHEET)).to_be_visible()

    page.set_viewport_size(DESKTOP)
    expect(page.locator(SHEET)).to_have_count(0)
    expect(calendar).to_be_visible()
    assert calendar.evaluate("panel => panel.matches(':popover-open')")

    page.set_viewport_size(PHONE)
    expect(page.locator(SHEET)).to_be_visible()
    expect(page.locator(SHEET).locator("[data-date-range-calendar]")).to_be_visible()
    assert errors == []


def test_a_date_field_in_a_form_dialog_stacks_a_sheet(phone: Page, live_server, errors):
    page = phone
    page.goto(f"{live_server.url}{reverse('games:list_playthroughs')}")
    page.evaluate(
        """url => {
            const link = document.createElement("a");
            link.href = url;
            link.textContent = "Open add playthrough";
            link.setAttribute("data-form-dialog", "");
            document.body.prepend(link);
        }""",
        reverse("games:add_playthrough"),
    )
    page.get_by_role("link", name="Open add playthrough").click()
    modals = page.locator("dialog[data-modal][open]")
    expect(modals).to_have_count(1)
    # The game picker opens on focus; a press on the title shuts it.
    modals.first.locator("[data-form-dialog-title]").click()

    modals.first.locator(f"{STARTED} [data-date-picker-calendar-toggle]").click()
    expect(modals).to_have_count(2)
    expect(page.locator(SHEET)).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.locator(SHEET)).to_have_count(0)
    expect(modals).to_have_count(1)
    assert errors == []


def test_a_quick_facet_applies_from_its_sheet(phone: Page, live_server, errors):
    page = phone
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    _open_overflow_facet(page, "Timing")
    sheet = top_sheet(page)
    expect(sheet).to_be_visible()
    sheet.locator('[data-search-select-option][data-label="Duration only"]').click()
    with page.expect_navigation():
        sheet.get_by_role("button", name="Apply", exact=True).click()
    assert "duration_only" in page.url
    assert errors == []


def test_escape_leaves_a_sheet_for_its_calendar_button(
    phone: Page, live_server, errors
):
    page = phone
    _open_started(page, live_server)
    expect(page.locator(SHEET)).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(SHEET)).to_have_count(0)
    expect(
        page.locator(f"{STARTED} [data-date-picker-calendar-toggle]")
    ).to_be_focused()
    assert errors == []


def test_a_range_calendar_selects_and_cancels_in_its_sheet(
    phone: Page, live_server, errors
):
    page = phone
    stated = {"purchased": {"value": "", "value2": "", "modifier": "BETWEEN"}}
    page.goto(f"{live_server.url}{builder_url_for('purchases', json.dumps(stated))}")
    picker = page.locator("drop-down:has(> date-range-picker)").first
    toggle = picker.locator("[data-date-range-calendar-toggle]")
    sheet = page.locator(SHEET)

    def day(number: int) -> Locator:
        return (
            sheet.locator("[data-date-range-grid] button[data-date]")
            .filter(has_text=re.compile(rf"^{number}$"))
            .first
        )

    toggle.click()
    expect(sheet).to_be_visible()
    sheet.get_by_role("button", name="Cancel", exact=True).click()
    expect(page.locator(SHEET)).to_have_count(0)

    toggle.click()
    day(10).click()
    day(12).click()
    sheet.get_by_role("button", name="Select", exact=True).click()
    expect(page.locator(SHEET)).to_have_count(0)
    expect(picker.locator('input[data-date-range-hidden="min"]')).to_have_value(
        re.compile(r"-10$")
    )
    expect(picker.locator('input[data-date-range-hidden="max"]')).to_have_value(
        re.compile(r"-12$")
    )
    assert errors == []


def test_a_date_facet_applies_from_its_calendar_footer(
    phone: Page, live_server, errors
):
    page = phone
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    _open_overflow_facet(page, "Day")
    sheet = top_sheet(page)
    expect(sheet).to_be_visible()
    sheet.get_by_role("button", name="Today", exact=True).click()
    expect(sheet.get_by_role("button", name="Apply", exact=True)).to_have_count(1)
    with page.expect_navigation():
        sheet.get_by_role("button", name="Apply", exact=True).click()
    assert '"day"' in unquote(page.url)
    assert errors == []


def test_a_facet_sheet_survives_the_bar_reflowing(phone: Page, live_server, errors):
    page = phone
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    facet = _open_overflow_facet(page, "Timing")
    expect(top_sheet(page)).to_be_visible()
    page.set_viewport_size(ViewportSize(width=560, height=812))
    page.wait_for_timeout(200)
    expect(top_sheet(page)).to_be_visible()
    expect(top_sheet(page).locator("#quick-timing_mode-dropdown")).to_have_count(1)
    expect(facet.locator("#quick-timing_mode-dropdown")).to_have_count(1)
    assert errors == []


@pytest.fixture
def narrow(live_server, page: Page, e2e_user, errors) -> Page:
    """Signed in at a 390 px phone."""
    page.set_viewport_size(NARROW)
    log_in(page, live_server)
    return page


def test_a_row_menu_opens_as_a_sheet_and_focuses_its_first_item(
    narrow: Page, live_server, e2e_library, errors
):
    page = narrow
    create_device(e2e_library, "Deck")
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")

    page.get_by_role("button", name="Deck (Unknown) actions").click()
    sheet = page.locator(SHEET)
    expect(sheet).to_have_count(1)
    expect(sheet.locator("[data-dropdown-sheet-title]")).to_have_text(
        "Deck (Unknown) actions"
    )
    expect(sheet.get_by_role("menuitem").first).to_be_focused()

    # "Edit" navigates; the sheet is gone with the page it opened from.
    with page.expect_navigation():
        sheet.get_by_role("menuitem", name="Edit", exact=True).click()
    expect(page.locator(SHEET)).to_have_count(0)
    assert errors == []


def test_a_submenu_opens_as_a_level_and_an_act_inside_it_closes_every_sheet(
    narrow: Page, live_server, e2e_user, e2e_library, errors
):
    page = narrow
    record_copy(e2e_user, e2e_library, "Tunic")
    page.goto(f"{live_server.url}{reverse('games:list_library')}")

    page.get_by_role("button", name="Tunic (PS5) actions").click()
    parent = page.locator(PARENT)
    expect(parent).to_have_count(1)
    expect(sheet_title(parent)).to_have_text("Tunic (PS5) actions")

    top_sheet(page).get_by_role("menuitem", name="I no longer have it").click()
    level = page.locator(LEVEL)
    expect(level).to_have_count(1)
    expect(level).to_be_visible()
    back = level.locator("[data-sheet-back]")
    expect(back).to_be_visible()
    expect(back).to_have_accessible_name("Back to Tunic (PS5) actions")

    # Escape goes back one level: the parent sheet stays open.
    page.keyboard.press("Escape")
    expect(page.locator(LEVEL)).to_have_count(0)
    expect(page.locator(PARENT)).to_have_count(1)
    expect(page.locator(LEAVING)).to_have_count(0)

    # Reopen the submenu and press an act inside it: every sheet closes.
    top_sheet(page).get_by_role("menuitem", name="I no longer have it").click()
    expect(page.locator(LEVEL)).to_have_count(1)
    with page.expect_navigation():
        page.locator(LEVEL).get_by_role("menuitem", name="Just mark it gone").click()
    expect(page.locator(SHEET)).to_have_count(0)
    expect(page.get_by_text("Marked as no longer yours.")).to_be_visible()
    assert errors == []


def test_a_facet_picker_level_closes_the_whole_chain_and_returns_focus(
    narrow: Page, live_server, errors
):
    page = narrow
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    trigger = page.locator("#quick-name-dropdownLink")
    overflow = page.locator("[data-quick-overflow-trigger]")
    in_overflow = not trigger.is_visible()
    #: The first sheet's opener: the overflow when the facet sits in it.
    opener = overflow if in_overflow else trigger
    opener.click()
    expect(page.locator(PARENT)).to_have_count(1)
    if in_overflow:
        trigger.click()
    panel = page.locator("#quick-name-dropdown")
    expect(panel.locator('input[name="quick-name"]')).to_be_visible()

    modifier = panel.locator('search-select[name="quick-name-modifier"]')
    host = modifier.locator("xpath=ancestor::drop-down[1]")
    face = host.locator(
        ":scope > [data-search-select-face] [data-search-select-face-open]"
    )
    if face.is_visible():
        face.click()
    else:
        modifier.locator("[data-search-select-search]").click()
    level = page.locator(LEVEL).last
    expect(level).to_be_visible()
    expect(modifier.locator("[data-search-select-panel]")).to_be_visible()

    # The level's × closes the whole chain at once.
    level.locator("[data-modal-dismiss]").first.click()
    expect(page.locator(SHEET)).to_have_count(0)
    expect(page.locator(LEAVING)).to_have_count(0)
    expect(opener).to_be_focused()
    # No picker below takes focus and opens again.
    expect(page.locator(SHEET)).to_have_count(0)
    expect(modifier.locator("[data-search-select-panel]")).to_be_hidden()
    assert errors == []


def test_a_form_dialog_link_in_a_sheet_opens_after_the_sheet_leaves(
    narrow: Page, live_server, e2e_user, e2e_library, errors
):
    page = narrow
    platform = Platform.objects.create(library=e2e_library, name="PC", icon="steam")
    game = Game.objects.create(library=e2e_library, name="Test Game", platform=platform)
    page.goto(f"{live_server.url}{game.get_absolute_url()}")

    page.get_by_role("button", name="Playthrough actions").click()
    page.locator(SHEET).get_by_role("menuitem", name="Set times played…").click()

    expect(page.locator(SHEET)).to_have_count(0)
    dialog = page.locator(FORM_DIALOG)
    expect(dialog).to_be_visible()
    expect(page.locator("dialog[data-modal][open]")).to_have_count(1)
    assert errors == []


def test_a_game_status_sheet_picks_a_status_and_closes(
    narrow: Page, live_server, e2e_library, errors
):
    page = narrow
    platform = Platform.objects.create(library=e2e_library, name="PC", icon="steam")
    game = Game.objects.create(library=e2e_library, name="Test Game", platform=platform)
    game_url = game.get_absolute_url()
    page.goto(f"{live_server.url}{game_url}")

    host = page.locator('drop-down[behavior="select"]').first
    host.locator("[data-toggle]").click()
    sheet = page.locator(SHEET)
    expect(sheet).to_have_count(1)
    expect(sheet.locator("[data-dropdown-sheet-title]")).to_have_text("Status")

    with page.expect_response(
        lambda r: "/status" in r.url and r.request.method == "PATCH"
    ):
        sheet.locator('[data-option][data-value="completed"]').click()
    expect(page.locator(SHEET)).to_have_count(0)
    expect(host.locator("[data-label]")).to_contain_text("Completed")
    assert errors == []
