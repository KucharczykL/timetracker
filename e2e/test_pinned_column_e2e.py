"""Real-layout coverage for the pinned first column.

The pin is only correct if three things hold at once: the column stays put
while the rest scrolls, its surface is opaque in both themes, and it does not
swallow the panels that live inside it.

Scrolling is exercised without JavaScript. With <responsive-table> live, no
list table overflows at any width — priority-plus drops columns until it fits —
so the no-JS path above md is where every column renders at once and the region
genuinely scrolls. That is the same state a user-toggleable column set will
produce deliberately, and the CSS under test is identical in both.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.urls import reverse
from playwright.sync_api import Browser, Page, ViewportSize

from e2e.helpers import settle_layout
from games.models import Device, Game, Platform, Purchase, Session

ZONEINFO = ZoneInfo(settings.TIME_ZONE)
BASE = datetime(2025, 3, 1, 10, 0, tzinfo=ZONEINFO)

LONG_NAME = (
    "A Deliberately Extraordinary Game Name That Is Much Wider Than Any Practical "
    "Name Column And Therefore Must Be Clipped By Its Rendered Width"
)

# Wide enough that the md-gated scroll padding applies and the no-JS fallback
# shows every column; narrow enough that purchases still overflows by ~300px.
WIDE: ViewportSize = {"width": 800, "height": 900}
# The pin classes are all md:-gated (sticky, z-index, bg-inherit, the seam
# shadow) — below md the same cell is max-md:max-w-0 and nothing is pinned, so
# the panel tests need at least the md breakpoint too, not an actually-narrow
# viewport. It is wider than WIDE for one more reason: the tooltip panel holds
# LONG_NAME on a single unwrapped line (~875px rendered), and the occlusion
# probe samples the panel's own rectangle — a panel edge that falls outside
# the viewport reads as "occluded" by nothing (elementFromPoint returns null
# off-screen), which is a viewport artifact, not the defect under test.
NARROW: ViewportSize = {"width": 1100, "height": 900}

# The toast container is also role="region"; the scroll region is the focusable
# one. Same selector the shipped responsive-table suite uses.
REGION = '[role="region"][tabindex="0"]'


@pytest.fixture
def populated(db) -> None:
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    device = Device.objects.create(name="A Desktop Computer Of Some Kind", type="p")
    game = Game.objects.create(name=LONG_NAME, platform=platform, year_released=2024)
    short = Game.objects.create(name="Short", platform=platform, year_released=2023)
    # The purchase list's default sort is newest-purchased-first, so the long
    # name's purchase must be the later one to land in the first row — the
    # row the panel/occlusion tests hover.
    for index, subject in enumerate((short, game)):
        Session.objects.create(
            game=subject,
            device=device,
            timestamp_start=BASE + timedelta(days=index),
            timestamp_end=BASE + timedelta(days=index, hours=2),
        )
        purchase = Purchase.objects.create(
            platform=platform,
            date_purchased=BASE + timedelta(days=index),
            price=1234,
            price_currency="USD",
        )
        purchase.games.add(subject)


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
    """Every column renders at once, so the region overflows. Login is a plain
    form POST, so it works without scripts."""
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    yield _login(page, live_server, django_user_model)
    context.close()


def _open(page: Page, live_server, url_name: str, viewport: ViewportSize) -> None:
    page.set_viewport_size(viewport)
    page.goto(f"{live_server.url}{reverse(url_name)}")
    # <responsive-table> coalesces its column-drop decision into a later frame,
    # so a measurement taken right after a resize reads the previous one. The
    # shared helper polls the element's own settled state; on the no-JS pages
    # there is no element and it falls through to the font wait.
    settle_layout(page)


OVERFLOW = f"""
() => {{
  const region = document.querySelector('{REGION}');
  return region.scrollWidth - region.clientWidth;
}}
"""

PIN_OFFSET = f"""
() => {{
  const region = document.querySelector('{REGION}');
  const cell = document.querySelector('tbody tr th');
  return Math.round(
    cell.getBoundingClientRect().left - region.getBoundingClientRect().left
  );
}}
"""


@pytest.mark.parametrize("url_name", ["games:list_purchases", "games:list_games"])
def test_the_pinned_column_stays_at_the_regions_start_edge(
    no_js_page: Page, live_server, populated, url_name: str
):
    page = no_js_page
    _open(page, live_server, url_name, WIDE)
    assert page.evaluate(OVERFLOW) > 0, (
        "the fixture no longer overflows without JS; the pin has nothing to do "
        "and this test would pass vacuously"
    )
    at_rest = page.evaluate(PIN_OFFSET)
    page.evaluate(
        f"""() => {{
            const region = document.querySelector('{REGION}');
            region.scrollLeft = region.scrollWidth;
        }}"""
    )
    assert page.evaluate(PIN_OFFSET) == at_rest


def test_the_pinned_column_pins_to_the_right_edge_under_rtl(
    no_js_page: Page, live_server, populated
):
    """`start-0` is a logical inset: under rtl the scroll start edge is the
    right one, where a physical `left-0` would pin to the wrong side."""
    page = no_js_page
    _open(page, live_server, "games:list_purchases", WIDE)
    page.evaluate("() => document.documentElement.setAttribute('dir', 'rtl')")
    assert page.evaluate(OVERFLOW) > 0, "no overflow under rtl; nothing to measure"
    offset = page.evaluate(
        f"""() => {{
            const region = document.querySelector('{REGION}');
            const cell = document.querySelector('tbody tr th');
            // Chrome reports rtl scrollLeft as negative; this reaches the far edge.
            region.scrollLeft = -region.scrollWidth;
            return Math.round(
                region.getBoundingClientRect().right - cell.getBoundingClientRect().right
            );
        }}"""
    )
    assert offset == 0
    # The seam's offset is physical while the pin and the query are logical, so
    # it has to be mirrored or it paints into the table's edge rather than over
    # the content sliding underneath. Read the x-offset specifically: the
    # computed value is "rgba(…) 4px 0px 6px -4px", whose spread is negative in
    # both directions, so a substring test for "-4px" passes either way.
    box_shadow = "none"
    for _ in range(20):
        box_shadow = page.locator("tbody tr th").first.evaluate(
            "(node) => getComputedStyle(node).boxShadow"
        )
        if box_shadow != "none":
            break
        page.wait_for_timeout(50)
    # Tailwind emits the ring/inset placeholders as transparent layers first,
    # so the real shadow is the last one.
    offsets = re.findall(r"\)\s*(-?[\d.]+px)", box_shadow)
    assert offsets, box_shadow
    assert offsets[-1].startswith("-"), box_shadow


def test_the_seam_appears_only_once_the_region_is_scrolled(
    no_js_page: Page, live_server, populated
):
    page = no_js_page
    _open(page, live_server, "games:list_purchases", WIDE)
    assert page.evaluate(OVERFLOW) > 0, "no overflow; the seam could never appear"
    cell = page.locator("tbody tr th").first
    assert cell.evaluate("(node) => getComputedStyle(node).boxShadow") == "none"
    page.evaluate(
        f"""() => {{
            const region = document.querySelector('{REGION}');
            region.scrollLeft = region.scrollWidth;
        }}"""
    )
    # The scroll-state container query recomputes on its own rendering step,
    # not synchronously with the scroll. settle_layout has nothing to poll on
    # a no-JS page (there is no <responsive-table> to report settled), and
    # Page.wait_for_function's default rAF-driven polling never wakes on a
    # page with scripting disabled — so this polls with Playwright's own
    # timer instead, which does not depend on the page's own event loop.
    box_shadow = "none"
    for _ in range(20):
        box_shadow = cell.evaluate("(node) => getComputedStyle(node).boxShadow")
        if box_shadow != "none":
            break
        page.wait_for_timeout(50)
    assert box_shadow != "none"


def test_a_control_scrolled_under_the_pin_is_cleared_of_it_on_focus(
    no_js_page: Page, live_server, populated
):
    """The scroll padding reserves the region's start edge. A control that is
    already onscreen but painted behind the sticky pinned column reads as
    "visible enough" to the browser without that reservation, so nothing
    scrolls it clear on focus — it stays hidden under the pin. It is
    `md:`-gated, so this only holds at the wide viewport."""
    page = no_js_page
    _open(page, live_server, "games:list_purchases", WIDE)
    assert page.evaluate(OVERFLOW) > 0, "no overflow; nothing can park under the pin"
    # The price column's popover trigger is the earliest control after the
    # pinned name column. Scroll it to the pin's own midpoint so it is planted
    # behind the pin, not merely nearby.
    page.evaluate(
        f"""() => {{
            const region = document.querySelector('{REGION}');
            const control = document.querySelector('tbody tr td a, tbody tr td button');
            const pin = document.querySelector('tbody tr th').getBoundingClientRect();
            const before = control.getBoundingClientRect();
            region.scrollLeft += before.left - (pin.left + pin.width / 2);
        }}"""
    )
    overlap_probe = """() => {
        const pin = document.querySelector('tbody tr th').getBoundingClientRect();
        const control = document.querySelector('tbody tr td a, tbody tr td button');
        const box = control.getBoundingClientRect();
        return box.left < pin.right && box.right > pin.left;
    }"""
    assert page.evaluate(overlap_probe), (
        "the staged control does not sit behind the pinned column; the scroll "
        "offset above needs adjusting"
    )
    page.locator("tbody tr td a, tbody tr td button").first.focus()
    overlap = page.evaluate(
        """() => {
            const pin = document.querySelector('tbody tr th').getBoundingClientRect();
            const focused = document.activeElement.getBoundingClientRect();
            return focused.left < pin.right && focused.right > pin.left;
        }"""
    )
    assert overlap is False


@pytest.mark.parametrize("dark", [False, True])
def test_the_pinned_surface_is_opaque_in_both_themes(
    authenticated_page: Page, live_server, populated, dark: bool
):
    """A transparent sticky cell lets the scrolled columns show through it."""
    page = authenticated_page
    _open(page, live_server, "games:list_purchases", NARROW)
    if dark:
        page.evaluate("() => document.documentElement.classList.add('dark')")
    backgrounds = page.evaluate(
        """() => [
            document.querySelector('thead tr th'),
            document.querySelector('tbody tr th'),
        ].map((cell) => getComputedStyle(cell).backgroundColor)"""
    )
    for background in backgrounds:
        assert background not in ("rgba(0, 0, 0, 0)", "transparent"), backgrounds


def test_the_pinned_surface_follows_the_row_hover(
    authenticated_page: Page, live_server, populated
):
    """`bg-inherit` is what buys this: the cell has no surface of its own, so
    the row's hover state has to reach it."""
    page = authenticated_page
    _open(page, live_server, "games:list_purchases", NARROW)
    cell = page.locator("tbody tr th").first
    at_rest = cell.evaluate("(node) => getComputedStyle(node).backgroundColor")
    page.locator("tbody tr").first.hover()
    hovered = cell.evaluate("(node) => getComputedStyle(node).backgroundColor")
    assert hovered != at_rest


