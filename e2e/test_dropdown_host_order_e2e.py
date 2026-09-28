"""A hosted widget never outruns its host."""

import pytest
from devices import create_device
from django.urls import reverse
from playwright.sync_api import Page, Route, expect

#: Delays host evaluation, like a slow fetch.
HOST_DELAY = "await new Promise((resolve) => setTimeout(resolve, 500));\n"


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_autofocused_picker_opens_after_a_slow_host(
    authenticated_page: Page, live_server, e2e_library
):
    from tracked_games import create_tracked_game

    page = authenticated_page
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    delayed: list[int] = []

    def delay_host(route: Route) -> None:
        response = route.fetch()
        delayed.append(response.status)
        route.fulfill(response=response, body=HOST_DELAY + response.text())

    game = create_tracked_game(e2e_library, "Outer Wilds")
    create_device(e2e_library, "Steam Deck")
    page.route("**/elements/drop-down*.js", delay_host)

    page.goto(
        f"{live_server.url}{reverse('games:add_session_for_game', args=[game.pk])}"
    )

    picker = page.locator("search-select[name='device']")
    expect(picker.locator("[data-search-select-search]")).to_be_focused()
    expect(picker.locator("[data-search-select-options]")).to_be_visible()
    # Hashed or moved files skip the delay.
    assert delayed == [200]
    assert errors == []
