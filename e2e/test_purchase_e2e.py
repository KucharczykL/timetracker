"""The purchase segment, the copy's refund, and name tooltips."""

from decimal import Decimal

import pytest
from django.urls import reverse
from entries import record_entry
from graphs import default_graph
from playwright.sync_api import Page, expect
from purchases import record_purchase

from games.models import Game, Platform, Purchase


@pytest.fixture
def authenticated_page(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_the_price_segment_shows_only_the_rows_it_reads(
    authenticated_page: Page, live_server, e2e_library
):
    game = default_graph(Game(library=e2e_library, name="Tunic"), e2e_library).game
    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:add_library_entry', args=[game.pk])}")
    amount = page.locator('[data-field-row="amount"]')
    currency = page.locator('[data-field-row="currency"]')

    expect(amount).to_be_visible()
    expect(currency).to_be_visible()
    page.get_by_label("Free", exact=True).check()
    expect(amount).to_be_hidden()
    expect(currency).to_be_visible()
    page.get_by_label("No purchase", exact=True).check()
    expect(amount).to_be_hidden()
    expect(currency).to_be_hidden()

    page.get_by_label("Paid", exact=True).check()
    page.locator('input[name="amount"]').fill("24.50")
    page.locator('input[name="currency"]').fill("EUR")
    with page.expect_navigation():
        page.get_by_role("button", name="Add to library", exact=True).click()

    purchase = Purchase.objects.get(entry__player_game__game=game)
    assert (purchase.amount, purchase.currency) == (Decimal("24.50"), "EUR")


def test_the_copy_menu_refunds_and_undo_takes_it_back(
    authenticated_page: Page, live_server, e2e_library
):
    ps5 = Platform.objects.create(name="PS5", group="Sony")
    graph = default_graph(
        Game(library=e2e_library, name="Tunic"), e2e_library, platform=ps5
    )
    purchase = record_purchase(record_entry(e2e_library, graph.release))
    page = authenticated_page
    page.goto(f"{live_server.url}{graph.game.get_absolute_url()}")
    page.wait_for_function("() => !!customElements.get('drop-down')")

    page.get_by_role("button", name="Tunic (PS5) actions").click()
    page.get_by_role("menuitem", name="Bought · 19.99 EUR").hover()
    with page.expect_navigation():
        page.get_by_role("menuitem", name="Refund").click()

    expect(
        page.locator("#library").get_by_text("Nothing in your library")
    ).to_be_visible()
    purchase.refresh_from_db()
    assert purchase.refund_recorded_at is not None

    with page.expect_navigation():
        page.locator("toast-stack").get_by_role("button", name="Undo").click()

    expect(page.locator("#library [data-summary-detail]")).to_contain_text("Bought")
    purchase.refresh_from_db()
    assert purchase.refund_recorded_at is None


@pytest.fixture
def touch_page(live_server, browser, e2e_user):
    """A logged-in page in a touch, no-hover mobile context (so locator.tap()
    works, pointer events report pointerType "touch", and `(hover: none)` matches
    — the reveal button is shown only where the device can't hover)."""
    context = browser.new_context(
        has_touch=True, is_mobile=True, viewport={"width": 390, "height": 844}
    )
    page = context.new_page()
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    # Tap, never click: a click parks the virtual mouse on the
    # button, and the next page opens whatever tooltip loads
    # under it. A no-hover device has no cursor to park.
    page.tap('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    yield page
    context.close()


def test_name_popover_shows_on_hover(
    authenticated_page: Page, live_server, e2e_library
):
    """On a hover-capable (desktop) device the tap reveal button is hidden, and
    hovering the NAME (the link) opens the tooltip — the whole host opens on
    hover, so the hover surface is the visible name, not a glyph (#445 M1)."""
    page = authenticated_page
    platform = Platform.objects.create(
        library=e2e_library, name="PC", icon="steam", group="PC"
    )
    Game.objects.create(
        library=e2e_library,
        name=(
            "A Very Long Game Name That Exceeds Every Practical Desktop Column "
            "Width And Must Be Clipped By The Browser"
        ),
        platform=platform,
    )

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    name_link = page.locator("truncated-text a").first
    panel = page.locator("truncated-text [data-pop-over-panel]").first
    # The reveal button is mobile-only (shown only where the device can't hover).
    expect(page.locator("truncated-text [data-truncated-reveal]").first).to_be_hidden()

    expect(panel).to_be_hidden()
    name_link.hover()
    expect(panel).to_be_visible()
    expect(panel.locator("[data-pop-over-arrow]")).to_be_visible()
    page.mouse.move(0, 0)
    expect(panel).to_be_hidden()


def test_name_popover_taps_open_on_touch(touch_page: Page, live_server, e2e_library):
    """On touch (no hover) a tap on the glyph trigger toggles the tooltip; a tap
    elsewhere dismisses it. The link is a sibling of the trigger, so this reveal
    path never fights the link's own navigation."""
    page = touch_page
    platform = Platform.objects.create(
        library=e2e_library, name="PC", icon="steam", group="PC"
    )
    Game.objects.create(
        library=e2e_library,
        name=(
            "A Very Long Game Name That Exceeds Every Practical Mobile Column "
            "Width And Must Be Clipped By The Browser"
        ),
        platform=platform,
    )

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    trigger = page.locator("truncated-text [data-truncated-reveal]").first
    panel = page.locator("truncated-text [data-pop-over-panel]").first

    expect(panel).to_be_hidden()
    trigger.tap()
    expect(panel).to_be_visible()
    # A tap on empty page space dismisses (pointerdown outside the host).
    page.touchscreen.tap(2, 2)
    expect(panel).to_be_hidden()
