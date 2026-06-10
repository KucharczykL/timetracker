"""End-to-end Playwright test for String multi-mode filter serialization, null-state toggling, and prefill behaviors."""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import PlatformFilterBar


def _bar_page(filter_json: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>String filter E2E</title>
    <script src="/static/js/range_slider.js" defer></script>
    <script src="/static/js/search_select.js" defer></script>
    <script src="/static/js/filter_bar.js" defer></script>
</head>
<body>
    {PlatformFilterBar(filter_json=filter_json, preset_list_url="/p/l", preset_save_url="/p/s")}
</body>
</html>"""


def empty_bar_view(request):
    return HttpResponse(_bar_page())


def prefilled_bar_view(request):
    filter_json = json.dumps(
        {
            "name": {
                "value": "Switch",
                "modifier": "INCLUDES",
            },
            "group": {
                "modifier": "IS_NULL"
            }
        }
    )
    return HttpResponse(_bar_page(filter_json=filter_json))


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
    
    # 1. Verify text inputs are active by default and modifier "is" (EQUALS) is checked
    name_input = page.locator('input[name="filter-name"]')
    assert name_input.is_enabled()
    
    is_radio = page.locator('input[name="filter-name-modifier"][value="EQUALS"]')
    assert is_radio.is_checked()

    # 2. Enter values, click "includes" (INCLUDES), and submit
    name_input.fill("PlayStation")
    includes_radio = page.locator('input[name="filter-name-modifier"][value="INCLUDES"]')
    includes_radio.click()
    
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert parsed["name"] == {"value": "PlayStation", "modifier": "INCLUDES"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_string_filter_e2e")
def test_string_filter_null_states(live_server, page):
    page.goto(live_server.url + "/test-string-filter-empty/")

    name_input = page.locator('input[name="filter-name"]')
    name_input.fill("Xbox")
    
    # Click "is null"
    is_null_radio = page.locator('input[name="filter-name-modifier"][value="IS_NULL"]')
    is_null_radio.click()
    
    # Verification of interactive disabling
    assert not name_input.is_enabled()
    assert name_input.input_value() == ""
    
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )
    parsed = _filter_from_url(page.url)
    assert parsed["name"] == {"modifier": "IS_NULL"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_string_filter_e2e")
def test_string_filter_prefilled_states(live_server, page):
    page.goto(live_server.url + "/test-string-filter-prefilled/")
    
    name_input = page.locator('input[name="filter-name"]')
    group_input = page.locator('input[name="filter-group"]')
    
    # Verifies name matches "Switch" and "includes" is checked
    assert name_input.input_value() == "Switch"
    assert name_input.is_enabled()
    assert page.locator('input[name="filter-name-modifier"][value="INCLUDES"]').is_checked()
    
    # Verifies group is empty, disabled, and "is null" is checked
    assert group_input.input_value() == ""
    assert not group_input.is_enabled()
    assert page.locator('input[name="filter-group-modifier"][value="IS_NULL"]').is_checked()
