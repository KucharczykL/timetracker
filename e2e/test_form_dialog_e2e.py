"""A marked link opens its form page in a modal."""

import pytest
from devices import create_device
from django.urls import reverse
from playwright.sync_api import Browser, Page, Route, expect
from tracked_games import create_tracked_game

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement
from games.models import Device, Game, LibraryEntry, Platform, Release
from games.writes.libraryentry import record_entry
from games.writes.playergame import new_correlation_id
from timetracker.temporal import TemporalValue

LOGIN = ("tester", "secret123")


def _log_in(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', LOGIN[0])
    page.fill('input[name="password"]', LOGIN[1])
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def errors(page: Page) -> list[str]:
    collected: list[str] = []
    page.on(
        "console",
        lambda message: (
            collected.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: collected.append(str(error)))
    return collected


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user, errors) -> Page:
    _log_in(page, live_server)
    return page


def _mark(page: Page, selector: str, chrome: str = "") -> None:
    page.locator(selector).first.evaluate(
        "(link, chrome) => link.setAttribute('data-form-dialog', chrome)", chrome
    )


def _menu(page: Page, name: str):
    return page.get_by_role("button", name=f"{name} (Unknown) actions")


def _stamp_window(page: Page) -> None:
    page.evaluate("window.notReloaded = true")


def _not_reloaded(page: Page) -> bool:
    return page.evaluate("window.notReloaded === true")


def _open_device_edit(page: Page, live_server, device: Device) -> None:
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")
    _stamp_window(page)
    edit = f'a[href^="{reverse("games:edit_device", args=[device.pk])}"]'
    _mark(page, edit)
    _menu(page, device.name).click()
    page.locator(edit).click()
    expect(page.locator("dialog[data-modal][open]")).to_be_visible()


def test_an_edit_saves_and_swaps_the_list(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    _open_device_edit(page, live_server, deck)
    dialog = page.locator("dialog[data-modal][open]")
    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Edit device")
    dialog.locator('input[name="name"]').fill("Deck OLED")
    dialog.get_by_role("button", name="Submit", exact=True).click()

    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(page.locator("tbody tr", has_text="Deck OLED")).to_be_visible()
    assert _not_reloaded(page)
    expect(_menu(page, "Deck OLED")).to_be_focused()
    assert errors == []


def test_an_invalid_submit_stays_in_the_dialog(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    _open_device_edit(page, live_server, deck)
    dialog = page.locator("dialog[data-modal][open]")
    dialog.locator('input[name="name"]').fill("")
    dialog.locator('input[name="name"]').evaluate("input => input.required = false")
    dialog.get_by_role("button", name="Submit", exact=True).click()

    expect(dialog.locator('[aria-invalid="true"]').first).to_be_visible()
    expect(dialog).to_be_visible()
    assert Device.objects.get(pk=deck.pk).name == "Deck"
    assert errors == []


def test_escape_closes_only_the_top_dialog(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    _open_device_edit(page, live_server, deck)
    lower = page.locator("dialog[data-modal][open]")
    lower.evaluate(
        """(dialog) => {
            const link = document.createElement('a');
            link.href = '/tracker/device/add';
            link.textContent = 'New device';
            link.setAttribute('data-form-dialog', '');
            dialog.querySelector('[data-form-dialog-body]').append(link);
        }"""
    )
    lower.get_by_role("link", name="New device").click()
    expect(page.locator("dialog[data-modal][open]")).to_have_count(2)

    page.keyboard.press("Escape")
    expect(page.locator("dialog[data-modal][open]")).to_have_count(1)
    expect(lower.get_by_role("link", name="New device")).to_be_focused()
    assert errors == []


def test_a_removal_confirms_in_the_dialog(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")
    remove = f'a[href^="{reverse("games:remove_device", args=[deck.pk])}"]'
    _mark(page, remove, "bare")
    _menu(page, "Deck").click()
    page.locator(remove).click()
    dialog = page.locator("dialog[data-modal][open]")
    expect(dialog.locator("[data-form-dialog-header]")).to_have_count(0)
    dialog.get_by_role("button", name="Remove").click()

    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(page.locator("tbody tr", has_text="Deck")).to_have_count(0)
    expect(page.get_by_role("button", name="Undo")).to_be_visible()
    assert errors == []


def test_without_scripting_the_link_navigates(
    live_server, browser: Browser, e2e_user, e2e_library
):
    deck = create_device(e2e_library, "Deck")
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    _log_in(page, live_server)
    edit_url = reverse("games:edit_device", args=[deck.pk])
    list_url = f"{live_server.url}{reverse('games:list_devices')}"

    def mark_server_side(route: Route) -> None:
        response = route.fetch()
        body = response.text().replace(
            f'href="{edit_url}', f'data-form-dialog="" href="{edit_url}'
        )
        route.fulfill(response=response, body=body)

    page.route(list_url, mark_server_side)
    page.goto(list_url)
    # The menu needs scripting; the link itself does not.
    page.locator(f'a[data-form-dialog][href^="{edit_url}"]').dispatch_event("click")
    page.wait_for_url(f"{live_server.url}{edit_url}**")
    expect(page.locator('input[name="name"]')).to_have_value("Deck")
    context.close()


def _copy_got_in_2099(user, library) -> LibraryEntry:
    """Any end the form offers precedes it."""
    platform = Platform.objects.create(name="PS5", group="Sony")
    game: Game = create_tracked_game(library, "Tunic")
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
    answer = record_entry(
        user,
        EntryStatement(
            release_id=Release.objects.get(edition__game=game).pk,
            access="owned",
            format="digital",
            note="",
            acquired=ActStatement(TemporalValue.parse("2099-01-01"), ""),
        ),
        correlation_id=new_correlation_id(),
    )
    return LibraryEntry.objects.get(pk=answer.entry_id)


def test_a_refused_act_toasts_inside_the_dialog(
    authenticated_page: Page, live_server, e2e_user, e2e_library, errors
):
    page = authenticated_page
    entry = _copy_got_in_2099(e2e_user, e2e_library)
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")
    end_url = reverse("games:end_library_entry", args=[entry.pk])
    page.evaluate(
        """(href) => {
            const link = document.createElement('a');
            link.href = href;
            link.textContent = 'End access';
            link.setAttribute('data-form-dialog', '');
            document.getElementById('main-container').prepend(link);
        }""",
        end_url,
    )
    page.get_by_role("link", name="End access").click()
    dialog = page.locator("dialog[data-modal][open]")
    dialog.get_by_role("button", name="Save", exact=True).click()

    region = dialog.get_by_role("region", name="Notifications")
    expect(region).to_contain_text("acquired after that day")
    expect(dialog).to_be_visible()
    # The browser logs the 409 itself.
    assert errors and all("409 (Conflict)" in error for error in errors)


def test_add_game_continues_to_its_copy_and_a_close_refreshes(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    _stamp_window(page)
    page.evaluate(
        """(href) => {
            const link = document.createElement('a');
            link.href = href;
            link.textContent = 'New game';
            link.setAttribute('data-form-dialog', '');
            document.getElementById('main-container').prepend(link);
        }""",
        reverse("games:add_game"),
    )
    page.get_by_role("link", name="New game").click()
    dialog = page.locator("dialog[data-modal][open]")
    dialog.locator('input[name="name"]').press_sequentially("Outer Wilds")
    expect(dialog.locator('input[name="sort_name"]')).to_have_value("Outer Wilds")
    dialog.get_by_role("button", name="Submit & Add to library").click()

    expect(dialog.locator("[data-form-dialog-title]")).to_contain_text("Outer Wilds")
    # Escape may first close a focused picker's panel.
    dialog.get_by_role("button", name="Close dialog").click()
    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(page.get_by_role("link", name="Outer Wilds").first).to_be_visible()
    assert _not_reloaded(page)
    assert errors == []
