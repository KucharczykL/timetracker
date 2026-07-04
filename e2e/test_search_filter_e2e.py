"""End-to-end Playwright tests for the injected free-text search input and its
Exclude toggle (issue #142).

Every ``*Filter.to_q`` already negates the free-text OR when
``search.modifier == EXCLUDES``, but until now the client-injected search input
only ever emitted ``modifier:"INCLUDES"``. The Exclude checkbox added next to the
search box makes the EXCLUDES branch reachable from the UI. These tests assert
both the emitted filter JSON and that an excluded term actually filters the list.
"""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from playwright.sync_api import Page, expect

from common.components import PlatformFilterBar
from games.models import Game


def _bar_page(filter_json: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Search filter E2E</title>
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/dist/elements/search-select.js" type="module"></script>
    <script src="/static/js/dist/elements/filter-bar.js" type="module"></script>
</head>
<body>
    {PlatformFilterBar(filter_json=filter_json, preset_api_url="/api/presets/")}
</body>
</html>"""


def empty_bar_view(request):
    return HttpResponse(_bar_page())


def prefilled_exclude_view(request):
    filter_json = json.dumps({"search": {"value": "Witcher", "modifier": "EXCLUDES"}})
    return HttpResponse(_bar_page(filter_json=filter_json))


urlpatterns = [
    path("test-search-filter-empty/", empty_bar_view),
    path("test-search-filter-prefilled-exclude/", prefilled_exclude_view),
]


def _filter_from_url(url: str) -> dict:
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


def _submit(page: Page) -> None:
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_filter_e2e")
def test_search_defaults_to_includes(live_server, page):
    page.goto(live_server.url + "/test-search-filter-empty/")

    search_input = page.locator('input[name="filter-search"]')
    exclude_checkbox = page.locator('input[name="filter-search-exclude"]')
    expect(search_input).to_be_visible()
    assert not exclude_checkbox.is_checked()

    search_input.fill("Witcher")
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed["search"] == {"value": "Witcher", "modifier": "INCLUDES"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_filter_e2e")
def test_search_exclude_emits_excludes_modifier(live_server, page):
    page.goto(live_server.url + "/test-search-filter-empty/")

    page.locator('input[name="filter-search"]').fill("Witcher")
    page.locator('input[name="filter-search-exclude"]').check()

    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed["search"] == {"value": "Witcher", "modifier": "EXCLUDES"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_search_filter_e2e")
def test_search_exclude_prefills_from_filter_json(live_server, page):
    page.goto(live_server.url + "/test-search-filter-prefilled-exclude/")

    assert page.locator('input[name="filter-search"]').input_value() == "Witcher"
    assert page.locator('input[name="filter-search-exclude"]').is_checked()


@pytest.fixture
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def test_excluded_search_term_filters_game_list(authenticated_page, live_server, db):
    """An excluded search term hides matching games and keeps the rest."""
    page = authenticated_page
    Game.objects.create(name="The Witcher 3", sort_name="witcher 3")
    Game.objects.create(name="Hollow Knight", sort_name="hollow knight")

    page.goto(f"{live_server.url}{reverse('games:list_games')}")
    # Reveal the collapsed filter-bar body.
    page.locator("[data-filter-bar-toggle]").click()
    page.locator('input[name="filter-search"]').fill("Witcher")
    page.locator('input[name="filter-search-exclude"]').check()

    with page.expect_navigation():
        page.locator("[data-filter-bar-clear]").wait_for()
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )

    assert _filter_from_url(page.url)["search"]["modifier"] == "EXCLUDES"
    table = page.locator("table")
    expect(table).not_to_contain_text("The Witcher 3")
    expect(table).to_contain_text("Hollow Knight")
