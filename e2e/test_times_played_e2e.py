"""A person states how many times a game was played."""

import pytest
from playwright.sync_api import Page, expect

from e2e.helpers import log_in
from games.models import Game, PlayerGame
from games.reads.playthrough_runs import completed_run_count
from games.writes.playergame import new_correlation_id, track_game

#: Tracked by command: the Undo reads events.
pytestmark = pytest.mark.untracked_games


def test_a_count_opens_in_a_dialog_and_its_undo_takes_it_back(
    live_server, page: Page, e2e_user, e2e_library
):
    game = Game.objects.create(library=e2e_library, name="Outer Wilds")
    track_game(e2e_user, game, correlation_id=new_correlation_id())
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    log_in(page, live_server)
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    detail_url = page.url

    page.get_by_role("button", name="Playthrough actions").click()
    page.get_by_role("menuitem", name="Set times played…").click()
    dialog = page.locator("dialog[data-modal][open]")
    expect(dialog).to_be_visible()
    assert page.url == detail_url
    dialog.locator('input[name="count"]').fill("3")
    dialog.get_by_role("button", name="Submit", exact=True).click()

    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    section = page.locator("#playthroughs-container")
    expect(section.locator("tbody tr")).to_have_count(3)
    tracked = PlayerGame.objects.get(game=game)
    assert completed_run_count(e2e_library, tracked) == 3

    page.locator("toast-stack").get_by_role("button", name="Undo").click()
    expect(section.locator("tbody tr")).to_have_count(1)
    assert completed_run_count(e2e_library, tracked) == 0
    assert errors == []
