"""The real session list on a phone.

The synthetic selectable-table suite proves the stacked cell against a
table it builds itself. This proves the list view writes one: the
summary the view states, at a width where every column but the pinned
one has dropped.
"""

import datetime as dt

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect
from session_rows import timed_row, tracked_run

from games.filters import PlayerSessionFilter, filter_url
from games.models import Device, Game, Platform

PHONE = {"width": 375, "height": 812}

STARTED_AT = dt.datetime(2026, 3, 5, 10, tzinfo=dt.UTC)

#: Where the checkbox landed, and how far off the name it is.
CHECKBOX_PLACEMENT = """
() => {
    const identity = document.querySelector('tbody th [data-row-identity]');
    const box = identity.querySelector('[data-selection-checkbox]');
    const name = identity.querySelector('a, span');
    const middle = (shape) => shape.top + shape.height / 2;
    return {
        insideTheIdentityRow: identity.contains(box),
        insideTheSummary: !!document
            .querySelector('tbody th [data-row-summary]')
            ?.contains(box),
        offBy: Math.abs(
            middle(box.getBoundingClientRect())
            - middle(name.getBoundingClientRect())
        ),
    };
}
"""


@pytest.fixture
def one_game_played(e2e_library):
    """One game, two sessions, one of them on a device."""
    platform = Platform.objects.create(
        library=e2e_library, name="PC", icon="pc", group="PC"
    )
    game = Game.objects.create(library=e2e_library, name="Tunic", platform=platform)
    device = Device.objects.create(library=e2e_library, name="Steam Deck")
    run = tracked_run(e2e_library, game)
    timed_row(run, STARTED_AT, STARTED_AT + dt.timedelta(hours=1), device=device)
    timed_row(
        run,
        STARTED_AT + dt.timedelta(days=1),
        STARTED_AT + dt.timedelta(days=1, hours=2),
    )
    return game


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _organized(live_server, game) -> str:
    return live_server.url + filter_url(
        PlayerSessionFilter.where(game=[game.id]), sort="playthrough"
    )


def test_the_summary_names_the_run_where_the_column_has_dropped(
    authenticated_page: Page, live_server, one_game_played
):
    """Below md the Playthrough column is gone with the rest."""
    page = authenticated_page
    page.goto(_organized(live_server, one_game_played))

    summary = page.locator("tbody th [data-row-summary]").first
    expect(summary).to_contain_text("Playthrough 1")
    expect(summary).to_contain_text("Steam Deck")
    #: The column itself has dropped, so nothing else names the run.
    expect(page.locator("tbody td").first).to_be_hidden()


def test_the_checkbox_sits_beside_the_name_not_across_both_lines(
    authenticated_page: Page, live_server, one_game_played
):
    page = authenticated_page
    page.goto(_organized(live_server, one_game_played))
    page.locator("[data-selection-bar] [data-selection-toggle]").first.click()
    page.wait_for_selector("tbody [data-selection-checkbox]")

    placed = page.evaluate(CHECKBOX_PLACEMENT)

    assert placed["insideTheIdentityRow"]
    assert not placed["insideTheSummary"]
    #: Centred on the name, not on the two-line cell.
    assert placed["offBy"] < 4
