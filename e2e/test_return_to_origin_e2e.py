"""A real browser edits from a filtered list and lands back on it."""

import json
import re
from urllib.parse import quote

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Platform, PlayerGameStatus
from games.writes.playergame import new_correlation_id, record_facts, track_game

#: The fixture below tracks its games the way production does, so the
#: conftest fixture that writes a bare row must stay out of the way: a
#: row already there turns TrackGame into a no-op, and the delete this
#: module exercises needs the reference that event captures.
pytestmark = pytest.mark.untracked_games


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def world(live_server, e2e_user):
    platform = Platform.objects.create(library=e2e_user.library, name="PC")
    played = Game.objects.create(
        library=e2e_user.library, name="Alpha", platform=platform
    )
    unplayed = Game.objects.create(
        library=e2e_user.library, name="Zeta Unplayed", platform=platform
    )
    for game in (played, unplayed):
        track_game(e2e_user, game, correlation_id=new_correlation_id())
    #: Stated as a command, so the projection the list reads and the
    #: catalog column the filter reads say the same word.
    record_facts(
        e2e_user,
        played,
        status=PlayerGameStatus.PLAYED,
        correlation_id=new_correlation_id(),
    )
    return played


@pytest.fixture
def authenticated_page(live_server, page: Page, world) -> Page:
    _login(page, live_server)
    return page


def _played_only_path() -> str:
    return (
        reverse("games:list_games")
        + "?filter="
        + quote(json.dumps({"status": {"modifier": "INCLUDES", "value": ["played"]}}))
    )


def test_editing_from_a_filtered_list_returns_to_it(
    authenticated_page, live_server, world
):
    list_path = _played_only_path()
    authenticated_page.goto(f"{live_server.url}{list_path}")
    # The filter is doing work: the unplayed game is absent.
    expect(authenticated_page.locator("table")).to_contain_text("Alpha")
    expect(authenticated_page.locator("table")).not_to_contain_text("Zeta Unplayed")

    authenticated_page.click('a[href*="/edit?origin="]')
    expect(authenticated_page).to_have_url(re.compile(re.escape("/edit?origin=")))
    authenticated_page.fill('input[name="name"]', "Alpha Renamed")
    authenticated_page.click('#add-form button[type="submit"]')

    expect(authenticated_page).to_have_url(f"{live_server.url}{list_path}")
    expect(authenticated_page.locator("table")).to_contain_text("Alpha Renamed")
    expect(authenticated_page.locator("table")).not_to_contain_text("Zeta Unplayed")


def test_deleting_a_game_from_its_detail_page_lands_on_the_list(
    authenticated_page, live_server, world
):
    authenticated_page.goto(f"{live_server.url}{world.get_absolute_url()}")
    authenticated_page.click('a:has-text("Delete")')
    authenticated_page.click('form button[type="submit"]:has-text("Delete")')
    expect(authenticated_page).to_have_url(
        f"{live_server.url}{reverse('games:list_games')}"
    )
    #: A tracked game is named in an event, so the row stays as a
    #: tombstone. What the list shows is the assertion either way.
    expect(authenticated_page.locator("table")).not_to_contain_text("Alpha")
    assert Game.objects.get(id=world.id).removed_at is not None
