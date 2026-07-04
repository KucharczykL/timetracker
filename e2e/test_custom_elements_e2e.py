import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.mark.django_db
def test_game_status_selector_opens_and_patches(authenticated_page: Page, live_server):
    from games.models import Game, Platform

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Test Game", platform=platform, status="u")

    page = authenticated_page
    game_url = reverse("games:view_game", args=[game.id])
    page.goto(f"{live_server.url}{game_url}")

    # The History section starts empty — the status change we make below must
    # appear in it after the htmx refresh.
    expect(page.locator("#history-container li")).to_have_count(0)

    host = page.locator('drop-down[behavior="select"]').first
    expect(host).to_be_attached()
    host.locator("[data-toggle]").click()
    expect(host.locator("[data-menu]")).to_be_visible()
    # Arm the wait for the htmx refresh GET (fired by the status-changed event
    # #history-container listens for) BEFORE the click, alongside the PATCH wait,
    # so a fast refresh can't slip through between the two.
    with (
        page.expect_response(
            lambda r: (
                game_url in r.url
                and r.request.method == "GET"
                and r.request.headers.get("hx-request") == "true"
            )
        ),
        page.expect_response(
            lambda r: "/status" in r.url and r.request.method == "PATCH"
        ),
    ):
        host.locator('[data-option][data-value="f"]').click()
    expect(host.locator("[data-menu]")).to_be_hidden()
    # Client effects of the pick: toggle label swapped, selection reflected.
    expect(host.locator("[data-label]")).to_contain_text("Finished")
    expect(host.locator('[data-option][data-value="f"]')).to_have_attribute(
        "aria-selected", "true"
    )
    expect(host.locator('[data-option][data-value="u"]')).to_have_attribute(
        "aria-selected", "false"
    )
    # The htmx refresh swapped in the re-rendered History section: the audit
    # entry for the status change is now server-rendered on the page.
    history_entries = page.locator("#history-container li")
    expect(history_entries).to_have_count(1)
    expect(history_entries).to_contain_text("Changed status from")
    expect(history_entries).to_contain_text("Unplayed")
    expect(history_entries).to_contain_text("Finished")
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

    host = page.locator('drop-down[behavior="select"]').first
    expect(host).to_be_attached()
    page.evaluate(
        "() => { window.__refreshed = false; "
        "document.body.addEventListener('device-changed', () => "
        "{ window.__refreshed = true; }); }"
    )
    host.locator("[data-toggle]").click()
    with page.expect_response(
        lambda r: "/device" in r.url and r.request.method == "PATCH"
    ):
        host.locator(f'[data-option][data-value="{deck.id}"]').click()
    expect(host.locator("[data-label]")).to_contain_text("Deck")
    expect(host.locator(f'[data-option][data-value="{deck.id}"]')).to_have_attribute(
        "aria-selected", "true"
    )
    page.wait_for_function("() => window.__refreshed === true")
    session.refresh_from_db()
    assert session.device_id == deck.id
    # No htmx container listens for device-changed (unlike status-changed /
    # play-added on the game page), so there is no refresh GET to await here.
    # Instead verify the server-rendered state: a fresh page load shows the new
    # device as the selector's current value.
    page.reload()
    host = page.locator('drop-down[behavior="select"]').first
    expect(host.locator("[data-label]")).to_contain_text("Deck")
    expect(host.locator(f'[data-option][data-value="{deck.id}"]')).to_have_attribute(
        "aria-selected", "true"
    )


@pytest.mark.django_db
def test_status_selector_reverts_on_failed_patch(authenticated_page: Page, live_server):
    """A rejected PATCH (mocked 422) reverts the optimistic label + aria-selected
    and surfaces an error toast — the server value never silently diverges."""
    from games.models import Game, Platform

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Test Game", platform=platform, status="u")

    page = authenticated_page
    page.route(
        "**/api/games/**/status",
        lambda route: route.fulfill(status=422, body=""),
    )
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    host = page.locator('drop-down[behavior="select"]').first
    host.locator("[data-toggle]").click()
    host.locator('[data-option][data-value="f"]').click()

    # The optimistic pick reverts: label back to Unplayed, "f" no longer selected.
    expect(host.locator("[data-label]")).to_contain_text("Unplayed")
    expect(host.locator('[data-option][data-value="f"]')).to_have_attribute(
        "aria-selected", "false"
    )
    expect(page.get_by_text("Couldn't save your change")).to_be_visible()
    game.refresh_from_db()
    assert game.status == "u"  # server unchanged


@pytest.mark.django_db
def test_play_event_row_increments(authenticated_page: Page, live_server):
    from games.models import Game, Platform

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Test Game", platform=platform)

    page = authenticated_page
    game_url = reverse("games:view_game", args=[game.id])
    page.goto(f"{live_server.url}{game_url}")

    container = page.locator("#playevents-container")
    expect(container).to_contain_text("No play events yet.")

    host = page.locator("play-event-row").first
    expect(host).to_be_attached()
    host.locator("[data-toggle]").click()
    # Arm the wait for the htmx refresh GET (fired by the play-added event
    # #playevents-container listens for) BEFORE the click, alongside the POST
    # wait, so a fast refresh can't slip through between the two.
    with (
        page.expect_response(
            lambda r: (
                game_url in r.url
                and r.request.method == "GET"
                and r.request.headers.get("hx-request") == "true"
            )
        ),
        page.expect_response(
            lambda r: "playevent" in r.url.lower() and r.request.method == "POST"
        ),
    ):
        host.locator("[data-add-play]").click()
    # Optimistic client-side bump on the split button…
    expect(host.locator("[data-count]")).to_have_text("1")
    # …and the htmx refresh swapped in the re-rendered Play Events section:
    # the empty state is gone, one server-rendered row and the count badge show.
    container = page.locator("#playevents-container")
    expect(container).not_to_contain_text("No play events yet.")
    expect(container.locator("tbody tr")).to_have_count(1)
    expect(container.locator("h1")).to_contain_text("1")
    assert game.playevents.count() == 1
