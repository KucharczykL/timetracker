"""Real-layout coverage for priority-plus column dropping.

The contract, stated in rendered geometry: a data table never produces
wrapper scroll at any common viewport — columns drop by priority instead —
the name column keeps its floor on mobile, and the no-JS fallback still
behaves exactly like the old positional hiding.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.urls import reverse
from playwright.sync_api import Browser, Page

from e2e.helpers import settle_layout
from games.models import (
    Device,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
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
    "so this column must not be allowed to widen the table without limit."
)

VIEWPORTS = (390, 768, 1280)

REGION_DIMENSIONS = """
() => {
    const region = document.querySelector('[role="region"][tabindex="0"]');
    return {client: region.clientWidth, scroll: region.scrollWidth};
}
"""

VISIBLE_HEADER_COUNT = """
() => [...document.querySelectorAll('thead th')].filter(
    (cell) => cell.getClientRects().length > 0
).length
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
def bundled_purchase(populated) -> None:
    """A two-game purchase: it carries the extra Split action, which widens the
    Actions column past what a single-game row needs."""
    bundle = Purchase.objects.create(
        platform=Platform.objects.first(),
        date_purchased=BASE + timedelta(days=9),
        price=4321,
        price_currency="USD",
    )
    bundle.games.add(*Game.objects.all())


def _login(page: Page, live_server, django_user_model) -> Page:
    django_user_model.objects.get_or_create(username="tester")
    user = django_user_model.objects.get(username="tester")
    user.set_password("secret123")
    user.save()
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    return _login(page, live_server, django_user_model)


@pytest.fixture
def no_js_page(live_server, browser: Browser, django_user_model):
    """The no-JS fallback path: <responsive-table> never defines, so the
    :not(:defined)-scoped positional hiding stays live. Login is a plain form
    POST, so it works without scripts."""
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    yield _login(page, live_server, django_user_model)
    context.close()


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
def test_no_wrapper_scroll_at_any_viewport(
    authenticated_page: Page, live_server, populated, url_name: str
):
    """The point of the phase: what used to overflow (purchases carried 285px
    of scroll at a 1024 viewport) now drops columns until it fits."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse(url_name)}")
    for width in VIEWPORTS:
        page.set_viewport_size({"width": width, "height": 900})
        settle_layout(page)
        dimensions = page.evaluate(REGION_DIMENSIONS)
        assert dimensions["scroll"] <= dimensions["client"] + 1, (
            f"{url_name} still scrolls at {width}px: {dimensions}"
        )


def test_name_column_keeps_the_floor_at_mobile(
    authenticated_page: Page, live_server, populated
):
    """Below md the greed squeezes the name column; the fit budget must leave
    it at least the floor rather than letting kept columns crush it."""
    page = authenticated_page
    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")
    settle_layout(page)
    name_cell_width = page.evaluate(
        "() => document.querySelector('tbody th').getBoundingClientRect().width"
    )
    assert name_cell_width >= 150, f"name column squeezed to {name_cell_width}px"


def test_columns_reappear_as_the_viewport_widens(
    authenticated_page: Page, live_server, populated
):
    """Continuous, self-tuning: the exact visible set is emergent (it depends
    on data and fonts), but more room must always mean at least as many
    columns, and the widest table must show more than mobile's."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_purchases')}")
    visible_counts = []
    for width in VIEWPORTS:
        page.set_viewport_size({"width": width, "height": 900})
        settle_layout(page)
        visible_counts.append(page.evaluate(VISIBLE_HEADER_COUNT))
    assert visible_counts == sorted(visible_counts), visible_counts
    assert visible_counts[0] < visible_counts[-1], visible_counts
    # The row header and the Actions column survive even the narrowest fit.
    assert visible_counts[0] >= 2, visible_counts


