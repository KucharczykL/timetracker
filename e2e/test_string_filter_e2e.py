"""End-to-end Playwright test for String multi-mode filter serialization,
null-state toggling, and prefill behaviors — hosted in the platforms quick
bar's facet dropdowns (#315)."""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import QuickFilterBar


def _bar_page(filter_json: str = "", apply_url: str = "") -> str:
    bar = QuickFilterBar(mode="platforms", filter_json=filter_json, apply_url=apply_url)
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>String filter E2E</title>
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


def prefilled_bar_view(request):
    filter_json = json.dumps(
        {
            "name": {
                "value": "Switch",
                "modifier": "INCLUDES",
            },
            "group": {"modifier": "IS_NULL"},
        }
    )
    return HttpResponse(_bar_page(filter_json=filter_json, apply_url=request.path))


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
def test_string_filter_null_states(live_server, page):
    page.goto(live_server.url + "/test-string-filter-empty/")
    page.locator("#quick-name-dropdownLink").click()

    name_input = page.locator('input[name="quick-name"]')
    name_input.fill("Xbox")

    # Choose "is null"
    page.locator('select[name="quick-name-modifier"]').select_option("IS_NULL")

    # Verification of interactive disabling
    assert not name_input.is_enabled()
    assert name_input.input_value() == ""

    with page.expect_navigation():
        page.locator('quick-filter-bar button[type="submit"]').click()
    parsed = _filter_from_url(page.url)
    assert parsed["name"] == {"modifier": "IS_NULL"}


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

    # Verifies group is empty, disabled, and "is null" is selected
    page.locator("#quick-group-dropdownLink").click()
    assert group_input.input_value() == ""
    assert not group_input.is_enabled()
    assert (
        page.locator('select[name="quick-group-modifier"]').input_value() == "IS_NULL"
    )


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_string_filter_e2e")
def test_string_filter_modifier_switch_re_enables(live_server, page):
    page.goto(live_server.url + "/test-string-filter-empty/")
    page.locator("#quick-name-dropdownLink").click()

    name_input = page.locator('input[name="quick-name"]')
    modifier_select = page.locator('select[name="quick-name-modifier"]')

    # 1. Choose "is null" -> disables the text input
    modifier_select.select_option("IS_NULL")
    assert not name_input.is_enabled()

    # 2. Switch back to a value modifier -> re-enables the text input
    modifier_select.select_option("EQUALS")
    assert name_input.is_enabled()
