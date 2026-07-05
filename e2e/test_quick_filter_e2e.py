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

    widget = page.locator('quick-filter-bar search-select[name="status"]')
    widget.locator("[data-search-select-search]").click()
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
