"""A field picker opens as a bottom sheet below 640 px."""

import pytest
from django.urls import reverse
from playwright.sync_api import Locator, Page, ViewportSize, expect

from e2e.tracked_games import create_tracked_game

pytestmark = pytest.mark.django_db(transaction=True)

LOGIN = ("tester", "secret123")
PHONE = ViewportSize(width=375, height=812)
DESKTOP = ViewportSize(width=1280, height=800)
SHEET = "dialog[data-dropdown-sheet][open]"
GAME_HOST = 'drop-down[behavior="inline-combobox"]:has(search-select[name="game"])'


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
def signed_in(live_server, page: Page, e2e_user, errors) -> Page:
    _log_in(page, live_server)
    return page


def _game_host(page: Page) -> Locator:
    host = page.locator(GAME_HOST)
    expect(host).to_have_count(1)
    return host


def _face_open(host: Locator) -> Locator:
    return host.locator("[data-search-select-face-open]")


def _held_game(page: Page) -> Locator:
    return page.locator(
        'search-select[name="game"] [data-search-select-pills] input[type="hidden"]'
    )


def _option(sheet: Locator, name: str) -> Locator:
    return sheet.locator("[data-search-select-option]").filter(has_text=name).first


def _pick_game(page: Page, host: Locator, name: str) -> None:
    _face_open(host).click()
    sheet = page.locator(SHEET)
    sheet.locator("[data-search-select-search]").press_sequentially(name)
    _option(sheet, name).click()
    expect(page.locator(SHEET)).to_have_count(0)


def _add_session(page: Page, live_server, viewport: ViewportSize) -> Locator:
    page.set_viewport_size(viewport)
    page.goto(f"{live_server.url}{reverse('games:add_session')}")
    return _game_host(page)


def test_a_pick_in_the_sheet_closes_it_and_shows_on_the_face(
    signed_in: Page, live_server, e2e_library, errors
):
    game = create_tracked_game(e2e_library, "Outer Wilds")
    page = signed_in
    host = _add_session(page, live_server, PHONE)
    face = _face_open(host)
    expect(face).to_be_visible()
    expect(host.locator("[data-search-select-search]")).to_be_hidden()

    face.click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible()
    expect(sheet.locator("[data-dropdown-sheet-title]")).to_have_text("Game")
    box = sheet.locator("[data-search-select-search]")
    expect(box).to_be_focused()
    expect(face).to_have_attribute("aria-expanded", "true")

    box.press_sequentially("Outer")
    _option(sheet, "Outer Wilds").click()

    expect(page.locator(SHEET)).to_have_count(0)
    expect(_held_game(page)).to_have_value(str(game.pk))
    expect(host.locator("[data-search-select-face-value]")).to_contain_text(
        "Outer Wilds"
    )
    expect(face).to_be_focused()
    expect(face).to_have_attribute("aria-expanded", "false")
    assert errors == []


def test_the_face_names_its_field_and_clears_in_one_tap(
    signed_in: Page, live_server, e2e_library, errors
):
    create_tracked_game(e2e_library, "Celeste")
    page = signed_in
    host = _add_session(page, live_server, PHONE)
    _pick_game(page, host, "Celeste")
    expect(
        page.get_by_role("button", name="Game, Celeste (Unspecified)", exact=True)
    ).to_be_visible()

    host.locator("[data-search-select-face-clear]").click()

    expect(page.locator(SHEET)).to_have_count(0)
    expect(_held_game(page)).to_have_count(0)
    expect(host.locator("[data-search-select-face-clear]")).to_be_hidden()
    expect(_face_open(host)).to_be_focused()
    assert errors == []


def test_escape_closes_the_sheet_and_keeps_the_value(
    signed_in: Page, live_server, e2e_library, errors
):
    game = create_tracked_game(e2e_library, "Tunic")
    page = signed_in
    host = _add_session(page, live_server, PHONE)
    _pick_game(page, host, "Tunic")
    _face_open(host).click()
    page.keyboard.press("Escape")

    expect(page.locator(SHEET)).to_have_count(0)
    expect(_held_game(page)).to_have_value(str(game.pk))
    expect(host.locator("search-select")).to_have_count(1)
    expect(_face_open(host)).to_be_focused()
    assert errors == []


def test_the_presets_panel_opens_as_a_sheet(signed_in: Page, live_server, errors):
    page = signed_in
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")
    page.get_by_role("button", name="Presets", exact=True).click()
    sheet = page.locator(SHEET)
    expect(sheet).to_be_visible()
    expect(sheet.locator("[data-dropdown-sheet-title]")).to_have_text("Presets")
    expect(sheet.locator("[data-search-select-search]")).to_be_focused()
    assert errors == []


def test_wide_the_list_stays_anchored(
    signed_in: Page, live_server, e2e_library, errors
):
    create_tracked_game(e2e_library, "Hades")
    page = signed_in
    host = _add_session(page, live_server, DESKTOP)
    expect(_face_open(host)).to_be_hidden()
    host.locator("[data-search-select-search]").click()

    expect(host.locator("[data-search-select-panel]")).to_be_visible()
    expect(page.locator(SHEET)).to_have_count(0)
    assert errors == []