OCCLUSION = """
(selector) => {
  const panel = document.querySelector(selector);
  const box = panel.getBoundingClientRect();
  // Inset past --radius-base (12px): a sample right at a rounded corner
  // legitimately shows whatever is behind the corner the radius cuts away,
  // which is not the occlusion this probe is checking for.
  const inset = 14;
  let occluded = 0;
  let total = 0;
  for (let row = 0; row < 6; row++) {
    for (let column = 0; column < 4; column++) {
      const x = box.left + inset + (column * (box.width - 2 * inset)) / 3;
      const y = box.top + inset + (row * (box.height - 2 * inset)) / 5;
      total++;
      const hit = document.elementFromPoint(x, y);
      if (hit !== panel && !panel.contains(hit)) occluded++;
    }
  }
  return [occluded, total];
}
"""


def test_a_tooltip_inside_the_pinned_cell_is_not_occluded(
    authenticated_page: Page, live_server, populated
):
    """The defect this phase had to solve: a panel nested in a sticky cell is
    scoped to that cell's stacking context, so later rows paint over it.

    Purchases renders its first cell through `LinkedPurchase` → `TruncatedText`
    with `reveal="auto"`, so the tooltip exists only while the name is actually
    clipped — which the long fixture name guarantees at this width.
    """
    page = authenticated_page
    _open(page, live_server, "games:list_purchases", NARROW)
    page.locator("tbody tr th truncated-text").first.hover()
    page.locator("tbody tr th [data-pop-over-panel]").first.wait_for(state="visible")
    # The panel prefers opening above its anchor and only flips below when
    # there is not enough room — with the ordinary page headroom above the
    # first row, it never needs to. Pin it over the second row directly: that
    # is the geometry the elevation rule exists for, and it is what a taller
    # fixture or a shorter viewport would eventually produce anyway, without
    # this test depending on exactly reproducing that flip.
    page.evaluate(
        """() => {
            const panel = document.querySelector('tbody tr th [data-pop-over-panel]');
            const secondRow = document.querySelectorAll('tbody tr')[1].querySelector('th');
            const target = secondRow.getBoundingClientRect();
            panel.style.top = `${target.top + 5}px`;
            panel.style.left = `${target.left}px`;
        }"""
    )
    # The reposition above only lands where intended because the panel is
    # `position: fixed` — its offsets are viewport-relative regardless of the
    # sticky cell it is nested in. If that positioning model ever changes, the
    # panel drifts somewhere unrelated and the occlusion probe below would
    # measure nothing while still passing. Confirm it actually landed over the
    # second row before trusting the probe.
    overlaps_second_row = page.evaluate(
        """() => {
            const panel = document
                .querySelector('tbody tr th [data-pop-over-panel]')
                .getBoundingClientRect();
            const secondRow = document
                .querySelectorAll('tbody tr')[1]
                .querySelector('th')
                .getBoundingClientRect();
            return (
                panel.left < secondRow.right &&
                panel.right > secondRow.left &&
                panel.top < secondRow.bottom &&
                panel.bottom > secondRow.top
            );
        }"""
    )
    assert overlaps_second_row, (
        "the repositioned panel does not overlap the second row's pinned "
        "cell; the reposition above relies on the panel being `position: "
        "fixed`, and the occlusion probe below would be measuring nothing"
    )
    occluded, total = page.evaluate(OCCLUSION, "tbody tr th [data-pop-over-panel]")
    assert occluded == 0, f"{occluded}/{total} points occluded"


