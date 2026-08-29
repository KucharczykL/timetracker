"""The confirmation tells the truth.

The copy is what the user consents to. Assert it in the
browser, not only against the view.
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Page, expect

from games.models import Game, Session


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.mark.untracked_games
def test_the_confirmation_promises_a_removal(
    authenticated_page: Page, live_server, e2e_library
):
    """One act, whether or not an event names the row."""
    game = Game.objects.create(library=e2e_library, name="Forgettable")

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:remove_game', args=[game.pk])}")

    expect(page.get_by_text("Remove Forgettable from your library?")).to_be_visible()

    page.click('button:has-text("Remove")')
    page.wait_for_url(f"{live_server.url}{reverse('games:list_games')}**")
    expect(page.get_by_text("Forgettable")).to_have_count(0)
    assert Game.objects.get(pk=game.pk).removed_at is not None


@pytest.mark.untracked_games
def test_removing_a_game_empties_it_from_the_session_list(
    authenticated_page: Page, live_server, e2e_library
):
    """A removed game takes its sessions out of sight, and keeps them."""
    game = Game.objects.create(library=e2e_library, name="Sessioned")
    Session.objects.create(game=game, timestamp_start=timezone.now())

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:remove_game', args=[game.pk])}")
    page.click('button:has-text("Remove")')
    page.wait_for_url(f"{live_server.url}{reverse('games:list_games')}**")

    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    expect(page.get_by_text("Sessioned")).to_have_count(0)
    assert Session.objects.filter(game=game).exists()
