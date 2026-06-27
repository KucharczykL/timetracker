"""End-to-end Playwright test for the ``set``-kind FilterSelect widget.

Covers the one layer the Python-side tests cannot reach: the generic
serializer in ``ts/elements/filter-bar.ts`` reading a FilterSelect's
include/exclude pills (and pinned presence modifier) off its
``data-included``/``data-excluded``/``data-modifier`` attributes, building the
set-criterion JSON, and navigating to ``?filter=<encoded>``.

Uses ``DeviceFilterBar`` because its single ``type`` field is an enum
FilterSelect with pre-rendered option rows (no search endpoint) and both pinned
modifiers — ``(Any)`` (NOT_NULL) and ``(None)`` (IS_NULL) — so include, exclude,
and presence paths are all reachable from a static page. Renders the bar at its
own custom URL so the test needs no auth — the bar's JS doesn't care what route
serves it.
"""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import DeviceFilterBar


def _bar_page(filter_json: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Set filter E2E</title>
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/dist/elements/search-select.js" type="module"></script>
    <script src="/static/js/dist/elements/filter-bar.js" type="module"></script>
</head>
<body>
    {DeviceFilterBar(filter_json=filter_json, preset_list_url="/p/l", preset_save_url="/p/s")}
</body>
</html>"""


def empty_bar_view(request):
    return HttpResponse(_bar_page())


urlpatterns = [
    path("test-set-filter/", empty_bar_view),
]


def _filter_from_url(url: str) -> dict:
    """Extract and parse the ?filter=... query param from a URL."""
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


def _widget(page):
    return page.locator('search-select[name="type"]')


def _open_panel(page):
    """Focus the search box so the FilterSelect options panel is interactable."""
    _widget(page).locator("[data-search-select-search]").click()


def _add_value(page, value: str, action: str):
    """Click the include (+) or exclude (−) button on a value row."""
    _widget(page).locator(
        f'[data-search-select-option][data-value="{value}"] '
        f'[data-search-select-action="{action}"]'
    ).click()


def _choose_modifier(page, modifier: str):
    """Click a pinned modifier pseudo-option (e.g. (Any)/(None))."""
    _widget(page).locator(f'[data-search-select-modifier-option="{modifier}"]').click()


def _submit(page):
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_set_filter_e2e")
def test_set_filter_empty_omits_field(live_server, page):
    page.goto(live_server.url + "/test-set-filter/")
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert "type" not in parsed


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_set_filter_e2e")
def test_set_filter_include_only(live_server, page):
    page.goto(live_server.url + "/test-set-filter/")
    _open_panel(page)
    _add_value(page, "PC", "include")
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed["type"] == {
        "value": [{"id": "PC", "label": "PC"}],
        "excludes": [],
        "modifier": "INCLUDES",
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_set_filter_e2e")
def test_set_filter_include_and_exclude(live_server, page):
    page.goto(live_server.url + "/test-set-filter/")
    _open_panel(page)
    _add_value(page, "PC", "include")
    _add_value(page, "Console", "exclude")
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed["type"] == {
        "value": [{"id": "PC", "label": "PC"}],
        "excludes": [{"id": "Console", "label": "Console"}],
        "modifier": "INCLUDES",
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_set_filter_e2e")
def test_set_filter_presence_is_null(live_server, page):
    page.goto(live_server.url + "/test-set-filter/")
    _open_panel(page)
    _choose_modifier(page, "IS_NULL")
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed["type"] == {"modifier": "IS_NULL"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_set_filter_e2e")
def test_set_filter_presence_not_null(live_server, page):
    page.goto(live_server.url + "/test-set-filter/")
    _open_panel(page)
    _choose_modifier(page, "NOT_NULL")
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed["type"] == {"modifier": "NOT_NULL"}
