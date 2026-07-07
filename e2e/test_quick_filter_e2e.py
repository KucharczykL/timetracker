"""Browser tests for the quick filter bar (#197): Apply-button facet
serialization (set facets on the games list, the scalar duration facet on the
sessions list), and the degraded "Advanced filter active" pill for a filter
the bar cannot round-trip."""

import json
import urllib.parse

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Platform


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    _login(page, live_server)
    return page


def _filter_from_url(url: str) -> dict:
    """Extract and parse the ?filter=... query param from a URL."""
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


def _quick_apply(page: Page) -> None:
    page.locator('quick-filter-bar button[type="submit"]').click()


def test_quick_facet_apply_filters_the_list(authenticated_page: Page, live_server):
    """Picking a status in the quick bar and hitting Apply navigates with a
    flat facet-only ?filter= and the list is filtered."""
    platform = Platform.objects.create(name="PC", icon="pc")
    Game.objects.create(
        name="Finished Game", platform=platform, status=Game.Status.FINISHED
    )
    Game.objects.create(
        name="Unplayed Game", platform=platform, status=Game.Status.UNPLAYED
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_games')}")

    page.locator("#quick-status-dropdownLink").click()
    widget = page.locator('quick-filter-bar search-select[name="status"]')
    widget.locator('[data-search-select-option][data-label="Finished"]').click()
    _quick_apply(page)

    page.wait_for_url("**filter=**")
    assert _filter_from_url(page.url) == {
        "status": {
            "value": [{"id": "f", "label": "Finished"}],
            "excludes": [],
            "modifier": "INCLUDES",
        }
    }
    expect(page.get_by_text("Finished Game")).to_be_visible()
    expect(page.get_by_text("Unplayed Game")).to_have_count(0)

    # The applied filter round-trips back into an editable quick bar with the
    # picked value rendered as an include pill (#197's round-trip guarantee).
    pill = page.locator("quick-filter-bar [data-search-select-pills] [data-pill]")
    expect(pill).to_have_count(1)
    expect(pill).to_contain_text("Finished")


def test_quick_scalar_facet_filters_sessions(authenticated_page: Page, live_server):
    """The sessions quick bar's Duration number facet serializes a flat
    numeric criterion on Apply and the list is filtered by it."""
    from datetime import datetime, timedelta, timezone

    from games.models import Session

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Timed Game", platform=platform)
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    long_session = Session.objects.create(
        game=game, timestamp_start=start, timestamp_end=start + timedelta(hours=3)
    )
    short_session = Session.objects.create(
        game=game, timestamp_start=start, timestamp_end=start + timedelta(hours=1)
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    # The Duration facet is a dropdown (#315): open its panel first.
    page.locator("#quick-duration_total_hours-dropdownLink").click()
    duration = page.locator('quick-filter-bar [data-filter-widget][data-kind="number"]')
    duration.locator("select[data-number-modifier-select]").select_option(
        "GREATER_THAN"
    )
    duration.locator('input[name="quick-duration_total_hours"]').fill("2")
    _quick_apply(page)

    page.wait_for_url("**filter=**")
    assert _filter_from_url(page.url) == {
        "duration_total_hours": {"value": 2, "modifier": "GREATER_THAN"}
    }
    expect(page.locator(f"#session-row-{long_session.pk}")).to_be_visible()
    expect(page.locator(f"#session-row-{short_session.pk}")).to_have_count(0)

    # Round trip: the applied scalar criterion prefills an editable quick bar.
    expect(
        page.locator('quick-filter-bar input[name="quick-duration_total_hours"]')
    ).to_have_value("2")


def test_advanced_filter_shows_degraded_pill(authenticated_page: Page, live_server):
    """A filter with operator nesting renders the read-only pill (with working
    Edit-in-builder / Clear links) instead of facet widgets."""
    filter_json = json.dumps(
        {"AND": [{"status": {"value": [{"id": "f", "label": "Finished"}]}}]}
    )
    page = authenticated_page
    list_url = reverse("games:list_games")
    page.goto(f"{live_server.url}{list_url}?filter={urllib.parse.quote(filter_json)}")

    expect(page.get_by_text("Advanced filter active")).to_be_visible()
    expect(page.locator("quick-filter-bar")).to_have_count(0)

    edit_link = page.get_by_role("link", name="Edit in builder")
    href = edit_link.get_attribute("href")
    assert href is not None
    assert reverse("games:filter_builder", args=["game"]) in href
    assert "filter=" in href

    clear_link = page.get_by_role("link", name="Clear")
    assert clear_link.get_attribute("href") == list_url
    clear_link.click()
    page.wait_for_url(f"{live_server.url}{list_url}")
    assert _filter_from_url(page.url) == {}


def test_dropdown_facet_full_flow(authenticated_page: Page, live_server):
    """The #315 dropdown facets on the sessions list: open the Game panel,
    include a game, remove a pill (the panel must stay open — the composedPath
    close-guard fix), Apply, and round-trip back into an editable bar with the
    pill inside the reopened panel."""
    from datetime import datetime, timedelta, timezone

    from games.models import Session

    platform = Platform.objects.create(name="PC", icon="pc")
    picked = Game.objects.create(name="Picked Game", platform=platform)
    other = Game.objects.create(name="Other Game", platform=platform)
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    picked_session = Session.objects.create(
        game=picked, timestamp_start=start, timestamp_end=start + timedelta(hours=1)
    )
    other_session = Session.objects.create(
        game=other, timestamp_start=start, timestamp_end=start + timedelta(hours=1)
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    # Closed trigger: a ghost "Game ▾" button; the panel is hidden.
    trigger = page.locator("#quick-game-dropdownLink")
    panel = page.locator("#quick-game-dropdown")
    expect(trigger).to_be_visible()
    expect(panel).to_be_hidden()

    # Open: search focused, options fetched (refetch-on-show), pick two games
    # then remove one pill — the panel must survive the pill removal.
    trigger.click()
    expect(panel).to_be_visible()
    widget = panel.locator('search-select[name="game"]')
    expect(widget.locator("[data-search-select-search]")).to_be_focused()
    widget.locator(
        '[data-search-select-option][data-label="Picked Game (PC)"] '
        '[data-search-select-action="include"]'
    ).click()
    widget.locator(
        '[data-search-select-option][data-label="Other Game (PC)"] '
        '[data-search-select-action="include"]'
    ).click()
    expect(widget.locator("[data-pill]")).to_have_count(2)
    widget.locator(
        '[data-pill][data-label="Other Game (PC)"] [data-pill-remove]'
    ).click()
    expect(widget.locator("[data-pill]")).to_have_count(1)
    expect(panel).to_be_visible()

    _quick_apply(page)
    page.wait_for_url("**filter=**")
    assert _filter_from_url(page.url) == {
        "game": {
            "value": [{"id": str(picked.pk), "label": "Picked Game (PC)"}],
            "excludes": [],
            "modifier": "INCLUDES",
        }
    }
    expect(page.locator(f"#session-row-{picked_session.pk}")).to_be_visible()
    expect(page.locator(f"#session-row-{other_session.pk}")).to_have_count(0)

    # Round trip: still an editable bar (no degraded pill), and the include
    # pill is server-rendered inside the reopened panel.
    expect(page.get_by_text("Advanced filter active")).to_have_count(0)
    page.locator("#quick-game-dropdownLink").click()
    reopened = page.locator('#quick-game-dropdown search-select[name="game"]')
    pill = reopened.locator("[data-pill]")
    expect(pill).to_have_count(1)
    expect(pill).to_contain_text("Picked Game (PC)")


def test_date_dropdown_facet_preset_flow(authenticated_page: Page, live_server):
    """The Started facet as a dropdown (#315): a ghost "Started ▾" trigger
    opening a static always-visible calendar (no toggle, no Cancel/Select);
    picking the Today preset and applying serializes a BETWEEN criterion."""
    from datetime import date, datetime, timedelta, timezone

    from games.models import Session

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Doom", platform=platform)
    now = datetime.now(timezone.utc)
    today_session = Session.objects.create(
        game=game, timestamp_start=now, timestamp_end=now + timedelta(hours=1)
    )
    old_start = datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc)
    old_session = Session.objects.create(
        game=game,
        timestamp_start=old_start,
        timestamp_end=old_start + timedelta(hours=1),
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    trigger = page.locator("#quick-timestamp_start-dropdownLink")
    panel = page.locator("#quick-timestamp_start-dropdown")
    expect(trigger).to_be_visible()
    expect(panel).to_be_hidden()

    trigger.click()
    expect(panel).to_be_visible()
    # Static calendar: grid rendered, no toggle / Cancel / Select controls.
    expect(panel.locator("[data-date-range-grid] button[data-date]")).to_have_count(42)
    expect(panel.locator("[data-date-range-calendar-toggle]")).to_have_count(0)
    expect(panel.locator("[data-date-range-cancel]")).to_have_count(0)
    expect(panel.locator("[data-date-range-select]")).to_have_count(0)

    panel.locator('[data-date-range-preset="today"]').click()
    _quick_apply(page)

    page.wait_for_url("**filter=**")
    today_iso = date.today().isoformat()
    assert _filter_from_url(page.url) == {
        "timestamp_start": {
            "value": today_iso,
            "value2": today_iso,
            "modifier": "BETWEEN",
        }
    }
    expect(page.locator(f"#session-row-{today_session.pk}")).to_be_visible()
    expect(page.locator(f"#session-row-{old_session.pk}")).to_have_count(0)

    # Round trip: reopened panel shows the committed range in the segments.
    page.locator("#quick-timestamp_start-dropdownLink").click()
    min_hidden = page.locator("#quick-timestamp_start-dropdown [data-range-min]")
    expect(min_hidden).to_have_value(today_iso)


def test_priority_plus_overflow_collapses_and_restores(
    authenticated_page: Page, live_server
):
    """#315 priority-plus: narrowing the viewport moves rightmost facets into
    the "⋯" overflow menu (ResizeObserver, no breakpoints); facets keep
    working from inside it; widening moves them back and hides the menu."""
    from datetime import datetime, timedelta, timezone

    from games.models import Session

    platform = Platform.objects.create(name="PC", icon="pc")
    game = Game.objects.create(name="Doom", platform=platform)
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    long_session = Session.objects.create(
        game=game, timestamp_start=start, timestamp_end=start + timedelta(hours=3)
    )
    short_session = Session.objects.create(
        game=game, timestamp_start=start, timestamp_end=start + timedelta(hours=1)
    )

    page = authenticated_page
    page.set_viewport_size({"width": 1400, "height": 900})
    page.goto(f"{live_server.url}{reverse('games:list_sessions')}")

    overflow = page.locator("[data-quick-overflow]")
    overflow_items = page.locator("[data-quick-overflow-items]")
    duration_facet = page.locator(
        "drop-down[data-quick-facet]:has(#quick-duration_total_hours-dropdown)"
    )

    # Wide: everything inline, no ⋯.
    expect(overflow).to_be_hidden()
    expect(overflow_items.locator("[data-quick-facet]")).to_have_count(0)

    # Narrow: rightmost facets (Duration is last) spill into the ⋯ menu.
    page.set_viewport_size({"width": 520, "height": 900})
    expect(overflow).to_be_visible()
    expect(
        overflow_items.locator(
            ":scope > drop-down:has(#quick-duration_total_hours-dropdown)"
        )
    ).to_have_count(1)

    # The spilled facet still works: open ⋯ → open Duration → edit → Apply.
    page.locator("#quick-sessions-overflowLink").click()
    duration_facet.locator("#quick-duration_total_hours-dropdownLink").click()
    duration_panel = page.locator("#quick-duration_total_hours-dropdown")
    expect(duration_panel).to_be_visible()
    duration_panel.locator("select[data-number-modifier-select]").select_option(
        "GREATER_THAN"
    )
    duration_panel.locator('input[name="quick-duration_total_hours"]').fill("2")
    _quick_apply(page)
    page.wait_for_url("**filter=**")
    assert _filter_from_url(page.url) == {
        "duration_total_hours": {"value": 2, "modifier": "GREATER_THAN"}
    }
    expect(page.locator(f"#session-row-{long_session.pk}")).to_be_visible()
    expect(page.locator(f"#session-row-{short_session.pk}")).to_have_count(0)

    # Widen: facets return to the row in order, ⋯ hides again.
    page.set_viewport_size({"width": 1400, "height": 900})
    expect(page.locator("[data-quick-overflow]")).to_be_hidden()
    expect(
        page.locator("[data-quick-overflow-items] [data-quick-facet]")
    ).to_have_count(0)


def test_preset_pick_on_builderless_mode(
    authenticated_page: Page, live_server, django_user_model
):
    """The quick bar's Load-preset picker works on a builderless mode
    (devices): picking navigates with the preset's ?filter=; Enter inside the
    picker's search box never applies the facet form (#297/#315)."""
    from games.models import Device, FilterPreset

    Device.objects.create(name="Steam Deck")
    Device.objects.create(name="Desktop")
    user = django_user_model.objects.get(username="tester")
    stored_filter = {"name": {"modifier": "INCLUDES", "value": "deck"}}
    FilterPreset.objects.create(
        user=user, name="DeckOnly", mode="devices", object_filter=stored_filter
    )

    page = authenticated_page
    page.goto(f"{live_server.url}{reverse('games:list_devices')}")

    picker = page.locator("quick-filter-bar [data-preset-picker]")
    picker.locator("[data-toggle]").click()
    search = picker.locator("[data-search-select-search]")
    expect(search).to_be_focused()

    # Enter in the picker's search box must not submit the facet form. Type a
    # no-match query first so no preset row can be auto-highlighted — with a
    # highlight, Enter legitimately PICKS the row (that raced in CI when the
    # preset fetch resolved before the keypress).
    search.fill("zzz-no-such-preset")
    expect(picker.locator("[data-search-select-no-results]")).to_be_visible()
    search.press("Enter")
    expect(page).to_have_url(f"{live_server.url}{reverse('games:list_devices')}")

    search.fill("")
    row = picker.locator("[data-search-select-option]").filter(has_text="DeckOnly")
    expect(row).to_be_visible(timeout=5_000)
    with page.expect_navigation():
        row.click()

    assert "?filter=" in page.url
    expect(page.locator("table")).to_contain_text("Steam Deck")
    expect(page.locator("table")).not_to_contain_text("Desktop")