@pytest.mark.parametrize("url_name", LIST_PAGES)
def test_a_table_never_collapses_to_its_row_header(
    authenticated_page: Page, live_server, populated, url_name: str
):
    """Dropping down to the row header alone is never the better fit: it leaves
    a full-width column with its content stranded against empty space, and
    nothing left to act on."""
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse(url_name)}")
    for width in (320, 390):
        page.set_viewport_size({"width": width, "height": 900})
        settle_layout(page)
        visible = page.evaluate(VISIBLE_HEADER_COUNT)
        assert visible >= 2, f"{url_name} kept only {visible} column(s) at {width}px"


def test_actions_survive_a_multi_game_purchase(
    authenticated_page: Page, live_server, bundled_purchase
):
    """The Split action a bundle adds widens the Actions column; the fit must
    squeeze the elastic name column rather than drop the only column that
    offers interaction."""
    page = authenticated_page
    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_purchases')}")
    settle_layout(page)
    actions_header = page.locator("thead th").last
    # Rendered uppercase by the header style, so compare case-insensitively.
    assert actions_header.inner_text().strip().lower() == "actions"
    assert actions_header.is_visible(), "Actions dropped on a bundled-purchase row"
    name_width = page.evaluate(
        "() => document.querySelector('tbody th').getBoundingClientRect().width"
    )
    assert name_width >= 150, f"name column squeezed to {name_width}px"


def test_a_swapped_in_row_inherits_the_current_decision(
    authenticated_page: Page, live_server, populated
):
    """The drop state is a table-level rule precisely so a row fragment (the
    refund swap, a cloned session row) needs no knowledge of it."""
    page = authenticated_page
    page.set_viewport_size({"width": 1024, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_purchases')}")
    settle_layout(page)
    hidden_before = page.evaluate(
        """() => {
            const row = document.querySelector('tbody tr');
            const clone = row.cloneNode(true);
            row.parentElement.appendChild(clone);
            const cells = [...clone.children];
            return {
                total: cells.length,
                visible: cells.filter(
                    (cell) => cell.getClientRects().length > 0
                ).length,
                headerVisible: [...document.querySelectorAll('thead th')].filter(
                    (cell) => cell.getClientRects().length > 0
                ).length,
            };
        }"""
    )
    assert hidden_before["visible"] == hidden_before["headerVisible"]
    assert hidden_before["visible"] < hidden_before["total"]


def test_no_js_fallback_matches_the_old_positional_hiding(
    no_js_page: Page, live_server, populated
):
    """Without the element the :not(:defined) rules are today's exact
    behavior: middle columns hidden below md, everything visible above it —
    including the overflow the element exists to remove."""
    page = no_js_page
    page.goto(f"{live_server.url}{reverse('games:list_purchases')}")

    page.set_viewport_size({"width": 500, "height": 900})
    visible_narrow = page.evaluate(VISIBLE_HEADER_COUNT)
    assert visible_narrow == 2, f"expected first+last only, got {visible_narrow}"

    page.set_viewport_size({"width": 1024, "height": 900})
    visible_wide = page.evaluate(VISIBLE_HEADER_COUNT)
    total = page.evaluate("() => document.querySelectorAll('thead th').length")
    assert visible_wide == total


def test_no_js_scroll_region_still_scrolls(no_js_page: Page, live_server, populated):
    """The keyboard-reachable region earns its keep exactly here: with no JS
    nothing drops columns above md, purchases genuinely overflows, and the
    server-rendered role/tabindex make that scroll reachable."""
    page = no_js_page
    page.set_viewport_size({"width": 1024, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_purchases')}")

    region = page.get_by_role("region", name="Purchases")
    region.focus()
    scrolled = region.evaluate(
        """(element) => {
            element.scrollLeft = element.scrollWidth;
            return {left: element.scrollLeft, over: element.scrollWidth
                - element.clientWidth};
        }"""
    )
    assert scrolled["over"] > 0, "purchases no longer overflows without JS at 1024"
    assert scrolled["left"] > 0, "the region does not actually scroll"
