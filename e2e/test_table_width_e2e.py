"""Real-layout coverage for the data-table width policy.

The contract is stated in rendered lines, not in classes: a data table's cells
occupy exactly one line at every viewport, and the horizontal scroll that
buys is reachable from the keyboard.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import (
    Device,
    Game,
    GameStatusChange,
    PlayEvent,
    Platform,
    Purchase,
    Session,
)

ZONEINFO = ZoneInfo(settings.TIME_ZONE)
BASE = datetime(2025, 3, 1, 10, 0, tzinfo=ZONEINFO)

LONG_NAME = (
    "A Deliberately Extraordinary Game Name That Is Much Wider Than Any Practical "
    "Name Column And Therefore Must Be Clipped By Its Rendered Width"
)
LONG_NOTE = (
    "A note long enough to need several lines: free text has no natural width, "
    "so this column is the one place a data table is allowed to grow downward "
    "instead of sideways."
)

VIEWPORTS = (390, 768, 1280)

# Counting rendered lines has to walk text nodes, not elements: the sessions
# DATE cell holds bare text with no element of its own, and a per-cell Range
# picks up whitespace-only nodes between cells and reports them as extra lines.
COUNT_WRAPPED_CELLS = """
(excludedColumns) => {
    const wrapped = [];
    for (const table of document.querySelectorAll('[role="region"] table')) {
        const headers = [...table.querySelectorAll('thead th')].map(
            (th) => th.textContent.trim()
        );
        for (const cell of table.querySelectorAll('tbody th, tbody td')) {
            const label = headers[cell.cellIndex] ?? '';
            if (excludedColumns.includes(label)) continue;
            if (cell.getClientRects().length === 0) continue;  // hidden column
            const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
            for (let node = walker.nextNode(); node; node = walker.nextNode()) {
                if (!node.textContent.trim()) continue;
                const range = document.createRange();
                range.selectNodeContents(node);
                const tops = new Set(
                    [...range.getClientRects()]
                        .filter((rect) => rect.width > 0)
                        .map((rect) => Math.round(rect.top))
                );
                if (tops.size > 1) {
                    wrapped.push(`${label || '(row header)'}: ` +
                        `${node.textContent.trim().slice(0, 40)}`);
                }
            }
        }
    }
    return wrapped;
}
"""


@pytest.fixture
def populated(db) -> None:
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    device = Device.objects.create(name="A Desktop Computer Of Some Kind", type="p")
    game = Game.objects.create(name=LONG_NAME, platform=platform, year_released=2024)
    short = Game.objects.create(name="Short", platform=platform, year_released=2023)
    Session.objects.create(
        game=game,
        device=device,
        timestamp_start=BASE,
        timestamp_end=BASE + timedelta(hours=2),
        note="a session note",
    )
    Session.objects.create(
        game=short,
        device=device,
        timestamp_start=BASE + timedelta(days=1),
        timestamp_end=BASE + timedelta(days=1, hours=1),
    )
    # One refunded, one not, so both renderings of the Refunded column appear.
    for index, purchased_game in enumerate((game, short)):
        purchase = Purchase.objects.create(
            platform=platform,
            date_purchased=BASE + timedelta(days=index),
            date_refunded=BASE + timedelta(days=index + 5) if index == 0 else None,
            price=1234,
            price_currency="USD",
        )
        purchase.games.add(purchased_game)
    PlayEvent.objects.create(
        game=game, started=BASE, ended=BASE + timedelta(days=3), note=LONG_NOTE
    )
    GameStatusChange.objects.create(game=game, new_status="p", timestamp=BASE)


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


LIST_PAGES = [
    "games:list_sessions",
    "games:list_games",
    "games:list_purchases",
    "games:list_playevents",
    "games:list_devices",
    "games:list_platforms",
    "games:list_statuschanges",
]


@pytest.mark.parametrize("url_name", LIST_PAGES)
def test_no_data_table_cell_wraps_at_any_viewport(
    authenticated_page: Page, live_server, populated, url_name: str
):
    """Purchases is the hard case — the widest natural column total of the set,
    so it is the first to run out of room and the first to wrap."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse(url_name)}")
    for width in VIEWPORTS:
        page.set_viewport_size({"width": width, "height": 900})
        page.evaluate("() => document.fonts.ready")
        # Note is the one column allowed to wrap; see the test below.
        wrapped = page.evaluate(COUNT_WRAPPED_CELLS, ["Note"])
        assert wrapped == [], f"{url_name} wraps at {width}px: {wrapped}"


def test_no_game_detail_mini_table_cell_wraps(
    authenticated_page: Page, live_server, populated
):
    """The detail page stacks three data tables inside a narrower column than
    any list page gets, so it is where the rule is under the most pressure."""
    page = authenticated_page
    game = Game.objects.get(name=LONG_NAME)
    page.goto(f"{live_server.url}{reverse('games:view_game', args=[game.pk])}")
    for width in VIEWPORTS:
        page.set_viewport_size({"width": width, "height": 900})
        page.evaluate("() => document.fonts.ready")
        wrapped = page.evaluate(COUNT_WRAPPED_CELLS, ["Note"])
        assert wrapped == [], f"game detail wraps at {width}px: {wrapped}"


def test_the_note_column_still_wraps(authenticated_page: Page, live_server, populated):
    """The opt-out has to be real, not vacuous: with a realistic note the column
    must take several lines rather than widening the table without limit."""
    page = authenticated_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_playevents')}")
    page.evaluate("() => document.fonts.ready")

    lines = page.evaluate(
        """() => {
            const headers = [...document.querySelectorAll('thead th')].map(
                (th) => th.textContent.trim()
            );
            const index = headers.indexOf('Note');
            const cell = document.querySelectorAll('tbody tr')[0].children[index];
            const range = document.createRange();
            range.selectNodeContents(cell);
            return new Set(
                [...range.getClientRects()]
                    .filter((rect) => rect.width > 0)
                    .map((rect) => Math.round(rect.top))
            ).size;
        }"""
    )
    assert lines > 1, "the wrap opt-out is not taking effect"


def test_scroll_region_is_reachable_and_named(
    authenticated_page: Page, live_server, populated
):
    """The region's accessibility contract with the app fully running. With
    <responsive-table> active the table rarely overflows — columns drop
    instead — so the actually-scrolls proof lives in
    test_responsive_table_e2e.py's no-JS test, where the overflow is real."""
    page = authenticated_page
    page.set_viewport_size({"width": 1024, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_purchases')}")
    page.evaluate("() => document.fonts.ready")

    # By role and name, so the visually hidden caption is proven to survive the
    # browser's own accessible-name computation rather than just being present.
    region = page.get_by_role("region", name="Purchases")
    expect(region).to_have_attribute("tabindex", "0")

    region.focus()
    assert page.evaluate(
        "() => document.activeElement.getAttribute('role') === 'region'"
    )
