"""Log a game: its ticks, section dialogs and a press."""

import pytest
from django.urls import reverse
from graphs import default_graph
from playwright.sync_api import Locator, Page, expect
from tracked_games import create_tracked_game

from e2e.helpers import log_in, open_row_menu, pick_choice
from games.models import Game, LibraryEntry


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    log_in(page, live_server)
    return page


def _open_log_from_navbar(page: Page, live_server) -> Locator:
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    page.locator('a[aria-label="Log game"]').click()
    dialog = page.locator("dialog[data-modal][open]").first
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Log a game")
    return dialog


def _open_log_for(page: Page, live_server, game: Game) -> Locator:
    dialog = _open_log_from_navbar(page, live_server)
    pick_choice(dialog, "game", str(game.pk))
    return dialog


def _section(page: Page, section: str) -> Locator:
    return page.locator(f'dialog[data-log-section="{section}"]')


def _tick(dialog: Locator, section: str) -> None:
    dialog.locator(f'label:has(input[name="sections"][value="{section}"])').click()


def _display(panel: Locator) -> str:
    return panel.evaluate("element => getComputedStyle(element).display")


def test_the_navbar_opens_the_log_modal(authenticated_page, live_server):
    dialog = _open_log_from_navbar(authenticated_page, live_server)

    expect(dialog.locator('input[name="sections"][value="copy"]')).to_be_disabled()
    expect(dialog.get_by_text("Pick a game first.")).to_be_visible()


def test_a_tick_opens_its_section_and_done_keeps_it(
    authenticated_page, live_server, e2e_library
):
    page = authenticated_page
    dialog = _open_log_for(page, live_server, create_tracked_game(e2e_library, "Tunic"))
    section = _section(page, "copy")

    _tick(dialog, "copy")
    expect(section).to_have_attribute("open", "")
    section.get_by_role("button", name="Done").click()

    expect(section).not_to_have_attribute("open", "")
    expect(dialog.locator('input[name="sections"][value="copy"]')).to_be_checked()
    expect(dialog.get_by_text("Copy and price added")).to_be_visible()


def test_dismissing_a_section_unticks_it(authenticated_page, live_server, e2e_library):
    page = authenticated_page
    dialog = _open_log_for(page, live_server, create_tracked_game(e2e_library, "Tunic"))
    section = _section(page, "dates")

    _tick(dialog, "dates")
    expect(section).to_have_attribute("open", "")
    page.keyboard.press("Escape")

    expect(section).not_to_have_attribute("open", "")
    expect(dialog.locator('input[name="sections"][value="dates"]')).not_to_be_checked()
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Log a game")


def test_ticking_dates_shows_the_run_row(authenticated_page, live_server, e2e_library):
    page = authenticated_page
    dialog = _open_log_for(page, live_server, create_tracked_game(e2e_library, "Tunic"))
    run_row = dialog.locator('[data-field-row="playthrough"]')

    assert _display(run_row) == "none"
    _tick(dialog, "dates")
    _section(page, "dates").get_by_role("button", name="Done").click()
    assert _display(run_row) == "flex"


def test_a_refusal_reopens_its_section(authenticated_page, live_server, e2e_library):
    game = create_tracked_game(e2e_library, "Tunic")
    release = default_graph(game, e2e_library).release
    page = authenticated_page
    dialog = _open_log_for(page, live_server, game)
    _tick(dialog, "copy")
    section = _section(page, "copy")
    pick_choice(section, "release", str(release.pk))
    section.get_by_role("button", name="Done").click()
    dialog.get_by_role("button", name="Log game", exact=True).click()

    expect(section).to_have_attribute("open", "")
    expect(section.get_by_text("State what you paid")).to_be_visible()


def test_a_press_from_game_detail_logs_a_copy_to_that_game(
    authenticated_page, live_server, e2e_library
):
    game = create_tracked_game(e2e_library, "Outer Wilds")
    release = default_graph(game, e2e_library).release
    page = authenticated_page
    page.goto(
        f"{live_server.url}{reverse('games:view_game', args=[game.pk, game.url_slug])}"
    )
    open_row_menu(page, f"played-{game.pk}")
    page.get_by_text("Log…", exact=True).click()

    dialog = page.locator("dialog[data-modal][open]").first
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Log Outer Wilds")
    _tick(dialog, "copy")
    section = _section(page, "copy")
    pick_choice(section, "release", str(release.pk))
    section.locator('label:has(input[name="price"][value="none"])').click()
    section.get_by_role("button", name="Done").click()
    dialog.get_by_role("button", name="Log game", exact=True).click()

    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(page.get_by_text("Logged Outer Wilds.")).to_be_visible()
    assert LibraryEntry.objects.filter(
        library=e2e_library, player_game__game=game
    ).exists()


def test_new_game_hands_the_game_back_to_the_log_modal(
    authenticated_page, live_server, e2e_library
):
    dialog = _open_log_from_navbar(authenticated_page, live_server)
    dialog.locator('search-select[name="game"]').get_by_role(
        "link", name="New game"
    ).click()
    stacked = authenticated_page.locator("dialog[data-modal][open]").last
    stacked.locator('input[name="name"]').press_sequentially("Hades")
    stacked.get_by_role("button", name="Submit", exact=True).click()

    expect(authenticated_page.locator("dialog[data-modal][open]")).to_have_count(1)
    game = Game.objects.get(library=e2e_library, name="Hades")
    expect(
        dialog.locator(
            'search-select[name="game"] [data-search-select-pills] input[type="hidden"]'
        )
    ).to_have_value(str(game.pk))