def test_the_open_panel_raises_its_host_cell_and_releases_it(
    authenticated_page: Page, live_server, populated
):
    """The elevation is keyed off the `hidden` attribute. If a panel ever hides
    itself with a class instead, the selector goes blind and the occlusion
    above comes back silently."""
    page = authenticated_page
    _open(page, live_server, "games:list_purchases", NARROW)
    cell = page.locator("tbody tr th").first
    assert cell.evaluate("(node) => getComputedStyle(node).zIndex") == "2"
    page.locator("tbody tr th truncated-text").first.hover()
    page.locator("tbody tr th [data-pop-over-panel]").first.wait_for(state="visible")
    assert cell.evaluate("(node) => getComputedStyle(node).zIndex") == "3"
    page.mouse.move(0, 0)
    page.locator("tbody tr th [data-pop-over-panel]").first.wait_for(state="hidden")
    assert cell.evaluate("(node) => getComputedStyle(node).zIndex") == "2"


def test_an_open_row_menu_is_not_covered_by_a_pinned_cell(
    authenticated_page: Page, live_server, populated
):
    """The other direction: the pin must stay under the panel strata, or it
    covers the menus of the rows it overlaps.

    This one has to be staged. The menu needs JavaScript, and with JavaScript
    the table never overflows, so the pinned column never slides over anything
    on its own. Widening the table past its region reproduces the geometry a
    column toggle will create — the same thing the design's own measurement did
    on a synthetic table.
    """
    page = authenticated_page
    _open(page, live_server, "games:list_sessions", NARROW)
    # The Name column is `shrinkable` (`w-full`): forcing the table wider hands
    # essentially all of the extra width to it, so both the pin and every later
    # column's unscrolled position grow by the same amount and their gap holds
    # steady — scrolling to the end always lands later columns back at their
    # original screen position, regardless of how much extra width is forced.
    # The forced width has to exceed that gap before the scrollable range can
    # carry a later column in from the right far enough to slide under the pin.
    page.add_style_tag(content="table { min-width: 2200px !important; }")
    toggle = page.locator("tbody tr [data-toggle]:visible").first
    assert toggle.count() > 0, (
        "expected a visible row-menu toggle in tbody tr [data-toggle] at this "
        "fixture/viewport; this test owns both, so a missing toggle means the "
        "staged premise broke, not that the environment lacks one"
    )
    toggle.click()
    menu = page.locator("tbody tr [data-menu]:not([hidden])").first
    menu.wait_for(state="visible")
    page.evaluate(
        f"""() => {{
            const region = document.querySelector('{REGION}');
            region.scrollLeft = region.scrollWidth;
        }}"""
    )
    overlaps = page.evaluate(
        """() => {
            const menu = document.querySelector('tbody tr [data-menu]:not([hidden])');
            const pin = document.querySelector('tbody tr th').getBoundingClientRect();
            const box = menu.getBoundingClientRect();
            return box.left < pin.right && box.right > pin.left;
        }"""
    )
    # Without horizontal overlap the occlusion count is trivially zero and the
    # assertion below would pass while measuring nothing.
    assert overlaps, "the open menu does not overlap the pinned column"
    occluded, total = page.evaluate(OCCLUSION, "tbody tr [data-menu]:not([hidden])")
    assert occluded == 0, f"{occluded}/{total} points occluded"
