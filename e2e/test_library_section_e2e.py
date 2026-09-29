"""Every copy act, from Game detail and from the Add to library page."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect
from tracked_games import create_tracked_game

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.models import Game, LibraryEntry, Platform, Release, UserLibrary


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _game_on(library: UserLibrary, name: str, platform: Platform) -> Game:
    game = create_tracked_game(library, name)
    state_catalog_graph(
        game=game,
        library=library,
        editions=[
            EditionState(
                key="edition",
                is_default=True,
                releases=(
                    ReleaseState(key="release", platform=platform, is_default=True),
                ),
            )
        ],
    )
    return game


def _submit(page: Page) -> None:
    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()


def test_a_copy_goes_through_every_act_from_game_detail(
    authenticated_page: Page, live_server, e2e_library
):
    ps5 = Platform.objects.create(name="PS5", group="Sony")
    switch = Platform.objects.create(name="Switch", group="Nintendo")
    game = _game_on(e2e_library, "Tunic", ps5)
    page = authenticated_page
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    section = page.locator("#library")
    rows = section.locator("[data-summary-row]")
    expect(section.get_by_text("Nothing in your library yet.")).to_be_visible()

    section.get_by_role("link", name="Add").click()
    page.wait_for_function("() => !!customElements.get('search-select')")
    picker = page.locator("search-select[name='release']")
    held = picker.locator('[data-search-select-pills] input[type="hidden"]')
    expect(held).to_have_value(str(Release.objects.get(edition__game=game).pk))
    search = picker.locator("[data-search-select-search]")
    search.click()
    search.fill("Switch")
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/releases/")
            and response.request.method == "POST"
        )
    ) as response_info:
        picker.locator("[data-search-select-create]").click()
    assert response_info.value.status == 201
    created = Release.objects.get(edition__game=game, platform=switch)
    page.get_by_label("Physical").check()
    _submit(page)

    expect(page.get_by_text("Added to your library.")).to_be_visible()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Switch")
    expect(rows.first).to_contain_text("Owned · Physical")
    entry = LibraryEntry.objects.get(library=e2e_library)
    assert entry.release_id == created.pk

    rows.first.get_by_role("link", name="End access").click()
    page.select_option("select[name='way']", "sold")
    _submit(page)

    expect(page.get_by_text("Access ended.")).to_be_visible()
    expect(rows.first).to_contain_text("Sold")

    rows.first.get_by_role("link", name="Resume").click()
    _submit(page)

    expect(page.get_by_text("Access resumed.")).to_be_visible()
    expect(rows.first).not_to_contain_text("Sold")

    rows.first.get_by_role("link", name="Remove").click()
    page.click('button:has-text("Remove")')

    expect(page.get_by_text("Copy removed.")).to_be_visible()
    expect(rows).to_have_count(0)

    page.get_by_role("button", name="Undo").click()

    expect(page.get_by_text("Copy restored.")).to_be_visible()
    expect(rows).to_have_count(1)


def test_the_add_page_searches_releases_again_when_the_game_changes(
    authenticated_page: Page, live_server, e2e_library
):
    ps5 = Platform.objects.create(name="PS5", group="Sony")
    switch = Platform.objects.create(name="Switch", group="Nintendo")
    _game_on(e2e_library, "Tunic", ps5)
    hades = _game_on(e2e_library, "Hades", switch)
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_to_library')}")

    games = page.locator("search-select[name='game']")
    game_search = games.locator("[data-search-select-search]")
    game_search.click()
    game_search.fill("Hades")
    games.locator("[data-search-select-option]").first.click()

    releases = page.locator("search-select[name='release']")
    held = releases.locator('[data-search-select-pills] input[type="hidden"]')
    expect(held).to_have_value(str(Release.objects.get(edition__game=hades).pk))

    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()

    expect(page.get_by_text("Added to your library.")).to_be_visible()
    assert LibraryEntry.objects.get(library=e2e_library).player_game.game == hades
