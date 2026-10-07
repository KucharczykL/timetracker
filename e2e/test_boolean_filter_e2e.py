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
from common.date_time_presentation import date_time_presentation_for_request


def _bar_page(presentation, filter_json: str = "", apply_url: str = "") -> str:
    bar = QuickFilterBar(
        mode="games",
        filter_json=filter_json,
        apply_url=apply_url,
        presentation=presentation,
    )
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Boolean filter E2E</title>
    <link rel="stylesheet" href="/static/base.css">
    <script src="/static/js/dist/elements/search-select.js" type="module"></script>
    <script src="/static/js/dist/elements/drop-down.js" type="module"></script>
    <script src="/static/js/dist/elements/quick-filter-bar.js" type="module"></script>
    <script src="/static/js/dist/elements/search-field.js" type="module"></script>
</head>
<body>
    {bar}
</body>
</html>"""


def empty_bar_view(request):
    return HttpResponse(
        _bar_page(date_time_presentation_for_request(request), apply_url=request.path)
    )


urlpatterns = [
    path("test-boolean-filter/", empty_bar_view),
]


def _filter_from_url(url: str) -> dict:
    """Extract and parse the ?filter=... query param from a URL."""
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


def _open_mastered(page, url: str):
    """Wide enough that Mastered sits in the row, not the overflow."""
    page.set_viewport_size({"width": 1920, "height": 900})
    page.goto(url)
    page.locator("#quick-mastered-dropdownLink").click()


def _submit(page):
    with page.expect_navigation():
        page.locator(
            'quick-filter-bar [aria-label="Filter actions"] button[type="submit"]'
        ).click()


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
    _open_mastered(page, live_server.url + "/test-boolean-filter/")

    page.locator('input[name="quick-mastered"][value="true"]').click()
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed.get("mastered") == {"value": True, "modifier": "EQUALS"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_boolean_filter_e2e")
def test_click_to_deselect_radio_works(live_server, page):
    _open_mastered(page, live_server.url + "/test-boolean-filter/")

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


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_boolean_filter_e2e")
def test_the_visibility_facet_states_each_flag(live_server, page):
    page.set_viewport_size({"width": 1920, "height": 900})
    page.goto(live_server.url + "/test-boolean-filter/")
    trigger = page.get_by_role("button", name="Visibility")
    if not trigger.is_visible():
        page.get_by_role("button", name="More filters").click()
    trigger.click()

    page.get_by_role("group", name="Unfinished lists").get_by_label("False").check()
    page.get_by_role("group", name="Dropped figures").get_by_label("True").check()
    _submit(page)

    parsed = _filter_from_url(page.url)
    assert parsed["excluded_from_unfinished"] == {"value": False, "modifier": "EQUALS"}
    assert parsed["excluded_from_dropped"] == {"value": True, "modifier": "EQUALS"}
