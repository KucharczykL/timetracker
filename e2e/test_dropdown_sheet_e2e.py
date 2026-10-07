"""A dropdown panel opens as a bottom sheet below 640 px."""

import re

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

LOGIN = ("tester", "secret123")
PHONE = {"width": 375, "height": 812}
DESKTOP = {"width": 1280, "height": 800}
STARTED = 'drop-down:has(input[name="started"][data-date-picker-hidden])'
SHEET = "dialog[data-dropdown-sheet][open]"


def _log_in(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', LOGIN[0])
    page.fill('input[name="password"]', LOGIN[1])
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


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
    _log_in(page, live_server)
    return page


def _open_started(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('games:add_playthrough')}")
    page.locator(f"{STARTED} [data-date-picker-calendar-toggle]").click()


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
    _log_in(page, live_server)
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
    page.locator("[data-quick-overflow-trigger]").click()
    facet = page.locator("drop-down[data-quick-facet]").filter(
        has=page.get_by_role("button", name="Timing", exact=True)
    )
    facet.get_by_role("button", name="Timing", exact=True).click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible()
    sheet.locator('[data-search-select-option][data-label="Duration only"]').click()
    with page.expect_navigation():
        sheet.get_by_role("button", name="Apply", exact=True).click()
    assert "duration_only" in page.url
    assert errors == []
