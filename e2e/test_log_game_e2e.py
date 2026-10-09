"""Log a game in one modal: its ticks, its panels, and a press from Game detail."""

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
    dialog = page.locator("dialog[data-modal][open]")
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Log a game")
    return dialog


def _panel(dialog: Locator, legend: str) -> Locator:
    return dialog.locator("fieldset[data-form-field-group]").filter(
        has=dialog.page.locator("legend", has_text=legend)
    )


def _tick(dialog: Locator, section: str) -> None:
    dialog.locator(f'label:has(input[name="sections"][value="{section}"])').click()


def _display(panel: Locator) -> str:
    return panel.evaluate("element => getComputedStyle(element).display")


def test_the_navbar_opens_the_log_modal(authenticated_page, live_server):
    dialog = _open_log_from_navbar(authenticated_page, live_server)

    expect(dialog.locator('input[name="sections"][value="copy"]')).to_have_count(1)


def test_a_tick_shows_its_panel_and_an_untick_hides_it(authenticated_page, live_server):
    dialog = _open_log_from_navbar(authenticated_page, live_server)
    copy_panel = _panel(dialog, "Your copy")

    assert _display(copy_panel) == "none"
    _tick(dialog, "copy")
    expect(copy_panel).to_be_visible()
    assert _display(copy_panel) == "flex"
    _tick(dialog, "copy")
    assert _display(copy_panel) == "none"


def test_ticking_dates_shows_the_run_row(authenticated_page, live_server):
    dialog = _open_log_from_navbar(authenticated_page, live_server)
    run_row = dialog.locator('[data-field-row="playthrough"]')

    assert _display(run_row) == "none"
    _tick(dialog, "dates")
    assert _display(run_row) == "flex"
    assert _display(_panel(dialog, "Dates")) == "flex"


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

    dialog = page.locator("dialog[data-modal][open]")
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Log Outer Wilds")
    _tick(dialog, "copy")
    pick_choice(dialog, "release", str(release.pk))
    dialog.locator('label:has(input[name="price"][value="none"])').click()
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
