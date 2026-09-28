"""A person edits two games' facts and takes it back."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, PlayerGame, PlayerGameStatus
from games.writes.playergame import new_correlation_id, record_facts, track_game

#: The Undo reads the stream, so games are tracked through the command.
pytestmark = pytest.mark.untracked_games


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


def _status(game: Game) -> PlayerGameStatus:
    return PlayerGameStatus(PlayerGame.objects.get(game=game).status)


def test_two_games_are_edited_and_the_undo_puts_theirs_back(
    live_server, page: Page, e2e_user, e2e_library
):
    games = []
    for name in ("Outer Wilds", "Tunic"):
        game = Game.objects.create(library=e2e_library, name=name, sort_name=name)
        track_game(e2e_user, game, correlation_id=new_correlation_id())
        games.append(game)
    record_facts(
        e2e_user,
        games[0],
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )
    _login(page, live_server)

    listed = f"{live_server.url}{reverse('games:list_games')}"
    page.goto(listed)
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name="Edit…").first.click()
    #: The picker's host is defined by a module script.
    page.wait_for_load_state()

    expect(page.get_by_role("heading", name="Edit 2 games")).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    status = page.locator("search-select[name='choice-status']")
    expect(status.locator("[data-search-select-search]")).to_have_attribute(
        "placeholder", "Keep: mixed"
    )
    status.locator("[data-search-select-search]").click()
    status.get_by_role("option", name="Completed").click()
    mastered = page.locator("search-select[name='choice-mastered']")
    mastered.locator("[data-search-select-search]").click()
    mastered.get_by_role("option", name="Mastered", exact=True).click()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    assert [_status(game) for game in games] == [PlayerGameStatus.COMPLETED] * 2
    assert all(PlayerGame.objects.get(game=game).mastered for game in games)

    with page.expect_navigation():
        page.get_by_role("button", name="Undo").click()

    #: The redirect follows the Undo's commit.
    page.wait_for_url(listed)
    assert [_status(game) for game in games] == [
        PlayerGameStatus.PLAYED,
        PlayerGameStatus.UNPLAYED,
    ]
    assert not any(PlayerGame.objects.get(game=game).mastered for game in games)
