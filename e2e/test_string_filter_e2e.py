"""End-to-end Playwright test for String multi-mode filter serialization,
null-state toggling, and prefill behaviors — hosted in the platforms quick
bar's facet dropdowns."""

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
        mode="platforms",
        filter_json=filter_json,
        apply_url=apply_url,
        presentation=presentation,
    )
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>String filter E2E</title>
    <link rel="stylesheet" href="/static/base.css">
    <script src="/static/js/htmx.min.js"></script>
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


def prefilled_bar_view(request):
    filter_json = json.dumps(
        {
            "name": {
                "value": "Switch",
                "modifier": "INCLUDES",
            },
            # "Is empty" on a NOT NULL column is "".
            #
            # Never a presence test, so this is the shape the widget states.
            "group": {"value": "", "modifier": "EQUALS"},
        }
    )
    return HttpResponse(
        _bar_page(
            date_time_presentation_for_request(request),
            filter_json=filter_json,
            apply_url=request.path,
        )
    )


urlpatterns = [
    path("test-string-filter-empty/", empty_bar_view),
    path("test-string-filter-prefilled/", prefilled_bar_view),
]


def _filter_from_url(url: str) -> dict:
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_string_filter_e2e")
def test_string_filter_defaults_and_toggles(live_server, page):
    page.goto(live_server.url + "/test-string-filter-empty/")
    page.locator("#quick-name-dropdownLink").click()

    # 1. Verify text inputs are active by default and modifier "is" (EQUALS) is checked
    name_input = page.locator('input[name="quick-name"]')
    assert name_input.is_enabled()

    modifier_select = page.locator('select[name="quick-name-modifier"]')
    assert modifier_select.input_value() == "EQUALS"

    # 2. Enter values, choose "includes" (INCLUDES), and submit
    name_input.fill("PlayStation")
    modifier_select.select_option("INCLUDES")

    with page.expect_navigation():
        page.locator('quick-filter-bar button[type="submit"]').click()
    parsed = _filter_from_url(page.url)
    assert parsed["name"] == {"value": "PlayStation", "modifier": "INCLUDES"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_string_filter_e2e")
def test_string_filter_offers_no_presence_modifier(live_server, page):
    """A string widget states only its field's modes.

    Every string column here is NOT NULL, so "is null" would match no row. The
    widget offers the six a value shape allows, and "is empty" is the empty
    string under "is".
    """
    page.goto(live_server.url + "/test-string-filter-empty/")
    page.locator("#quick-name-dropdownLink").click()

    modifier_select = page.locator('select[name="quick-name-modifier"]')
    offered = modifier_select.locator("option").evaluate_all(
        "options => options.map(option => option.value)"
    )
    assert "IS_NULL" not in offered
    assert "NOT_NULL" not in offered
    assert offered == [
        "EQUALS",
        "NOT_EQUALS",
        "INCLUDES",
        "EXCLUDES",
        "MATCHES_REGEX",
        "NOT_MATCHES_REGEX",
    ]

    # No offered mode carries no value.
    name_input = page.locator('input[name="quick-name"]')
    for modifier in offered:
        modifier_select.select_option(modifier)
        assert name_input.is_enabled(), modifier


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_string_filter_e2e")
def test_string_filter_prefilled_states(live_server, page):
    page.goto(live_server.url + "/test-string-filter-prefilled/")

    name_input = page.locator('input[name="quick-name"]')
    group_input = page.locator('input[name="quick-group"]')

    # Verifies name matches "Switch" and "includes" is selected
    page.locator("#quick-name-dropdownLink").click()
    assert name_input.input_value() == "Switch"
    assert name_input.is_enabled()
    assert (
        page.locator('select[name="quick-name-modifier"]').input_value() == "INCLUDES"
    )

    # group prefills the empty string under "is".
    page.locator("#quick-group-dropdownLink").click()
    assert group_input.input_value() == ""
    assert group_input.is_enabled()
    assert page.locator('select[name="quick-group-modifier"]').input_value() == "EQUALS"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_string_filter_e2e")
def test_string_filter_serializes_the_empty_string(live_server, page):
    """ "Is empty" is a value, not presence."""
    page.goto(live_server.url + "/test-string-filter-empty/")
    page.locator("#quick-name-dropdownLink").click()

    page.locator('input[name="quick-name"]').fill("Xbox")
    page.locator('select[name="quick-name-modifier"]').select_option("EQUALS")
    page.locator('input[name="quick-name"]').fill("")

    with page.expect_navigation():
        page.locator('quick-filter-bar button[type="submit"]').click()
    # An empty box states no criterion.
    #
    # The bar drops the key rather than narrowing to the rows holding "".
    assert "name" not in _filter_from_url(page.url)
