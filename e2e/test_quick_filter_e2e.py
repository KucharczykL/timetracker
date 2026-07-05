"""Browser tests for the quick filter bar (#197): apply-on-change facet
serialization on the games list, and the degraded "Advanced filter active"
pill for a filter the bar cannot round-trip."""

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


def test_quick_facet_pick_applies_immediately(authenticated_page: Page, live_server):
    """Picking a status in the quick bar navigates at once with a flat
    facet-only ?filter= — no Apply button — and the list is filtered."""
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
