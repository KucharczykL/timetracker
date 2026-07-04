"""End-to-end Playwright test for boolean radio filter serialization and deselect behavior.

Covers:
1. Selecting True/False serializes the boolean field as True/False.
2. Unsetting/unchecking a radio button by clicking on it again, which deselects it, omitting the field from JSON.
"""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import FilterBar


def _bar_page(filter_json: str = "", apply_url: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Boolean filter E2E</title>
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/dist/elements/search-select.js" type="module"></script>
    <script src="/static/js/dist/elements/filter-bar.js" type="module"></script>
</head>
<body>
    {FilterBar(filter_json=filter_json, preset_api_url="/api/presets/", apply_url=apply_url)}
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


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_boolean_filter_e2e")
def test_no_selection_omits_boolean_filters(live_server, page):
    page.goto(live_server.url + "/test-boolean-filter/")
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert "mastered" not in parsed
    assert "purchase_refunded" not in parsed
    # No selection means no AND element is created (purchase_refunded is now a
    # cross-entity relation-bool composed into AND; #123 Phase 2d).
    assert "AND" not in parsed


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_boolean_filter_e2e")
def test_select_true_and_false_serializes_correctly(live_server, page):
    page.goto(live_server.url + "/test-boolean-filter/")

    # Select "True" for Mastered — a flat (same-entity) bool, unchanged.
    # "filter-mastered" is the mastered radio name; true/false radios carry
    # value="true"/value="false".
    true_radio = page.locator('input[name="filter-mastered"][value="true"]')
    true_radio.click()

    # Select "False" for Refunded (filter-purchase-refunded) — a cross-entity
    # relation-bool: False composes into AND as match=NONE over is_refunded=true.
    false_radio = page.locator('input[name="filter-purchase-refunded"][value="false"]')
    false_radio.click()

    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert parsed.get("mastered") == {"value": True, "modifier": "EQUALS"}
    assert parsed.get("AND") == [
        {
            "purchase_filter": {
                "match": "NONE",
                "is_refunded": {"value": True, "modifier": "EQUALS"},
            }
        }
    ]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_boolean_filter_e2e")
def test_click_to_deselect_radio_works(live_server, page):
    page.goto(live_server.url + "/test-boolean-filter/")

    true_radio = page.locator('input[name="filter-mastered"][value="true"]')

    # First click checks it
    true_radio.click()
    assert true_radio.is_checked()

    # Second click deselects it
    true_radio.click()
    assert not true_radio.is_checked()

    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert "mastered" not in parsed
