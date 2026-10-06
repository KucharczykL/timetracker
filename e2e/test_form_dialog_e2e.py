"""A marked link opens its form page in a modal."""

import pytest
from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, expect
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


def _reloaded(page: Page) -> bool:
    return page.evaluate("window.notReloaded !== true")


def _open_device_edit(page: Page, live_server, device: Device) -> None:
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")
    _stamp_window(page)
    edit = f'a[href^="{reverse("games:edit_device", args=[device.pk])}"]'
    _mark(page, edit)
    _menu(page, device.name).click()
    page.locator(edit).click()
    expect(page.locator("dialog[data-modal][open]")).to_be_visible()


def test_an_edit_saves_and_reloads_the_list(
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
    assert _reloaded(page)
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


def _warning(page: Page):
    return page.get_by_role("alertdialog", name="Unsaved changes")


def _edit_and_escape(page: Page, live_server, device: Device):
    _open_device_edit(page, live_server, device)
    dialog = page.locator("dialog[data-modal][open]").first
    dialog.locator('input[name="name"]').fill("Deck OLED")
    page.keyboard.press("Escape")
    expect(_warning(page)).to_be_visible()
    return dialog


def test_an_unchanged_edit_closes_at_once(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    _open_device_edit(page, live_server, deck)
    page.keyboard.press("Escape")
    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(_warning(page)).to_have_count(0)
    assert errors == []


def test_escape_warns_and_return_keeps_the_input(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    dialog = _edit_and_escape(page, live_server, deck)
    expect(_warning(page)).to_contain_text("Your changes are not saved.")
    keep = _warning(page).get_by_role("button", name="Return to edit")
    expect(keep).to_be_focused()
    keep.click()
    expect(_warning(page)).to_have_count(0)
    expect(dialog).to_be_visible()
    expect(dialog.locator('input[name="name"]')).to_have_value("Deck OLED")
    expect(dialog.locator('input[name="name"]')).to_be_focused()
    assert errors == []


def test_a_second_escape_returns_to_the_edit(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    dialog = _edit_and_escape(page, live_server, deck)
    page.keyboard.press("Escape")
    expect(_warning(page)).to_have_count(0)
    expect(dialog).to_be_visible()
    expect(dialog.locator('input[name="name"]')).to_have_value("Deck OLED")
    assert errors == []


def test_typing_then_escape_twice_keeps_the_edit(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    _open_device_edit(page, live_server, deck)
    dialog = page.locator("dialog[data-modal][open]").first
    name = dialog.locator('input[name="name"]')
    name.click()
    page.keyboard.press("End")
    page.keyboard.type(" OLED")
    page.keyboard.press("Escape")
    expect(_warning(page)).to_be_visible()
    page.keyboard.press("Escape")
    expect(_warning(page)).to_have_count(0)
    expect(dialog).to_be_visible()
    expect(name).to_have_value("Deck OLED")
    assert errors == []


def test_discard_closes_without_a_write(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    _edit_and_escape(page, live_server, deck)
    _warning(page).get_by_role("button", name="Discard").click()
    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    assert not _reloaded(page)
    assert Device.objects.get(pk=deck.pk).name == "Deck"
    assert errors == []


def test_save_submits_the_edit(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    _edit_and_escape(page, live_server, deck)
    _warning(page).get_by_role("button", name="Save").click()
    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(page.locator("tbody tr", has_text="Deck OLED")).to_be_visible()
    assert _reloaded(page)
    assert Device.objects.get(pk=deck.pk).name == "Deck OLED"
    assert errors == []


def test_a_removal_confirms_in_the_dialog(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")
    _stamp_window(page)
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
    assert _reloaded(page)
    assert errors == []


def test_removing_the_page_own_game_lands_on_the_list(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    game = create_tracked_game(e2e_library, "Outer Wilds")
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    remove = f'a[href^="{reverse("games:remove_game", args=[game.pk])}"]'
    _mark(page, remove)
    page.locator(remove).click()
    page.locator("dialog[data-modal][open]").get_by_role(
        "button", name="Remove"
    ).click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_games')}**")
    expect(page.get_by_text("Outer Wilds removed from your library.")).to_be_visible()
    assert errors == []


def test_a_sign_in_inside_the_dialog_keeps_the_save(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    deck = create_device(e2e_library, "Deck")
    _open_device_edit(page, live_server, deck)
    page.context.clear_cookies(name="sessionid")
    dialog = page.locator("dialog[data-modal][open]")
    dialog.get_by_role("button", name="Submit", exact=True).click()

    dialog.locator('input[name="username"]').fill(LOGIN[0])
    dialog.locator('input[name="password"]').fill(LOGIN[1])
    dialog.get_by_role("button", name="Login").click()
    name = dialog.locator('input[name="name"]')
    expect(name).to_have_value("Deck")
    name.fill("Deck OLED")
    dialog.get_by_role("button", name="Submit", exact=True).click()

    expect(page.locator("tbody tr", has_text="Deck OLED")).to_be_visible()
    assert Device.objects.get(pk=deck.pk).name == "Deck OLED"
    assert errors == []


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


def test_add_game_continues_to_its_copy_and_a_close_reloads(
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

    expect(dialog.locator("[data-form-dialog-title]")).to_have_text("Add to library")
    expect(dialog.locator('[data-field-row="game"] dd')).to_contain_text("Outer Wilds")
    # Escape may first close a focused picker's panel.
    dialog.get_by_role("button", name="Close dialog").click()
    expect(page.locator("dialog[data-modal][open]")).to_have_count(0)
    expect(page.get_by_role("link", name="Outer Wilds").first).to_be_visible()
    assert _reloaded(page)
    assert errors == []


def _mark_new_link(page: Page, href: str, text: str) -> None:
    page.evaluate(
        """([href, text]) => {
            const link = document.createElement('a');
            link.href = href;
            link.textContent = text;
            link.setAttribute('data-form-dialog', '');
            document.getElementById('main-container').prepend(link);
        }""",
        [href, text],
    )


def _game_on(library, name: str, platform: Platform) -> Game:
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
    return game


def test_a_picker_works_inside_and_the_message_follows_the_page(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    hades = _game_on(
        e2e_library, "Hades", Platform.objects.create(name="PS5", group="Sony")
    )
    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    _mark_new_link(page, reverse("games:add_to_library"), "Add a copy")
    page.get_by_role("link", name="Add a copy").click()
    dialog = page.locator("dialog[data-modal][open]")

    games = dialog.locator("search-select[name='game']")
    search = games.locator("[data-search-select-search]")
    search.click()
    search.fill("Had")
    option = games.locator("[data-search-select-option]").first
    expect(option).to_be_visible()
    page.keyboard.press("Escape")
    expect(option).to_be_hidden()
    expect(dialog).to_be_visible()
    search.fill("Hades")
    option.click()
    expect(dialog).to_be_visible()
    held = dialog.locator(
        "search-select[name='release'] [data-search-select-pills] input[type='hidden']"
    )
    expect(held).to_have_value(str(Release.objects.get(edition__game=hades).pk))

    dialog.get_by_label("No purchase").check()
    with page.expect_navigation():
        dialog.get_by_role("button", name="Add to library", exact=True).click()
    expect(page.get_by_text("Added to your library.")).to_be_visible()
    assert errors == []


def test_a_masked_field_works_inside(
    authenticated_page: Page, live_server, e2e_library, errors
):
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    _mark_new_link(page, reverse("games:add_session"), "Log a session")
    page.get_by_role("link", name="Log a session").click()
    dialog = page.locator("dialog[data-modal][open]")
    duration = dialog.locator('input[name="duration"]')
    duration.click()
    duration.press_sequentially("123456")
    expect(duration).to_have_value("12:34:56")
    expect(dialog.locator("date-time-field").first).to_be_visible()
    assert errors == []
