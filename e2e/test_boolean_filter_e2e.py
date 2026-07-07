"""End-to-end Playwright test for boolean radio facet serialization and
deselect behavior, hosted in the games quick bar's Mastered dropdown.

Covers:
1. Selecting True/False serializes the boolean field as True/False.
2. Unsetting/unchecking a radio button by clicking it again (the
   setupDeselectableRadios behavior), omitting the field from the JSON.
"""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import QuickFilterBar


def _bar_page(filter_json: str = "", apply_url: str = "") -> str:
    bar = QuickFilterBar(mode="games", filter_json=filter_json, apply_url=apply_url)
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Boolean filter E2E</title>
    <link rel="stylesheet" href="/static/base.css">
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/dist/elements/search-select.js" type="module"></script>
    <script src="/static/js/dist/elements/drop-down.js" type="module"></script>
    <script src="/static/js/dist/elements/quick-filter-bar.js" type="module"></script>
</head>
<body>
    {bar}
</body>
</html>"""


def empty_bar_view(request):
    return HttpResponse(_bar_page(apply_url=request.path))


urlpatterns = [
    path("test-boolean-filter/", empty_bar_view),
]


def _filter_from_url(url: str) -> dict:
    """Extract and parse the ?filter=... query param from a URL."""
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


def _submit(page):
    with page.expect_navigation():
        page.locator('quick-filter-bar button[type="submit"]').click()


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_boolean_filter_e2e")
def test_no_selection_omits_boolean_filters(live_server, page):
    page.goto(live_server.url + "/test-boolean-filter/")
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert "mastered" not in parsed


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_boolean_filter_e2e")
def test_select_true_serializes_correctly(live_server, page):
    page.goto(live_server.url + "/test-boolean-filter/")
    page.locator("#quick-mastered-dropdownLink").click()

    page.locator('input[name="quick-mastered"][value="true"]').click()
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed.get("mastered") == {"value": True, "modifier": "EQUALS"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_boolean_filter_e2e")
def test_click_to_deselect_radio_works(live_server, page):
    page.goto(live_server.url + "/test-boolean-filter/")
    page.locator("#quick-mastered-dropdownLink").click()

    true_radio = page.locator('input[name="quick-mastered"][value="true"]')

    # First click checks it
    true_radio.click()
    assert true_radio.is_checked()

    # Second click deselects it
    true_radio.click()
    assert not true_radio.is_checked()

    _submit(page)
    parsed = _filter_from_url(page.url)
    assert "mastered" not in parsed
