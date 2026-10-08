"""A person removes two games from the Games list and takes it back."""

from django.urls import reverse
from playwright.sync_api import Page, expect
from tracked_games import create_tracked_game

from e2e.helpers import log_in
from games.models import Platform, PlayerGame


def test_two_games_are_removed_and_the_undo_puts_them_back(
    live_server, page: Page, e2e_library
):
    games = [
        create_tracked_game(e2e_library, name) for name in ("Outer Wilds", "Tunic")
    ]
    log_in(page, live_server)

    listed = f"{live_server.url}{reverse('games:list_games')}"
    page.goto(listed)
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name="Remove", exact=True).first.click()

    expect(page.get_by_role("heading", name="Remove 2 games")).to_be_visible()
    expect(page.locator("[data-bulk-sample-row]")).to_have_count(2)
    page.get_by_role("button", name="Remove", exact=True).click()

    page.wait_for_url(listed)
    expect(page.locator("tbody tr")).to_have_count(0)
    for game in games:
        game.refresh_from_db()
        assert game.removed_at is not None

    page.get_by_role("button", name="Undo").click()

    #: Server-rendered: the write has landed.
    expect(page.get_by_role("cell", name="Outer Wilds").first).to_be_visible()
    for game in games:
        game.refresh_from_db()
        assert game.removed_at is None
    assert not PlayerGame.objects.filter(
        library=e2e_library, removed_at__isnull=False
    ).exists()


def test_each_row_checkbox_names_its_game_alone(live_server, page: Page, e2e_library):
    platform = Platform.objects.create(
        library=e2e_library, name="PC", icon="steam", group="PC"
    )
    create_tracked_game(
        e2e_library, "The Witness", platform=platform, sort_name="Witness, The"
    )
    log_in(page, live_server)

    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    expect(page.get_by_role("checkbox", name="The Witness", exact=True)).to_have_count(
        1
    )
