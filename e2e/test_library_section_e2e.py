"""Every copy act, from Game detail and from the Add to library page."""

from django.urls import reverse
from graphs import default_graph
from playwright.sync_api import Page, expect
from tracked_games import create_tracked_game

from e2e.helpers import pick_choice
from games.models import Game, LibraryEntry, Platform, Release, UserLibrary


def _game_on(library: UserLibrary, name: str, platform: Platform) -> Game:
    game = create_tracked_game(library, name)
    return default_graph(game, library, platform=platform).game


def _submit(page: Page, label: str = "Save") -> None:
    with page.expect_navigation():
        page.get_by_role("button", name=label, exact=True).click()


def _save_in_dialog(page: Page, label: str = "Save") -> None:
    """Press a button in the open dialog; its save closes it and reloads."""
    dialog = page.locator("dialog[data-modal][open]")
    dialog.get_by_role("button", name=label, exact=True).click()
    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)


def _details(page: Page, scope, menu_label: str, item: str) -> None:
    page.wait_for_function("() => !!customElements.get('drop-down')")
    scope.get_by_role("button", name=menu_label).click()
    page.get_by_role("menuitem", name=item).click()


def _row_act(page: Page, row_menu: str, submenu: str, item: str) -> None:
    """Open the row's ⋮ menu, then one of its flyouts, then press ``item``."""
    page.wait_for_function("() => !!customElements.get('drop-down')")
    page.get_by_role("button", name=row_menu).click()
    page.get_by_role("menuitem", name=submenu).hover()
    page.get_by_role("menuitem", name=item).click()


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

    _details(page, section, "More ways to add to library", "Add to library…")
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
    page.get_by_label("No purchase").check()
    _submit(page, "Add to library")

    expect(page.get_by_text("Added to your library.")).to_be_visible()
    expect(rows).to_have_count(1)
    expect(section).to_contain_text("Switch")
    expect(rows.first).to_contain_text("Owned · Physical")
    entry = LibraryEntry.objects.get(library=e2e_library)
    assert entry.release_id == created.pk

    _details(page, section, "Tunic (Switch) actions", "Remove…")
    page.click('button:has-text("Remove")')

    expect(page.get_by_text("Copy removed.")).to_be_visible()
    expect(rows).to_have_count(0)

    page.get_by_role("button", name="Undo").click()

    expect(page.get_by_text("Copy restored.")).to_be_visible()
    expect(rows).to_have_count(1)

    _row_act(page, "Tunic (Switch) actions", "I no longer have it", "With details…")
    pick_choice(page.locator("dialog[data-modal][open]"), "way", "sold")
    _save_in_dialog(page)

    expect(page.get_by_text("Marked as no longer yours.")).to_be_visible()
    expect(rows).to_have_count(0)
    expect(section.get_by_text("Nothing in your library right now.")).to_be_visible()
    expect(
        section.get_by_text("There is 1 more copy previously in your library.")
    ).to_be_visible()

    with page.expect_navigation():
        section.get_by_role("link", name="1 more copy").click()
    expect(page.locator(f'[id="entry-menu-{entry.pk}"]')).to_have_count(1)


def test_one_click_gone_then_undo(authenticated_page: Page, live_server, e2e_library):
    game = _game_on(
        e2e_library, "Hades", Platform.objects.create(name="PS5", group="Sony")
    )
    page = authenticated_page
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    rows = page.locator("#library [data-summary-row]")
    with page.expect_navigation():
        page.locator("#library").get_by_role(
            "button", name="Add to library", exact=True
        ).click()

    with page.expect_navigation():
        _row_act(
            page, "Hades (PS5) actions", "I no longer have it", "Just mark it gone"
        )

    expect(page.get_by_text("Marked as no longer yours.")).to_be_visible()
    expect(rows).to_have_count(0)
    assert LibraryEntry.objects.get(library=e2e_library).access_end_way == "unstated"

    page.get_by_role("button", name="Undo").click()

    expect(rows).to_have_count(1)


def test_one_click_add_then_undo(authenticated_page: Page, live_server, e2e_library):
    game = _game_on(
        e2e_library, "Hades", Platform.objects.create(name="PS5", group="Sony")
    )
    page = authenticated_page
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    rows = page.locator("#library [data-summary-row]")

    with page.expect_navigation():
        page.locator("#library").get_by_role(
            "button", name="Add to library", exact=True
        ).click()

    expect(page.get_by_text("Added to your library.")).to_be_visible()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Owned · Digital")

    page.get_by_role("button", name="Undo").click()

    expect(page.get_by_text("Copy removed.")).to_be_visible()
    expect(rows).to_have_count(0)


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

    page.get_by_label("No purchase").check()
    _submit(page, "Add to library")

    expect(page.get_by_text("Added to your library.")).to_be_visible()
    assert LibraryEntry.objects.get(library=e2e_library).player_game.game == hades
