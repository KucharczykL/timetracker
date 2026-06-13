import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('input[type="submit"]')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.mark.django_db
def test_game_status_selector_opens_and_patches(authenticated_page: Page, live_server):
    from games.models import Game, Platform

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Test Game", platform=platform, status="u")

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    host = page.locator("game-status-selector").first
    expect(host).to_be_attached()
    host.locator("[data-toggle]").click()
    expect(host.locator("[data-menu]")).to_be_visible()
    host.locator('[data-option][data-value="f"]').click()
    expect(host.locator("[data-menu]")).to_be_hidden()
    game.refresh_from_db()
    assert game.status == "f"
