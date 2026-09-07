"""Browser regression tests for the "Played N times" dropdown on the game
view page (issue #70).

When the played-row control was migrated from Alpine to a custom element
(commit 1258c52), the hover highlight, the row-filling click target and a
consistent pointer cursor were lost: the interactive ``<a>``/``<button>``
shrank to its text and the ``<li>`` rows stopped carrying ``hover:bg-*``.
The visible result was: no hover highlight, a "hiccuping" hover between the
two items, a missing hand cursor on part of a row, and a click landing on
the row's padding rather than the text doing nothing.

These tests assert the user-perceived behaviour at every horizontal point of
a menu row, regardless of which element ends up carrying the styling. #687
took the "+1" action away, so they read the one item the menu still holds.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game

# Sample points spanning the row, including the former dead zones at the edges.
ROW_FRACTIONS = [0.02, 0.1, 0.3, 0.5, 0.7, 0.9, 0.98]


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.fixture
def game(e2e_library) -> Game:
    return Game.objects.create(
        library=e2e_library, name="Test Game", sort_name="test game"
    )


def open_played_menu(page: Page, live_server, game: Game) -> None:
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    page.locator(f'[aria-controls="played-{game.id}"]').click()
    expect(page.locator(f'[id="played-{game.id}"]')).to_be_visible()


def add_playthrough_row(page: Page, game: Game):
    """The '<li>' wrapping the 'Add playthrough...' link."""
    return page.locator(f'[id="played-{game.id}"] li').filter(
        has_text="Add playthrough"
    )


def test_played_menu_row_highlights_on_hover(authenticated_page, live_server, game):
    """Hovering the menu row paints a (non-transparent) background.

    Reads the background of whichever element sits under the row's centre, so
    it does not care whether the highlight lives on the <li> or the control.
    """
    page = authenticated_page
    open_played_menu(page, live_server, game)
    row = add_playthrough_row(page, game)

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
    """Every horizontal point of the menu row shows a hand cursor.

    The former dead zones (row padding resolving to a handler-less <li> with
    cursor:auto) are what made the cursor flicker and disappear.
    """
    page = authenticated_page
    open_played_menu(page, live_server, game)
    row = add_playthrough_row(page, game)

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


def test_played_menu_link_target_fills_the_row(authenticated_page, live_server, game):
    """The menu item's click target spans the whole row.

    Regression: the click target moved onto an inner control that no longer
    fills the row (16px dead zone left, 30px right), so clicks on the row's
    padding land on the <li>, which does nothing, and are silently swallowed.
    """
    page = authenticated_page
    open_played_menu(page, live_server, game)
    row = add_playthrough_row(page, game)

    misses = row.evaluate(
        """(el, fracs) => {
            const r = el.getBoundingClientRect();
            const y = r.top + r.height / 2;
            return fracs.filter(f => {
                const node = document.elementFromPoint(r.left + r.width * f, y);
                return !(node && node.closest('a[role="menuitem"]'));
            });
        }""",
        ROW_FRACTIONS,
    )
    assert misses == [], f"row fractions with no click target: {misses}"
