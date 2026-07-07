"""End-to-end Playwright tests for the number-kind facet widget.

Covers the layers Python tests cannot: the modifier-driven input toggling in
the real browser (BETWEEN reveals value2, presence modifiers disable+clear)
and the quick bar serializer reading the widget back into ``?filter=`` JSON.
The widgets live inside the games quick bar's facet dropdowns; each
test opens the facet's panel first. Rendered at a custom URL so the test
needs no auth (``apply_url`` override).
"""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import QuickFilterBar

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>Number filter E2E</title>
    <link rel="stylesheet" href="/static/base.css">
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/dist/elements/search-select.js" type="module"></script>
    <script src="/static/js/dist/elements/drop-down.js" type="module"></script>
    <script src="/static/js/dist/elements/quick-filter-bar.js" type="module"></script>
</head>
<body>
    {body}
</body>
</html>"""


def _bar_page(filter_json: str = "", apply_url: str = "") -> str:
    bar = QuickFilterBar(mode="games", filter_json=filter_json, apply_url=apply_url)
    return _PAGE_TEMPLATE.format(body=str(bar))


def empty_bar_view(request):
    return HttpResponse(_bar_page(apply_url=request.path))


def prefilled_bar_view(request):
    filter_json = json.dumps(
        {
            "year_released": {"value": 2000, "value2": 2010, "modifier": "BETWEEN"},
            "session_count": {"modifier": "IS_NULL"},
        }
    )
    return HttpResponse(_bar_page(filter_json=filter_json, apply_url=request.path))


urlpatterns = [
    path("test-number-filter-empty/", empty_bar_view),
    path("test-number-filter-prefilled/", prefilled_bar_view),
]


def _filter_from_url(url: str) -> dict:
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


def _open_facet(page, field: str):
    page.locator(f"#quick-{field}-dropdownLink").click()


def _submit(page):
    with page.expect_navigation():
        page.locator('quick-filter-bar button[type="submit"]').click()


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_number_filter_e2e")
def test_number_filter_defaults_and_greater_than(live_server, page):
    page.goto(live_server.url + "/test-number-filter-empty/")
    _open_facet(page, "year_released")

    value_input = page.locator('input[name="quick-year_released"]')
    value2_input = page.locator('input[name="quick-year_released-value2"]')
    assert value_input.is_enabled()
    # EQUALS is the default; the second input is hidden.
    assert (
        page.locator('select[name="quick-year_released-modifier"]').input_value()
        == "EQUALS"
    )
    assert value2_input.is_hidden()

    value_input.fill("2015")
    page.locator('select[name="quick-year_released-modifier"]').select_option(
        "GREATER_THAN"
    )
    _submit(page)

    parsed = _filter_from_url(page.url)
    assert parsed["year_released"] == {"value": 2015, "modifier": "GREATER_THAN"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_number_filter_e2e")
def test_number_filter_between_reveals_and_serializes(live_server, page):
    page.goto(live_server.url + "/test-number-filter-empty/")
    _open_facet(page, "year_released")

    value2_input = page.locator('input[name="quick-year_released-value2"]')
    assert value2_input.is_hidden()

    page.locator('select[name="quick-year_released-modifier"]').select_option("BETWEEN")
    assert value2_input.is_visible()

    page.locator('input[name="quick-year_released"]').fill("2000")
    value2_input.fill("2010")
    _submit(page)

    parsed = _filter_from_url(page.url)
    assert parsed["year_released"] == {
        "value": 2000,
        "value2": 2010,
        "modifier": "BETWEEN",
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_number_filter_e2e")
def test_number_filter_null_states(live_server, page):
    page.goto(live_server.url + "/test-number-filter-empty/")
    _open_facet(page, "year_released")

    value_input = page.locator('input[name="quick-year_released"]')
    value_input.fill("1999")

    page.locator('select[name="quick-year_released-modifier"]').select_option("IS_NULL")

    # Both inputs disable and clear under a presence modifier.
    assert not value_input.is_enabled()
    assert value_input.input_value() == ""

    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed["year_released"] == {"modifier": "IS_NULL"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_number_filter_e2e")
def test_number_filter_prefilled_states(live_server, page):
    page.goto(live_server.url + "/test-number-filter-prefilled/")

    # year_released: BETWEEN with both bounds, second input visible in the
    # opened panel.
    _open_facet(page, "year_released")
    assert page.locator('input[name="quick-year_released"]').input_value() == "2000"
    assert (
        page.locator('input[name="quick-year_released-value2"]').input_value() == "2010"
    )
    assert page.locator('input[name="quick-year_released-value2"]').is_visible()
    assert (
        page.locator('select[name="quick-year_released-modifier"]').input_value()
        == "BETWEEN"
    )

    # session_count: IS_NULL — value input disabled, modifier selected.
    _open_facet(page, "session_count")
    session_input = page.locator('input[name="quick-session_count"]')
    assert not session_input.is_enabled()
    assert (
        page.locator('select[name="quick-session_count-modifier"]').input_value()
        == "IS_NULL"
    )
