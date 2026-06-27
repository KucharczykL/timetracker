"""End-to-end Playwright tests for repointed cross-entity filter widgets (#123 2d).

Covers the one layer the Python-side tests cannot reach: the generic serializer
in ``ts/elements/filter-bar.ts`` building the NESTED ``AND`` sub-filter form for
cross-entity widgets — both a composed leaf (``purchase_type`` → set) and a
relation-bool (``session_emulated`` → ANY/NONE) — and the bar prefilling those
widgets back from a reloaded ``?filter=`` URL.

Uses the games ``FilterBar`` rendered at a custom URL so the test needs no auth.
``purchase_type`` is an enum FilterSelect with pre-rendered option rows (no
search endpoint), so its include path is reachable from a static page.
"""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import FilterBar


def _bar_page(filter_json: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Cross-entity filter E2E</title>
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/dist/elements/search-select.js" type="module"></script>
    <script src="/static/js/dist/elements/filter-bar.js" type="module"></script>
</head>
<body>
    {FilterBar(filter_json=filter_json, preset_list_url="/p/l", preset_save_url="/p/s")}
</body>
</html>"""


def bar_view(request):
    return HttpResponse(_bar_page(request.GET.get("filter", "")))


urlpatterns = [
    path("test-cross-entity/", bar_view),
]


def _filter_from_url(url: str) -> dict:
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


def _submit(page):
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )


# ── composed leaf: purchase_type (set) → AND[{purchase_filter:{type:…}}] ──────


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_cross_entity_filter_e2e")
def test_purchase_type_composes_into_and(live_server, page):
    page.goto(live_server.url + "/test-cross-entity/")
    widget = page.locator('search-select[name="purchase_type"]')
    widget.locator("[data-search-select-search]").click()
    widget.locator(
        '[data-search-select-option][data-value="game"] '
        '[data-search-select-action="include"]'
    ).click()
    _submit(page)

    parsed = _filter_from_url(page.url)
    assert parsed == {
        "AND": [
            {
                "purchase_filter": {
                    "type": {
                        "value": [{"id": "game", "label": "Game"}],
                        "excludes": [],
                        "modifier": "INCLUDES",
                    }
                }
            }
        ]
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_cross_entity_filter_e2e")
def test_purchase_type_prefills_from_url(live_server, page):
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "purchase_filter": {
                        "type": {
                            "value": [{"id": "game", "label": "Game"}],
                            "excludes": [],
                            "modifier": "INCLUDES",
                        }
                    }
                }
            ]
        }
    )
    page.goto(
        live_server.url
        + "/test-cross-entity/?filter="
        + urllib.parse.quote(filter_json)
    )
    pill = page.locator(
        'search-select[name="purchase_type"] [data-search-select-pills] [data-value="game"]'
    )
    assert pill.count() >= 1


# ── relation-bool: session_emulated = No → AND[{session_filter:{match:NONE…}}] ─


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_cross_entity_filter_e2e")
def test_session_emulated_no_composes_relation_none(live_server, page):
    page.goto(live_server.url + "/test-cross-entity/")
    page.locator('input[name="filter-session-emulated"][value="false"]').click()
    _submit(page)

    parsed = _filter_from_url(page.url)
    assert parsed == {
        "AND": [
            {
                "session_filter": {
                    "match": "NONE",
                    "emulated": {"value": True, "modifier": "EQUALS"},
                }
            }
        ]
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_cross_entity_filter_e2e")
def test_session_emulated_no_prefills_from_url(live_server, page):
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "session_filter": {
                        "match": "NONE",
                        "emulated": {"value": True, "modifier": "EQUALS"},
                    }
                }
            ]
        }
    )
    page.goto(
        live_server.url
        + "/test-cross-entity/?filter="
        + urllib.parse.quote(filter_json)
    )
    false_radio = page.locator('input[name="filter-session-emulated"][value="false"]')
    assert false_radio.is_checked()
