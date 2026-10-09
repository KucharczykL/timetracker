"""Log a game: the modal, its nested dialogs, a picked game and a refusal."""

import pytest
from django.urls import reverse
from playwright.sync_api import Locator, Page, expect
from tracked_games import create_tracked_game

from e2e.helpers import log_in, open_row_menu, pick_choice
from games.models import PlayerGameStatus


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


def _section(page: Page, section: str) -> Locator:
    return page.locator(f'dialog[data-log-section="{section}"]')


def _open_section(dialog: Locator, section: str) -> None:
    dialog.locator(f'[data-log-section-edit="{section}"]').click()


def test_the_navbar_opens_the_log_modal(authenticated_page, live_server):
    dialog = _open_log_from_navbar(authenticated_page, live_server)

    expect(dialog.get_by_role("button", name="Add playtime…")).to_be_visible()
    expect(dialog.get_by_role("button", name="Create log")).to_be_visible()


def test_a_navbar_pick_reloads_with_the_games_data(
    authenticated_page, live_server, e2e_library
):
    game = create_tracked_game(e2e_library, "Tunic", status=PlayerGameStatus.COMPLETED)
    page = authenticated_page
    dialog = _open_log_from_navbar(page, live_server)

    pick_choice(dialog, "game", str(game.pk))

    expect(page.locator("dialog[data-modal][open]")).to_have_count(1)
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Log Tunic")
    expect(dialog.locator('input[name="status"]')).to_have_value("completed")
    expect(dialog.get_by_role("button", name="Save", exact=True)).to_be_visible()


def test_add_playtime_opens_and_done_keeps_what_was_typed(
    authenticated_page, live_server, e2e_library
):
    game = create_tracked_game(e2e_library, "Tunic")
    page = authenticated_page
    dialog = _open_log_from_navbar(page, live_server)
    pick_choice(dialog, "game", str(game.pk))
    section = _section(page, "playtime")

    _open_section(dialog, "playtime")
    expect(section).to_have_attribute("open", "")
    section.locator('input[name="duration_hours"]').fill("2")
    section.get_by_role("button", name="Done").click()

    expect(section).not_to_have_attribute("open", "")
    expect(section.locator('input[name="duration_hours"]')).to_have_value("2")
    expect(dialog.get_by_role("button", name="Playtime added")).to_be_visible()


def test_a_refusal_reopens_its_section(authenticated_page, live_server, e2e_library):
    game = create_tracked_game(e2e_library, "Tunic")
    page = authenticated_page
    dialog = _open_log_from_navbar(page, live_server)
    pick_choice(dialog, "game", str(game.pk))
    _open_section(dialog, "playtime")
    section = _section(page, "playtime")
    section.locator('input[name="duration_hours"]').fill("0")
    section.locator('input[name="duration_minutes"]').fill("0")
    section.get_by_role("button", name="Done").click()

    dialog.get_by_role("button", name="Save", exact=True).click()

    expect(section).to_have_attribute("open", "")
    expect(section.get_by_text("Give a duration above zero.")).to_be_visible()


def test_game_detail_locks_the_game(authenticated_page, live_server, e2e_library):
    game = create_tracked_game(e2e_library, "Outer Wilds")
    page = authenticated_page
    page.goto(
        f"{live_server.url}{reverse('games:view_game', args=[game.pk, game.url_slug])}"
    )
    open_row_menu(page, f"played-{game.pk}")
    page.get_by_text("Log…", exact=True).click()

    dialog = page.locator("dialog[data-modal][open]").first
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Log Outer Wilds")
    expect(dialog.locator('search-select[name="game"]')).to_have_count(0)
    expect(dialog.locator('input[name="game"]')).to_have_value(str(game.pk))
