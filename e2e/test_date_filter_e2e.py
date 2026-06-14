"""End-to-end Playwright test for the date-range filter widget's JS submit path.

Covers the one layer the Django-Client tests in ``test_rendered_pages.py``
cannot reach: ``filter_bar.js`` reading the two ``<input type="date">``
elements, building a ``DateCriterion`` JSON object, and navigating the
browser to ``?filter=<encoded>``.

The native ``<input type="date">`` path is exercised through the Refunded
field — the Purchased field now uses the DateRangePicker component, covered
by ``test_date_range_picker_e2e.py``.

Renders the bar at its own custom URL so the test doesn't need to auth
against the real app — the bar's JS doesn't care what route serves it.
"""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import PurchaseFilterBar


def _bar_page(filter_json: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Date filter E2E</title>
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/range_slider.js" type="module"></script>
    <script src="/static/js/search_select.js" type="module"></script>
    <script src="/static/js/filter_bar.js" type="module"></script>
</head>
<body>
    {PurchaseFilterBar(filter_json=filter_json, preset_list_url="/p/l", preset_save_url="/p/s")}
</body>
</html>"""


def empty_bar_view(request):
    return HttpResponse(_bar_page())


def prefilled_bar_view(request):
    filter_json = json.dumps(
        {
            "date_refunded": {
                "value": "2024-03-15",
                "value2": "2024-09-20",
                "modifier": "BETWEEN",
            }
        }
    )
    return HttpResponse(_bar_page(filter_json))


urlpatterns = [
    path("test-date-filter/", empty_bar_view),
    path("test-date-filter-prefilled/", prefilled_bar_view),
]


def _filter_from_url(url: str) -> dict:
    """Extract and parse the ?filter=... query param from a URL."""
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_filter_e2e")
def test_both_dates_serializes_as_between(live_server, page):
    page.goto(live_server.url + "/test-date-filter/")
    page.locator('input[name="filter-date-refunded-min"]').fill("2024-01-01")
    page.locator('input[name="filter-date-refunded-max"]').fill("2024-12-31")
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert parsed == {
        "date_refunded": {
            "value": "2024-01-01",
            "value2": "2024-12-31",
            "modifier": "BETWEEN",
        }
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_filter_e2e")
def test_min_only_serializes_as_greater_than(live_server, page):
    page.goto(live_server.url + "/test-date-filter/")
    page.locator('input[name="filter-date-refunded-min"]').fill("2024-06-15")
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert parsed == {
        "date_refunded": {"value": "2024-06-15", "modifier": "GREATER_THAN"}
    }
    # value2 must not be present when there's no upper bound.
    assert "value2" not in parsed["date_refunded"]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_filter_e2e")
def test_max_only_serializes_as_less_than(live_server, page):
    page.goto(live_server.url + "/test-date-filter/")
    page.locator('input[name="filter-date-refunded-max"]').fill("2025-06-30")
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert parsed == {"date_refunded": {"value": "2025-06-30", "modifier": "LESS_THAN"}}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_filter_e2e")
def test_empty_inputs_omit_date_criterion(live_server, page):
    """No date typed → the filter JSON simply has no date_purchased /
    date_refunded keys (vs. an empty-string crash)."""
    page.goto(live_server.url + "/test-date-filter/")
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert "date_purchased" not in parsed
    assert "date_refunded" not in parsed


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_filter_e2e")
def test_prefilled_bar_reflects_existing_filter_in_inputs(live_server, page):
    """A bar rendered with a BETWEEN filter_json pre-fills the inputs and
    re-submits the same bounds unchanged."""
    page.goto(live_server.url + "/test-date-filter-prefilled/")
    assert (
        page.locator('input[name="filter-date-refunded-min"]').input_value()
        == "2024-03-15"
    )
    assert (
        page.locator('input[name="filter-date-refunded-max"]').input_value()
        == "2024-09-20"
    )
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert parsed["date_refunded"] == {
        "value": "2024-03-15",
        "value2": "2024-09-20",
        "modifier": "BETWEEN",
    }
