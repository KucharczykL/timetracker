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
    with page.expect_response(
        lambda r: "/status" in r.url and r.request.method == "PATCH"
    ):
        host.locator('[data-option][data-value="f"]').click()
    expect(host.locator("[data-menu]")).to_be_hidden()
    game.refresh_from_db()
    assert game.status == "f"


@pytest.mark.django_db
def test_session_device_selector_patches(authenticated_page: Page, live_server):
    from games.models import Device, Game, Platform, Session

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Test Game", platform=platform)
    desktop = Device.objects.create(name="Desktop")
    deck = Device.objects.create(name="Deck")
    session = Session.objects.create(
        game=game, device=desktop, timestamp_start="2025-01-01 00:00:00+00:00"
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    host = page.locator("session-device-selector").first
    expect(host).to_be_attached()
    host.locator("[data-toggle]").click()
    with page.expect_response(
        lambda r: "/device" in r.url and r.request.method == "PATCH"
    ):
        host.locator(f'[data-option][data-value="{deck.id}"]').click()
    session.refresh_from_db()
    assert session.device_id == deck.id
