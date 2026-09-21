"""The picker makes the row a person typed (#1080).

One submit: the name is typed, the create row is pressed, and the
form records a session on what came back.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


START_FIELD = 'date-time-field[field-name="started_at"]'


def _device_picker(page: Page):
    return page.locator("search-select[name='device']")


def _fill_start(page: Page) -> None:
    """A start alone is a running Timed session, which is enough."""
    for part, value in (
        ("year", "2026"),
        ("month", "01"),
        ("day", "02"),
        ("hour", "10"),
        ("minute", "30"),
    ):
        page.locator(f'{START_FIELD} input[data-date-part="{part}"]').click()
        page.keyboard.type(value)


def test_a_session_records_on_a_device_created_from_the_picker(
    authenticated_page: Page, live_server, e2e_library
):
    from tracked_games import create_tracked_game

    from games.models import Device, PlayerSession

    game = create_tracked_game(e2e_library, "Outer Wilds")
    page = authenticated_page
    page.goto(
        f"{live_server.url}{reverse('games:add_session_for_game', args=[game.pk])}"
    )

    picker = _device_picker(page)
    picker.wait_for(state="attached")
    search = picker.locator("[data-search-select-search]")
    search.click()
    search.fill("Steam Deck")

    create_row = picker.locator("[data-search-select-create]")
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/devices/") and response.request.method == "POST"
        )
    ) as response_info:
        create_row.click()
    assert response_info.value.status == 201

    device = Device.objects.get(library=e2e_library, name="Steam Deck")
    assert device.type == Device.UNKNOWN

    #: The picker holds the new row, so one submit records the session.
    _fill_start(page)
    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    session = PlayerSession.objects.get(library=e2e_library)
    assert session.device_id == device.pk


def test_a_refused_creation_makes_nothing(
    authenticated_page: Page, live_server, e2e_library
):
    from tracked_games import create_tracked_game

    from games.models import Device

    create_tracked_game(e2e_library, "Outer Wilds")
    Device.objects.create(library=e2e_library, name="Steam Deck")
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_session')}")

    picker = _device_picker(page)
    picker.wait_for(state="attached")
    search = picker.locator("[data-search-select-search]")
    search.click()
    search.fill("Steam Deck")
    page.wait_for_timeout(300)

    #: A name the library already holds is an option, never a creation.
    assert picker.locator("[data-search-select-create]").is_hidden()
    assert Device.objects.filter(library=e2e_library).count() == 1


def _run_picker(page: Page):
    return page.locator("search-select[name='playthrough']")


def test_the_run_picker_is_visible_on_a_game_holding_one_run(
    authenticated_page: Page, live_server, e2e_library
):
    """The very game this picker is for: nobody types into a hidden row."""
    from tracked_games import create_tracked_game

    game = create_tracked_game(e2e_library, "Outer Wilds")
    page = authenticated_page
    page.goto(
        f"{live_server.url}{reverse('games:add_session_for_game', args=[game.pk])}"
    )

    picker = _run_picker(page)
    picker.wait_for(state="visible")
    assert picker.locator("[data-search-select-search]").is_visible()


def test_a_session_records_on_a_run_created_from_the_picker(
    authenticated_page: Page, live_server, e2e_library
):
    from tracked_games import create_tracked_game

    from games.models import PlayerSession, Playthrough

    game = create_tracked_game(e2e_library, "Outer Wilds")
    page = authenticated_page
    page.goto(
        f"{live_server.url}{reverse('games:add_session_for_game', args=[game.pk])}"
    )

    picker = _run_picker(page)
    picker.wait_for(state="attached")
    search = picker.locator("[data-search-select-search]")
    search.click()
    search.fill("New Game Plus")

    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/playthrough/")
            and response.request.method == "POST"
        )
    ) as response_info:
        picker.locator("[data-search-select-create]").click()
    assert response_info.value.status == 201

    #: The placeholder tracking minted is named, never left beside a new run.
    run = Playthrough.objects.get(library=e2e_library, player_game__game=game)
    assert run.name == "New Game Plus"

    _fill_start(page)
    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    session = PlayerSession.objects.get(library=e2e_library)
    assert session.playthrough_id == run.pk


def test_picking_a_game_holding_one_run_holds_that_run(
    authenticated_page: Page, live_server, e2e_library
):
    """The field is required, so the sole run is held with no pick."""
    from tracked_games import create_tracked_game

    create_tracked_game(e2e_library, "Outer Wilds")
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_session')}")

    games = page.locator("search-select[name='game']")
    games.locator("[data-search-select-search]").click()
    games.locator("[data-search-select-option]").first.click()

    held = _run_picker(page).locator('[data-search-select-pills] input[type="hidden"]')
    expect(held).to_have_count(1)


def test_the_run_picker_searches_again_when_the_game_changes(
    authenticated_page: Page, live_server, e2e_library
):
    from tracked_games import create_tracked_game

    from games.models import Playthrough

    first = create_tracked_game(e2e_library, "Outer Wilds")
    second = create_tracked_game(e2e_library, "Hades")
    Playthrough.objects.filter(player_game__game=second).update(name="Hades run")
    page = authenticated_page
    page.goto(
        f"{live_server.url}{reverse('games:add_session_for_game', args=[first.pk])}"
    )

    game_picker = page.locator("search-select[name='game']")
    game_search = game_picker.locator("[data-search-select-search]")
    game_search.click()
    game_search.fill("Hades")
    game_picker.locator("[data-search-select-option]").first.click()

    runs = _run_picker(page)
    runs.locator("[data-search-select-search]").click()
    page.wait_for_timeout(400)
    labels = runs.locator("[data-search-select-option]").all_inner_texts()
    assert any("Hades run" in label for label in labels)


def test_a_purchase_records_on_a_platform_created_from_the_picker(
    authenticated_page: Page, live_server, e2e_library
):
    from tracked_games import create_tracked_game

    from games.models import Platform, Purchase

    game = create_tracked_game(e2e_library, "Outer Wilds")
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")

    games_picker = page.locator("search-select[name='games']")
    games_search = games_picker.locator("[data-search-select-search]")
    games_search.click()
    games_search.fill("Outer")
    games_picker.locator("[data-search-select-option]").first.click()

    picker = page.locator("search-select[name='platform']")
    search = picker.locator("[data-search-select-search]")
    search.click()
    search.fill("Arcade")

    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/platforms/")
            and response.request.method == "POST"
        )
    ) as response_info:
        picker.locator("[data-search-select-create]").click()
    assert response_info.value.status == 201

    platform = Platform.objects.get(library=e2e_library, name="Arcade")

    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    purchase = Purchase.objects.get(library=e2e_library)
    assert purchase.platform_id == platform.pk
    assert purchase.games.get() == game
