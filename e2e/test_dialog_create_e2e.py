"""A picker's + makes a game in a dialog and selects it."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Playthrough

LOGIN = ("tester", "secret123")


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
def authenticated_page(live_server, page: Page, e2e_user, errors) -> Page:
    _log_in(page, live_server)
    return page


def _held(page_or_dialog, name: str):
    return page_or_dialog.locator(
        f'search-select[name="{name}"] [data-search-select-pills] input[type="hidden"]'
    )


def _make_game(dialog, name: str) -> None:
    dialog.locator('input[name="name"]').press_sequentially(name)
    dialog.get_by_role("button", name="Submit", exact=True).click()


def test_add_session_selects_the_new_game(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    page.evaluate("window.notReloaded = true")
    page.locator('textarea[name="note"]').fill("kept")
    page.locator('search-select[name="game"]').get_by_role(
        "link", name="New game"
    ).click()
    dialog = page.locator("dialog[data-modal][open]")
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Add New Game")
    _make_game(dialog, "Outer Wilds")

    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    game = Game.objects.get(library=e2e_library, name="Outer Wilds")
    expect(_held(page, "game")).to_have_value(str(game.pk))
    run = Playthrough.objects.get(player_game__game=game)
    expect(_held(page, "playthrough")).to_have_value(str(run.pk))
    expect(page.locator('textarea[name="note"]')).to_have_value("kept")
    expect(page.get_by_role("link", name="New game")).to_be_focused()
    assert page.evaluate("window.notReloaded === true")
    assert errors == []


def test_a_nested_add_game_lands_in_its_own_picker(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    page.locator('search-select[name="game"]').get_by_role(
        "link", name="New game"
    ).click()
    outer = page.locator("dialog[data-modal][open]").first
    outer.locator('input[name="name"]').press_sequentially("Hollow Knight DLC")
    outer.locator('select[name="kind"]').select_option("dlc")
    outer.locator('search-select[name="parent"]').get_by_role(
        "link", name="New game"
    ).click()
    expect(page.locator("dialog[data-modal][open]")).to_have_count(2)
    _make_game(page.locator("dialog[data-modal][open]").last, "Hollow Knight")

    expect(page.locator("dialog[data-modal][open]")).to_have_count(1)
    parent = Game.objects.get(library=e2e_library, name="Hollow Knight")
    expect(_held(outer, "parent")).to_have_value(str(parent.pk))
    expect(outer.locator('input[name="name"]')).to_have_value("Hollow Knight DLC")
    assert errors == []
