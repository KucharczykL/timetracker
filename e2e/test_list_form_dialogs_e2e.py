"""Presses each real link; saves return focus."""

import re
from datetime import date, timedelta

import pytest
from django.urls import reverse
from entries import record_entry
from graphs import default_graph
from historical_playtime_rows import record_row
from playwright.sync_api import Locator, Page, ViewportSize, expect
from purchases import record_purchase
from session_rows import duration_only_row, tracked_run
from tracked_games import create_tracked_game

from e2e.helpers import pick_choice, record_copy, top_sheet
from games.models import (
    Game,
    LibraryEntry,
    Platform,
    PlayerSession,
    Playthrough,
    Purchase,
    UserLibrary,
)
from timetracker.temporal import TemporalValue

PHONE = ViewportSize(width=375, height=812)
WIDE = ViewportSize(width=1280, height=800)
DIALOG = "dialog[data-modal][open]"
SHEET = "dialog[data-dropdown-sheet][open]"
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


def _open(page: Page, url: str) -> None:
    """Load list; set window.notReloaded."""
    page.goto(url)
    page.wait_for_function("() => !!customElements.get('drop-down')")
    page.evaluate("window.notReloaded = true")


def _reloaded(page: Page) -> bool:
    return page.evaluate("window.notReloaded !== true")


def _dialog(page: Page) -> Locator:
    return page.locator(DIALOG).last


def _open_item(
    page: Page,
    toggle: Locator | str | re.Pattern[str],
    item: str,
    submenu: str | None = None,
) -> None:
    """Open row menu, flyout, then press ``item``."""
    menu = toggle if isinstance(toggle, Locator) else _row_toggle(page, toggle)
    menu.click()
    if submenu is not None:
        page.get_by_role("menuitem", name=submenu).hover()
    page.get_by_role("menuitem", name=item).click()


def _submit(dialog: Locator) -> Locator:
    """Form's submit, whatever the page calls it."""
    return dialog.locator('form button[type="submit"]').first


def _clear_required(field: Locator) -> None:
    """Empty field, drop HTML required; server refuses."""
    field.fill("")
    field.evaluate("field => field.required = false")


def _saved(page: Page, toggle: Locator) -> None:
    """Dialog closed, host reloaded, focus on toggle."""
    expect(page.locator(DIALOG)).to_have_count(0)
    expect(toggle).to_be_focused()
    assert _reloaded(page)


def _invalid_stays(dialog: Locator) -> None:
    expect(dialog.locator('[aria-invalid="true"]').first).to_be_visible()
    expect(dialog).to_be_visible()


def _row_toggle(page: Page, name: str | re.Pattern[str]) -> Locator:
    return page.get_by_role("button", name=name)


def _game_on(library: UserLibrary, name: str, platform: Platform) -> Game:
    game = create_tracked_game(library, name)
    return default_graph(game, library, platform=platform).game


#: Matches game and day, not their format.
SESSION_TOGGLE = re.compile(r"^Tunic, .* actions$")
PLAYTHROUGH_TOGGLE = re.compile(r", Tunic actions$")
HISTORICAL_TOGGLE = re.compile(r"^Tunic, .* actions$")
PURCHASE_TOGGLE = re.compile(r"\(Tunic\) actions$")
GAME_TOGGLE = re.compile(r"^Tunic( \(PS5\))? actions$")
RENAMED_GAME_TOGGLE = re.compile(r"^Tunic Deluxe( \(PS5\))? actions$")
COPY_TOGGLE = "Tunic (PS5) actions"


# Sessions


