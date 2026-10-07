"""The Library tab: tabs, a facet, bulk acts and Undo, the row menu."""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect
from tracked_games import create_tracked_game

from e2e.helpers import pick_choice
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement
from games.events.libraryentry import EntryAccessValue
from games.models import Game, LibraryEntry, Platform, Release, UserLibrary
from games.writes.libraryentry import record_entry
from games.writes.playergame import new_correlation_id


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _release(library: UserLibrary, name: str, platform: Platform) -> Release:
    game: Game = create_tracked_game(library, name)
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
    return Release.objects.get(edition__game=game)


@pytest.fixture
def copies(e2e_user, e2e_library) -> list[LibraryEntry]:
    ps5 = Platform.objects.create(name="PS5", group="Sony")
    recorded = []
    pairs: tuple[tuple[str, EntryAccessValue], ...] = (
        ("Tunic", "owned"),
        ("Hades", "borrowed"),
    )
    for name, access in pairs:
        release = _release(e2e_library, name, ps5)
        answer = record_entry(
            e2e_user,
            EntryStatement(
                release_id=release.pk,
                access=access,
                format="digital",
                note="",
                acquired=ActStatement(None, ""),
            ),
            correlation_id=new_correlation_id(),
        )
        recorded.append(LibraryEntry.objects.get(pk=answer.entry_id))
    return recorded


def _formats() -> list[str]:
    return sorted(LibraryEntry.objects.values_list("format", flat=True))


def test_the_tabs_move_between_games_and_library(
    authenticated_page: Page, live_server, copies
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    tabs = page.get_by_role("navigation", name="Games")
    tabs.get_by_role("link", name="Library").click()

    page.wait_for_url(f"**{reverse('games:list_library')}")
    expect(
        page.get_by_role("navigation", name="Games").get_by_role("link", name="Library")
    ).to_have_attribute("aria-current", "page")
    expect(page.get_by_role("link", name="Add to library")).to_be_visible()


def test_the_access_facet_narrows_the_list(
    authenticated_page: Page, live_server, copies
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_library')}")

    page.locator("#quick-access-dropdownLink").click()
    page.locator(
        '#quick-access-dropdown search-select[name="access"] '
        '[data-search-select-option][data-label="Borrowed"] '
        '[data-search-select-action="include"]'
    ).click()
    page.locator(
        'quick-filter-bar [aria-label="Filter actions"] button[type="submit"]'
    ).click()

    page.wait_for_url("**filter=**")
    rows = page.locator("tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Hades")


def test_two_copies_are_edited_and_the_undo_puts_theirs_back(
    authenticated_page: Page, live_server, copies
):
    page = authenticated_page
    listed = f"{live_server.url}{reverse('games:list_library')}"
    page.goto(listed)
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name="Edit…").first.click()
    page.wait_for_load_state()

    expect(page.get_by_role("heading", name="Edit 2 copies")).to_be_visible()
    format_picker = page.locator("search-select[name='choice-format']")
    format_picker.locator("[data-search-select-search]").click()
    format_picker.get_by_role("option", name="Physical").click()
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    assert _formats() == ["physical", "physical"]

    with page.expect_navigation():
        page.get_by_role("button", name="Undo").click()

    page.wait_for_url(listed)
    assert _formats() == ["digital", "digital"]


def _ended() -> list[str | None]:
    return sorted(
        LibraryEntry.objects.values_list("access_end_way", flat=True),
        key=lambda way: way or "",
    )


def test_two_copies_end_and_the_undo_holds_them_again(
    authenticated_page: Page, live_server, copies
):
    page = authenticated_page
    listed = f"{live_server.url}{reverse('games:list_library')}"
    page.goto(listed)
    boxes = page.locator("tbody [data-selection-checkbox]")
    boxes.nth(0).click()
    boxes.nth(1).click()
    page.get_by_role("button", name="I no longer have them…").first.click()
    page.wait_for_load_state()

    expect(
        page.get_by_role("heading", name="I no longer have these 2 copies")
    ).to_be_visible()
    pick_choice(page, "choice-way", "sold")
    page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    assert _ended() == ["sold", "sold"]

    with page.expect_navigation():
        page.get_by_role("button", name="Undo").click()

    page.wait_for_url(listed)
    assert all(way in (None, "") for way in _ended())


def test_the_row_menu_opens_the_details_page_and_returns_to_the_tab(
    authenticated_page: Page, live_server, copies
):
    page = authenticated_page
    listed = f"{live_server.url}{reverse('games:list_library')}"
    page.goto(listed)
    page.wait_for_function("() => !!customElements.get('drop-down')")

    page.get_by_role("button", name="Tunic (PS5) actions").click()
    page.get_by_role("menuitem", name="I no longer have it").hover()
    page.get_by_role("menuitem", name="With details…").click()

    entry = copies[0]
    page.wait_for_url(f"**{reverse('games:end_library_entry', args=[entry.pk])}*")
    pick_choice(page, "way", "sold")
    with page.expect_navigation():
        page.get_by_role("button", name="Save", exact=True).click()

    page.wait_for_url(listed)
    entry.refresh_from_db()
    assert entry.access_end_way == "sold"


def test_an_ended_copy_is_had_again_in_one_click(
    authenticated_page: Page, live_server, copies
):
    entry = copies[0]
    page = authenticated_page
    listed = f"{live_server.url}{reverse('games:list_library')}"
    page.goto(listed)
    page.wait_for_function("() => !!customElements.get('drop-down')")
    menu = page.get_by_role("button", name="Tunic (PS5) actions")
    menu.click()
    page.get_by_role("menuitem", name="I no longer have it").hover()
    with page.expect_navigation():
        page.get_by_role("menuitem", name="Just mark it gone").click()
    expect(page.get_by_text("Marked as no longer yours.")).to_be_visible()

    menu.click()
    page.get_by_role("menuitem", name="I have it again").hover()
    with page.expect_navigation():
        page.get_by_role("menuitem", name="Just add it back").click()

    expect(page.get_by_text("Marked as yours again.")).to_be_visible()
    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None


def test_the_games_tabs_access_facet_reads_copies(
    authenticated_page: Page, live_server, copies
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    page.locator("#quick-access-dropdownLink").click()
    page.locator(
        '#quick-access-dropdown search-select[name="access"] '
        '[data-search-select-option][data-label="Borrowed"] '
        '[data-search-select-action="include"]'
    ).click()
    page.locator(
        'quick-filter-bar [aria-label="Filter actions"] button[type="submit"]'
    ).click()

    page.wait_for_url("**filter=**")
    rows = page.locator("tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Hades")
