"""Clear × by keyboard and by pointer."""

import pytest
from devices import create_device
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from playwright.sync_api import Page, expect

from common.components import SearchSelect


def multi_harness_view(request):
    widget = SearchSelect(
        name="tags",
        selected=[
            {"value": "1", "label": "Apple", "data": {}},
            {"value": "2", "label": "Banana", "data": {}},
        ],
        options=[
            {"value": "1", "label": "Apple", "data": {}},
            {"value": "2", "label": "Banana", "data": {}},
            {"value": "3", "label": "Cherry", "data": {}},
        ],
        multi_select=True,
        id="tags",
        host_dropdown=True,
    )
    return HttpResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="icon" href="data:,">
        <link rel="stylesheet" href="/static/base.css">
        <script type="module" src="/static/js/dist/elements/search-select.js"></script>
        <script type="module" src="/static/js/dist/elements/drop-down.js"></script>
    </head>
    <body>
        <form style="padding: 50px;">
            {widget}
            <input type="text" id="next-field" />
        </form>
    </body>
    </html>
    """)


urlpatterns = [path("clear-multi/", multi_harness_view)]


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    return errors


START_FIELD = 'date-time-field[field-name="started_at"]'


def _fill_start(page: Page) -> None:
    """A start alone makes a running session."""
    for part, value in (
        ("year", "2026"),
        ("month", "01"),
        ("day", "02"),
        ("hour", "10"),
        ("minute", "30"),
    ):
        page.locator(f'{START_FIELD} input[data-date-part="{part}"]').click()
        page.keyboard.type(value)


def _session_form_holding_a_device(page: Page, live_server, library):
    from tracked_games import create_tracked_game

    game = create_tracked_game(library, "Outer Wilds")
    create_device(library, "Steam Deck")
    page.goto(
        f"{live_server.url}{reverse('games:add_session_for_game', args=[game.pk])}"
    )
    picker = page.locator("search-select[name='device']")
    search = picker.locator("[data-search-select-search]")
    search.click()
    picker.locator("[data-search-select-option]", has_text="Steam Deck").click()
    expect(picker.locator('input[type="hidden"][name="device"]')).to_have_count(1)
    return picker, search


def test_keyboard_clears_the_device_and_the_form_posts_none(
    authenticated_page: Page, live_server, e2e_library, console_errors
):
    from games.models import PlayerSession

    page = authenticated_page
    picker, search = _session_form_holding_a_device(page, live_server, e2e_library)
    clear = picker.get_by_role("button", name="Clear")

    search.focus()
    page.keyboard.press("Tab")
    expect(clear).to_be_focused()
    expect(picker.locator("[data-search-select-options]")).to_be_hidden()

    page.keyboard.press("Enter")
    expect(search).to_have_value("")
    expect(search).to_be_focused()
    expect(clear).to_be_hidden()

    _fill_start(page)
    with page.expect_navigation():
        page.get_by_role("button", name="Submit", exact=True).click()
    assert PlayerSession.objects.get(library=e2e_library).device_id is None
    assert console_errors == []


def test_pointer_clears_the_device_and_leaves_focus_alone(
    authenticated_page: Page, live_server, e2e_library, console_errors
):
    page = authenticated_page
    picker, search = _session_form_holding_a_device(page, live_server, e2e_library)
    note = page.locator("textarea[name='note']")
    note.focus()

    picker.get_by_role("button", name="Clear").click()
    expect(search).to_have_value("")
    expect(picker.locator('input[type="hidden"][name="device"]')).to_have_count(0)
    expect(note).to_be_focused()
    assert console_errors == []


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_clear_e2e")
def test_keyboard_clears_every_pill(live_server, page: Page, console_errors):
    page.goto(live_server.url + "/clear-multi/")
    picker = page.locator("search-select[name='tags']")
    expect(picker.locator("[data-pill]")).to_have_count(2)

    page.locator("#tags").focus()
    page.keyboard.press("Tab")
    expect(picker.get_by_role("button", name="Clear")).to_be_focused()
    page.keyboard.press("Space")

    expect(picker.locator("[data-pill]")).to_have_count(0)
    expect(picker.locator('input[type="hidden"]')).to_have_count(0)
    expect(page.locator("#tags")).to_be_focused()
    assert console_errors == []


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_clear_e2e")
def test_pointer_clears_every_pill_and_leaves_focus_alone(
    live_server, page: Page, console_errors
):
    page.goto(live_server.url + "/clear-multi/")
    picker = page.locator("search-select[name='tags']")
    page.locator("#next-field").focus()

    picker.get_by_role("button", name="Clear").click()

    expect(picker.locator("[data-pill]")).to_have_count(0)
    expect(page.locator("#next-field")).to_be_focused()
    assert console_errors == []


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_select_clear_e2e")
def test_a_disabled_box_hides_the_clear_button(live_server, page: Page):
    page.goto(live_server.url + "/clear-multi/")
    clear = page.locator("search-select[name='tags']").get_by_role(
        "button", name="Clear"
    )
    expect(clear).to_be_visible()

    page.locator("#tags").evaluate("box => { box.disabled = true; }")
    expect(clear).to_be_hidden()
