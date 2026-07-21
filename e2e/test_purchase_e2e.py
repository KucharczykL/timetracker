"""Browser tests for the purchase pricing UX and the split action.

- A synthetic page isolates the general ``selection-fields`` element (no API,
  deterministic option values), mirroring ``test_search_select_e2e.py``.
- The real-app tests drive the actual add-purchase form and the split modal
  against pytest-django's ``live_server``.
"""

from datetime import date

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from playwright.sync_api import Page, expect

from common.components import SearchSelect, SelectionFields
from games.models import Game, Platform, Purchase


def selection_fields_view(request):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="/static/js/htmx.min.js"></script>
        <script type="module" src="/static/js/dist/elements/search-select.js"></script>
        <script type="module" src="/static/js/dist/elements/selection-fields.js"></script>
    </head>
    <body>
        <div style="padding: 50px;">
            {
        SearchSelect(
            name="games",
            selected=[],
            options=[
                {"value": "7", "label": "Game A", "data": {}},
                {"value": "8", "label": "Game B", "data": {}},
            ],
            multi_select=True,
        )
    }
            {
        SelectionFields(
            source="games",
            name_prefix="price_for_game_",
            field_type="number",
            min_items=2,
            active=True,
        )
    }
        </div>
    </body>
    </html>
    """
    return HttpResponse(html)


urlpatterns = [
    path("sf-test/", selection_fields_view),
]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_purchase_e2e")
def test_selection_fields_syncs_with_source(live_server, page: Page):
    page.goto(live_server.url + "/sf-test/")

    games = page.locator('search-select[name="games"]')
    rows = page.locator("selection-fields [data-selection-fields-rows] input")

    # Below min_items (2): nothing rendered.
    expect(rows).to_have_count(0)

    games.locator("[data-search-select-search]").click()
    games.locator('[data-search-select-option][data-value="7"]').click()
    expect(rows).to_have_count(0)  # only one selected, still below min_items

    games.locator("[data-search-select-search]").click()
    games.locator('[data-search-select-option][data-value="8"]').click()
    expect(rows).to_have_count(2)

    # One input per item, named by the prefix + item id.
    expect(
        page.locator('selection-fields input[name="price_for_game_7"]')
    ).to_have_count(1)
    expect(
        page.locator('selection-fields input[name="price_for_game_8"]')
    ).to_have_count(1)

    # Typed values survive removing and re-adding another item.
    page.locator('selection-fields input[name="price_for_game_7"]').fill("12")
    games.locator('[data-pill][data-value="8"] [data-pill-remove]').click()
    expect(rows).to_have_count(0)
    games.locator("[data-search-select-search]").click()
    games.locator('[data-search-select-option][data-value="8"]').click()
    expect(rows).to_have_count(2)
    expect(
        page.locator('selection-fields input[name="price_for_game_7"]')
    ).to_have_value("12")


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def _select_two_games(page: Page) -> None:
    games = page.locator('search-select[name="games"]')
    games.locator("[data-search-select-search]").click()
    options = games.locator("[data-search-select-option]")
    expect(options).to_have_count(2)  # prefetched on focus
    options.nth(0).click()
    options.nth(1).click()


def test_add_purchase_per_game_toggle_reveals_inputs(
    authenticated_page: Page, live_server
):
    """The combined/per-game toggle appears only at 2+ games; turning it on
    hides the bundle Price and shows one price input per selected game.
    (Server-side creation of N purchases is covered by the unit tests.)"""
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(name="Alpha Game", platform=platform)
    Game.objects.create(name="Beta Game", platform=platform)

    page.goto(f"{live_server.url}{reverse('games:add_purchase')}")

    checkbox_row = page.locator("#separate-prices-row")
    expect(checkbox_row).to_be_hidden()

    _select_two_games(page)
    expect(checkbox_row).to_be_visible()

    page.locator("#id_separate_prices").check()
    expect(page.locator("#id_price")).to_be_hidden()
    per_game_inputs = page.locator(
        "selection-fields [data-selection-fields-rows] input"
    )
    expect(per_game_inputs).to_have_count(2)


def test_split_purchase_action(authenticated_page: Page, live_server):
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game_a = Game.objects.create(name="Alpha Game", platform=platform)
    game_b = Game.objects.create(name="Beta Game", platform=platform)
    bundle = Purchase.objects.create(
        price=30.0,
        price_currency="USD",
        date_purchased=date(2025, 1, 1),
        platform=platform,
        ownership_type=Purchase.DIGITAL,
        type=Purchase.GAME,
    )
    bundle.games.set([game_a, game_b])

    page.goto(f"{live_server.url}{reverse('games:list_purchases')}")
    # Before: one bundle row.
    expect(page.locator('[id^="purchase-row-"]')).to_have_count(1)

    page.locator('[title="Split into per-game purchases"]').click()
    modal = page.locator("#split-confirmation-modal")
    expect(modal).to_be_visible()
    modal.locator('button[type="submit"]', has_text="Split").click()

    page.wait_for_url(f"{live_server.url}{reverse('games:list_purchases')}**")
    # After: the bundle row is gone, replaced by two per-game rows. Asserted via
    # the UI (not the ORM) to avoid live_server/SQLite write-read contention.
    expect(page.locator(f"#purchase-row-{bundle.id}")).to_have_count(0)
    expect(page.locator('[id^="purchase-row-"]')).to_have_count(2)


def test_split_modal_dismisses_on_escape_and_backdrop(
    authenticated_page: Page, live_server
):
    """The confirm modal is a <modal-dialog>: Escape and a backdrop click close
    it."""
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    game_a = Game.objects.create(name="Alpha Game", platform=platform)
    game_b = Game.objects.create(name="Beta Game", platform=platform)
    bundle = Purchase.objects.create(
        price=30.0,
        price_currency="USD",
        date_purchased=date(2025, 1, 1),
        platform=platform,
        ownership_type=Purchase.DIGITAL,
        type=Purchase.GAME,
    )
    bundle.games.set([game_a, game_b])

    page.goto(f"{live_server.url}{reverse('games:list_purchases')}")
    modal = page.locator("#split-confirmation-modal")

    # Escape closes it.
    page.locator('[title="Split into per-game purchases"]').click()
    expect(modal).to_be_visible()
    page.keyboard.press("Escape")
    expect(modal).to_have_count(0)

    # A click on the backdrop (outside the panel) closes it. (5, 5) lands on the
    # overlay corner, well away from the centered panel. Coordinate-based (not a
    # locator click) because the overlay detaches mid-click when it dismisses.
    page.locator('[title="Split into per-game purchases"]').click()
    expect(modal).to_be_visible()
    page.mouse.click(5, 5)
    expect(modal).to_have_count(0)


@pytest.fixture
def touch_page(live_server, browser, django_user_model):
    """A logged-in page in a touch-enabled context (so locator.tap() works and
    pointer events report pointerType "touch"). Desktop-width viewport."""
    django_user_model.objects.create_user(username="tester", password="secret123")
    context = browser.new_context(has_touch=True)
    page = context.new_page()
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    yield page
    context.close()


def test_name_popover_shows_on_hover(authenticated_page: Page, live_server):
    """A truncated name's <pop-over> tooltip: the panel is hidden until hovered,
    then revealed. The reveal trigger is a glyph <button> beside the link, but
    the whole host opens on hover — so hovering the NAME (the link) opens it too,
    preserving the pre-extraction hover surface (#445 M1)."""
    page = authenticated_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(
        name="A Very Long Game Name That Exceeds The Thirty Char Limit",
        platform=platform,
    )

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    trigger = page.locator("pop-over [data-pop-over-trigger]").first
    name_link = page.locator("pop-over a").first
    panel = page.locator("pop-over [data-pop-over-panel]").first

    expect(panel).to_be_hidden()
    # Hovering the name link (not just the glyph) opens the tooltip.
    name_link.hover()
    expect(panel).to_be_visible()
    expect(panel.locator("[data-pop-over-arrow]")).to_be_visible()
    page.mouse.move(0, 0)
    expect(panel).to_be_hidden()
    # The glyph trigger opens it too.
    trigger.hover()
    expect(panel).to_be_visible()


def test_name_popover_taps_open_on_touch(touch_page: Page, live_server):
    """On touch (no hover) a tap on the glyph trigger toggles the tooltip; a tap
    elsewhere dismisses it. The link is a sibling of the trigger, so this reveal
    path never fights the link's own navigation."""
    page = touch_page
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    Game.objects.create(
        name="A Very Long Game Name That Exceeds The Thirty Char Limit",
        platform=platform,
    )

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    trigger = page.locator("pop-over [data-pop-over-trigger]").first
    panel = page.locator("pop-over [data-pop-over-panel]").first

    expect(panel).to_be_hidden()
    trigger.tap()
    expect(panel).to_be_visible()
    # A tap on empty page space dismisses (pointerdown outside the host).
    page.touchscreen.tap(2, 2)
    expect(panel).to_be_hidden()
