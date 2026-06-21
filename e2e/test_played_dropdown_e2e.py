"""Browser regression tests for the "Played N times" dropdown on the game
view page (issue #70).

When the played-row control was migrated from Alpine to a custom element
(commit 1258c52), the hover highlight, the row-filling click target and a
consistent pointer cursor were lost: the interactive ``<a>``/``<button>``
shrank to its text and the ``<li>`` rows stopped carrying ``hover:bg-*``.
The visible result was: no hover highlight, a "hiccuping" hover between the
two items, a missing hand cursor on part of a row, and "+1" failing to fire
when the user clicked the row's padding rather than the text itself.

These tests assert the user-perceived behaviour at every horizontal point of
a menu row, regardless of which element ends up carrying the styling.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game

# Sample points spanning the row, including the former dead zones at the edges.
ROW_FRACTIONS = [0.02, 0.1, 0.3, 0.5, 0.7, 0.9, 0.98]


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.fixture
def game(db) -> Game:
    return Game.objects.create(name="Test Game", sort_name="test game")


def open_played_menu(page: Page, live_server, game: Game) -> None:
    page.goto(f"{live_server.url}{reverse('games:view_game', args=[game.id])}")
    page.locator("play-event-row [data-toggle]").click()
    expect(page.locator("play-event-row [data-menu]")).to_be_visible()


def add_play_row(page: Page):
    """The '<li>' wrapping the 'Played times +1' control."""
    return page.locator("play-event-row [data-menu] li").filter(has_text="+1")


def test_played_menu_row_highlights_on_hover(authenticated_page, live_server, game):
    """Hovering the '+1' row paints a (non-transparent) background.

    Reads the background of whichever element sits under the row's centre, so
    it does not care whether the highlight lives on the <li> or the control.
    """
    page = authenticated_page
    open_played_menu(page, live_server, game)
    row = add_play_row(page)

    def center_bg() -> str:
        return row.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                const node = document.elementFromPoint(
                    r.left + r.width / 2, r.top + r.height / 2);
                return getComputedStyle(node).backgroundColor;
            }"""
        )

    idle = center_bg()
    row.hover()
    page.wait_for_timeout(150)
    hovered = center_bg()

    transparent = ("rgba(0, 0, 0, 0)", "transparent")
    assert hovered not in transparent and hovered != idle, (
        f"row background did not change on hover (idle={idle!r}, hovered={hovered!r})"
    )


def test_played_menu_row_has_pointer_cursor_across_full_row(
    authenticated_page, live_server, game
):
    """Every horizontal point of the '+1' row shows a hand cursor.

    The former dead zones (row padding resolving to a handler-less <li> with
    cursor:auto) are what made the cursor flicker and disappear.
    """
    page = authenticated_page
    open_played_menu(page, live_server, game)
    row = add_play_row(page)

    cursors = row.evaluate(
        """(el, fracs) => {
            const r = el.getBoundingClientRect();
            const y = r.top + r.height / 2;
            return fracs.map(f => {
                const node = document.elementFromPoint(r.left + r.width * f, y);
                return getComputedStyle(node).cursor;
            });
        }""",
        ROW_FRACTIONS,
    )
    not_pointer = [f for f, c in zip(ROW_FRACTIONS, cursors) if c != "pointer"]
    assert not_pointer == [], (
        f"row fractions without a pointer cursor: {not_pointer} (cursors={cursors})"
    )


def test_played_plus_one_target_fills_the_row(authenticated_page, live_server, game):
    """The '+1' click target spans the whole row.

    Regression: the click handler moved onto an inner <button> that no longer
    fills the row (16px dead zone left, 30px right), so clicks on the row's
    padding land on the <li>, which has no handler, and are silently swallowed.
    """
    page = authenticated_page
    open_played_menu(page, live_server, game)
    row = add_play_row(page)

    misses = row.evaluate(
        """(el, fracs) => {
            const r = el.getBoundingClientRect();
            const y = r.top + r.height / 2;
            return fracs.filter(f => {
                const node = document.elementFromPoint(r.left + r.width * f, y);
                return !(node && (node.hasAttribute('data-add-play')
                                  || node.closest('[data-add-play]')));
            });
        }""",
        ROW_FRACTIONS,
    )
    assert misses == [], f"row fractions with no '+1' click target: {misses}"


def test_played_plus_one_fires_when_clicking_row_edge(
    authenticated_page, live_server, game
):
    """Clicking the row's right edge (its padding) still records a play."""
    page = authenticated_page
    count = page.locator("play-event-row [data-count]")

    open_played_menu(page, live_server, game)
    expect(count).to_have_text("0")

    row = add_play_row(page)
    box = row.bounding_box()
    # Click well inside the right padding — a dead zone before the fix.
    page.mouse.click(box["x"] + box["width"] - 4, box["y"] + box["height"] / 2)

    expect(count).to_have_text("1")
    assert game.playevents.count() == 1


def test_played_plus_one_refreshes_play_events_table(
    authenticated_page, live_server, game
):
    """Recording a play via '+1' updates the Play Events section in place.

    Regression: the play-event-row dispatched no event after creating the
    play, so the Play Events table and its count badge stayed stale until a
    full reload. It now dispatches 'play-added' and #playevents-container
    re-fetches itself (mirroring the history section's status-changed refresh).
    """
    page = authenticated_page
    section = page.locator("#playevents-container")

    open_played_menu(page, live_server, game)
    expect(section).to_contain_text("No play events yet.")

    page.locator("play-event-row [data-add-play]").click()

    # The section swaps itself in via htmx — no manual reload.
    expect(section).not_to_contain_text("No play events yet.")
    expect(section.locator("table tbody tr")).to_have_count(1)