def test_a_session_edit_saves_and_returns_focus(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    run = tracked_run(e2e_library, _game_on(e2e_library, "Tunic", _ps5()))
    session = duration_only_row(run, date(2024, 6, 1), timedelta(hours=1))
    _open(page, f"{live_server.url}{reverse('games:list_sessions')}")
    _open_item(page, SESSION_TOGGLE, "Edit")

    dialog = _dialog(page)
    expect(dialog.locator("[data-form-dialog-title]")).to_contain_text("Edit")
    duration = dialog.locator('input[name="duration"]')
    duration.fill("")
    duration.press_sequentially("020000")
    _submit(dialog).click()

    _saved(page, _row_toggle(page, SESSION_TOGGLE))
    session.refresh_from_db()
    assert session.effective_duration == timedelta(hours=2)
    assert errors == []


def test_an_invalid_session_edit_stays_in_the_dialog(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    run = tracked_run(e2e_library, _game_on(e2e_library, "Tunic", _ps5()))
    duration_only_row(run, date(2024, 6, 1), timedelta(hours=1))
    _open(page, f"{live_server.url}{reverse('games:list_sessions')}")
    _open_item(page, SESSION_TOGGLE, "Edit")

    dialog = _dialog(page)
    _clear_required(dialog.locator('input[name="duration"]'))
    _submit(dialog).click()

    _invalid_stays(dialog)
    assert errors == []


def test_recording_a_session_as_historical_playtime_returns_to_the_main(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    run = tracked_run(e2e_library, _game_on(e2e_library, "Tunic", _ps5()))
    duration_only_row(run, date(2024, 6, 1), timedelta(hours=9))
    _open(page, f"{live_server.url}{reverse('games:list_sessions')}")
    _open_item(page, SESSION_TOGGLE, "Record as historical playtime")

    dialog = _dialog(page)
    expect(dialog.locator("[data-form-dialog-title]")).to_contain_text(
        "Record as historical playtime"
    )
    _submit(dialog).click()

    #: Removing the row moves focus to main.
    expect(page.locator(DIALOG)).to_have_count(0)
    expect(page.get_by_role("button", name="Undo")).to_be_visible()
    expect(page.locator("#main-container")).to_be_focused()
    assert _reloaded(page)
    assert errors == []


# Playthroughs and historical playtime


def test_a_playthrough_edit_saves_and_returns_focus(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    tracked_run(e2e_library, _game_on(e2e_library, "Tunic", _ps5()))
    _open(page, f"{live_server.url}{reverse('games:list_playthroughs')}")
    _open_item(page, PLAYTHROUGH_TOGGLE, "Edit")

    dialog = _dialog(page)
    dialog.locator('[name="note"]').fill("First run")
    _submit(dialog).click()

    _saved(page, _row_toggle(page, PLAYTHROUGH_TOGGLE))
    assert Playthrough.objects.get().note == "First run"
    assert errors == []


def test_a_historical_playtime_edit_saves_and_returns_focus(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    record_row(
        [tracked_run(e2e_library, _game_on(e2e_library, "Tunic", _ps5()))],
        when="2020",
    )
    _open(page, f"{live_server.url}{reverse('games:list_historical_playtime')}")
    _open_item(page, HISTORICAL_TOGGLE, "Edit")

    dialog = _dialog(page)
    dialog.locator('input[name="duration_hours"]').fill("0")
    _submit(dialog).click()
    #: Zero duration is refused; its sentence shows.
    region = dialog.get_by_role("region", name="Notifications")
    expect(region).to_contain_text("at least a second")
    expect(dialog).to_be_visible()

    dialog.locator('input[name="duration_hours"]').fill("3")
    _submit(dialog).click()
    _saved(page, _row_toggle(page, HISTORICAL_TOGGLE))
    #: The browser logs the refused 409 too.
    assert errors and all("409 (Conflict)" in error for error in errors)


# Platforms and games


def test_a_platform_edit_refuses_a_duplicate_name_on_the_field(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    Platform.objects.create(library=e2e_library, name="Amiga", group="Commodore")
    atari = Platform.objects.create(
        library=e2e_library, name="Atari ST", group="Commodore"
    )
    _open(page, f"{live_server.url}{reverse('games:list_platforms')}")
    _open_item(page, "Atari ST (Commodore) actions", "Edit")

    dialog = _dialog(page)
    dialog.locator('input[name="name"]').fill("Amiga")
    _submit(dialog).click()

    #: The refusal lists in the form before the name is read back.
    refusal = dialog.locator("[data-form-errors]")
    expect(refusal).to_contain_text("is violated")
    # TODO(#1608): assert the name field error.
    atari.refresh_from_db()
    assert atari.name == "Atari ST"
    expect(dialog).to_be_visible()
    assert errors == []


def test_a_game_edit_saves_and_returns_focus(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    game = _game_on(e2e_library, "Tunic", _ps5())
    _open(page, f"{live_server.url}{reverse('games:list_games')}")
    _open_item(page, GAME_TOGGLE, "Edit")

    dialog = _dialog(page)
    dialog.locator('input[name="name"]').fill("Tunic Deluxe")
    _submit(dialog).click()

    _saved(page, _row_toggle(page, RENAMED_GAME_TOGGLE))
    game.refresh_from_db()
    assert game.name == "Tunic Deluxe"
    assert errors == []


# Library copies and purchases


def test_a_copy_edit_saves_and_returns_focus(
    authenticated_page: Page, live_server, e2e_user, e2e_library, errors
):
    page = authenticated_page
    record_copy(e2e_user, e2e_library, "Tunic")
    _open(page, f"{live_server.url}{reverse('games:list_library')}")
    _open_item(page, COPY_TOGGLE, "Edit…")

    dialog = _dialog(page)
    dialog.locator('[name="note"]').fill("Bought used")
    _submit(dialog).click()

    _saved(page, _row_toggle(page, COPY_TOGGLE))
    assert LibraryEntry.objects.get(library=e2e_library).note == "Bought used"
    assert errors == []


def test_a_copy_edit_on_an_ended_copy_saves_how_it_left(
    authenticated_page: Page, live_server, e2e_user, e2e_library, errors
):
    page = authenticated_page
    record_copy(e2e_user, e2e_library, "Tunic")
    _open(page, f"{live_server.url}{reverse('games:list_library')}")
    _open_item(
        page,
        COPY_TOGGLE,
        "With details…",
        submenu="I no longer have it",
    )
    pick_choice(_dialog(page), "way", "sold")
    _submit(_dialog(page)).click()
    expect(page.locator(DIALOG)).to_have_count(0)

    #: The save reloaded the host; stamp it again.
    _open(page, f"{live_server.url}{reverse('games:list_library')}")
    _open_item(page, COPY_TOGGLE, "Edit how it left…")

    dialog = _dialog(page)
    expect(dialog.locator("[data-form-dialog-title]")).to_contain_text(
        "Edit how it left"
    )
    dialog.locator('[name="note"]').fill("Sold to a friend")
    _submit(dialog).click()

    _saved(page, _row_toggle(page, COPY_TOGGLE))
    assert (
        LibraryEntry.objects.get(library=e2e_library).access_end_note
        == "Sold to a friend"
    )
    assert errors == []


def test_a_purchase_added_from_a_copy_types_into_the_currency_mask(
    authenticated_page: Page, live_server, e2e_user, e2e_library, errors
):
    page = authenticated_page
    record_copy(e2e_user, e2e_library, "Tunic")
    _open(page, f"{live_server.url}{reverse('games:list_library')}")
    _open_item(page, COPY_TOGGLE, "Add purchase…")

    dialog = _dialog(page)
    expect(dialog.locator("[data-form-dialog-title]")).to_contain_text("Add purchase")
    dialog.get_by_label("Paid", exact=True).check()
    dialog.locator('input[name="amount"]').fill("12.50")
    currency = dialog.locator('input[name="currency"]')
    currency.fill("")
    currency.press_sequentially("eu3r")
    #: Mask drops the digit; field is uppercase.
    expect(currency).to_have_value("eur")
    expect(currency).to_have_css("text-transform", "uppercase")
    _submit(dialog).click()

    _saved(page, _row_toggle(page, COPY_TOGGLE))
    purchase = Purchase.objects.get()
    assert purchase.currency == "EUR"
    assert str(purchase.amount) == "12.50"
    assert errors == []


def test_an_end_with_details_refused_for_the_date_stays_in_the_dialog(
    authenticated_page: Page, live_server, e2e_user, e2e_library, errors
):
    page = authenticated_page
    platform = _ps5()
    game = _game_on(e2e_library, "Tunic", platform)
    release = default_graph(game, e2e_library, platform=platform).release
    record_entry(
        e2e_library,
        release,
        acquired=TemporalValue.parse("2099-01-01"),
    )
    _open(page, f"{live_server.url}{reverse('games:list_library')}")
    _open_item(
        page,
        COPY_TOGGLE,
        "With details…",
        submenu="I no longer have it",
    )

    dialog = _dialog(page)
    _submit(dialog).click()

    region = dialog.get_by_role("region", name="Notifications")
    expect(region).to_contain_text("acquired after that day")
    expect(dialog).to_be_visible()
    assert errors and all("409 (Conflict)" in error for error in errors)


def test_an_end_with_details_saves_and_returns_focus_to_the_main(
    authenticated_page: Page, live_server, e2e_user, e2e_library, errors
):
    page = authenticated_page
    record_copy(e2e_user, e2e_library, "Tunic")
    _open(page, f"{live_server.url}{reverse('games:list_library')}")
    _open_item(
        page,
        COPY_TOGGLE,
        "With details…",
        submenu="I no longer have it",
    )

    dialog = _dialog(page)
    pick_choice(dialog, "way", "sold")
    _submit(dialog).click()

    expect(page.locator(DIALOG)).to_have_count(0)
    expect(page.locator("#main-container")).to_be_focused()
    assert _reloaded(page)
    assert LibraryEntry.objects.get(library=e2e_library).access_end_way == "sold"
    assert errors == []


def test_a_purchase_edit_refuses_a_missing_currency_on_the_field(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    record_purchase(record_entry(e2e_library, _release(e2e_library, "Tunic")))
    _open(page, f"{live_server.url}{reverse('games:list_purchases')}")
    _open_item(page, PURCHASE_TOGGLE, "Edit purchase…")

    dialog = _dialog(page)
    _clear_required(dialog.locator('input[name="currency"]'))
    _submit(dialog).click()

    _invalid_stays(dialog)
    assert errors == []


def test_a_purchase_edit_saves_and_returns_focus(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    record_purchase(record_entry(e2e_library, _release(e2e_library, "Tunic")))
    _open(page, f"{live_server.url}{reverse('games:list_purchases')}")
    _open_item(page, PURCHASE_TOGGLE, "Edit purchase…")

    dialog = _dialog(page)
    dialog.locator('[name="note"]').fill("Bought on sale")
    _submit(dialog).click()

    _saved(page, _row_toggle(page, PURCHASE_TOGGLE))
    assert Purchase.objects.get().note == "Bought on sale"
    assert errors == []


# Library page and navbar


def test_adding_a_device_from_the_library_page_returns_focus_to_the_link(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    page.set_viewport_size(WIDE)
    _open(page, f"{live_server.url}{reverse('games:library')}")
    add = page.locator(
        f'[data-summary-row]:has-text("Devices") a[href^="{reverse("games:add_device")}"]:visible'
    )
    add.click()

    dialog = _dialog(page)
    dialog.locator('input[name="name"]').fill("Steam Deck")
    _submit(dialog).click()

    expect(page.locator(DIALOG)).to_have_count(0)
    expect(add).to_be_focused()
    assert _reloaded(page)
    assert errors == []


def test_adding_to_the_library_from_the_library_page_opens_the_dialog(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    page.set_viewport_size(WIDE)
    _open(page, f"{live_server.url}{reverse('games:library')}")
    add = page.locator(
        f'[data-summary-row]:has-text("Temporary home") a[href^="{reverse("games:add_to_library")}"]:visible'
    )
    add.click()

    dialog = _dialog(page)
    expect(dialog.locator("[data-form-dialog-title]")).to_contain_text("Add to library")
    expect(page.locator(FORM_DIALOG)).to_have_count(1)
    assert errors == []


def test_the_navbar_log_game_opens_the_session_dialog(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    _game_on(e2e_library, "Tunic", _ps5())
    _open(page, f"{live_server.url}{reverse('games:list_games')}")
    page.get_by_role("link", name="Log game", exact=True).click()

    dialog = _dialog(page)
    expect(dialog.locator('input[name="duration"]')).to_be_visible()
    assert errors == []


def test_the_navbar_log_game_from_a_form_page_saves_without_reloading_the_host(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    game = _game_on(e2e_library, "Tunic", _ps5())
    _open(page, f"{live_server.url}{reverse('games:edit_game', args=[game.pk])}")
    page.get_by_role("link", name="Log game", exact=True).click()

    dialog = _dialog(page)
    pick_choice(dialog, "game", str(game.pk))
    _submit(dialog).click()

    #: A form page is no read-only origin, so the host stays put.
    expect(page.locator(DIALOG)).to_have_count(0)
    assert not _reloaded(page)
    assert PlayerSession.objects.alive().count() == 1
    assert errors == []


# Phone width


def test_a_copy_form_opens_after_the_sheet_chain_closes_at_phone_width(
    authenticated_page: Page, live_server, e2e_user, e2e_library, errors
):
    page = authenticated_page
    page.set_viewport_size(PHONE)
    record_copy(e2e_user, e2e_library, "Tunic")
    _open(page, f"{live_server.url}{reverse('games:list_library')}")
    page.get_by_role("button", name=COPY_TOGGLE).click()
    top_sheet(page).get_by_role("menuitem", name="I no longer have it").click()
    top_sheet(page).get_by_role("menuitem", name="With details…").click()

    expect(page.locator(SHEET)).to_have_count(0)
    expect(page.locator(FORM_DIALOG)).to_have_count(1)
    expect(
        page.locator(FORM_DIALOG).locator("[data-form-dialog-title]")
    ).to_contain_text("I no longer have it")
    assert errors == []


# Helpers that need the seeds above


def _ps5() -> Platform:
    return Platform.objects.get_or_create(name="PS5", group="Sony")[0]


def _release(library: UserLibrary, name: str):
    platform = _ps5()
    game = create_tracked_game(library, name)
    return default_graph(game, library, platform=platform).release
