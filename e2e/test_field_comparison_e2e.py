"""End-to-end Playwright test for the field-to-field comparison widget (#167):
dependent operator/right-column option building, AND/OR serialization, and
prefill round-trip."""

import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import SessionFilterBar


def _bar_page(filter_json: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Field comparison E2E</title>
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/dist/elements/search-select.js" type="module"></script>
    <script src="/static/js/dist/elements/field-comparison-set.js" type="module"></script>
    <script src="/static/js/dist/elements/filter-bar.js" type="module"></script>
</head>
<body>
    {SessionFilterBar(filter_json=filter_json, preset_list_url="/p/l", preset_save_url="/p/s")}
</body>
</html>"""


def empty_bar_view(request):
    return HttpResponse(_bar_page())


def prefilled_and_view(request):
    filter_json = json.dumps(
        {
            "field_comparisons": [
                {
                    "left": "timestamp_end",
                    "right": "timestamp_start",
                    "modifier": "LESS_THAN",
                }
            ]
        }
    )
    return HttpResponse(_bar_page(filter_json=filter_json))


def prefilled_granularity_view(request):
    filter_json = json.dumps(
        {
            "field_comparisons": [
                {
                    "left": "timestamp_start",
                    "right": "timestamp_end",
                    "modifier": "LESS_THAN_OR_EQUAL",
                    "granularity": "date",
                }
            ]
        }
    )
    return HttpResponse(_bar_page(filter_json=filter_json))


urlpatterns = [
    path("test-fc-empty/", empty_bar_view),
    path("test-fc-prefilled-and/", prefilled_and_view),
    path("test-fc-prefilled-granularity/", prefilled_granularity_view),
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


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_field_comparison_e2e")
def test_dependent_options_and_and_mode(live_server, page):
    page.goto(live_server.url + "/test-fc-empty/")

    # No rows until the user adds one.
    assert page.locator("[data-fc-row]").count() == 0
    page.locator("[data-fc-add]").click()
    row = page.locator("[data-fc-row]").first

    left = row.locator("[data-fc-left]")
    operator = row.locator("[data-fc-op]")
    right = row.locator("[data-fc-right]")

    # Operator/right are disabled until a left column is chosen.
    assert not operator.is_enabled()
    assert not right.is_enabled()

    left.select_option("timestamp_end")

    # Operator list is now the datetime (ordered) set; string-only ops are absent.
    assert operator.is_enabled()
    assert operator.locator('option[value="LESS_THAN"]').count() == 1
    assert operator.locator('option[value="INCLUDES"]').count() == 0
    # Right column excludes the chosen left column and offers same-group columns.
    assert right.locator('option[value="timestamp_start"]').count() == 1
    assert right.locator('option[value="timestamp_end"]').count() == 0

    operator.select_option("LESS_THAN")
    right.select_option("timestamp_start")
    _submit(page)

    parsed = _filter_from_url(page.url)
    assert parsed["field_comparisons"] == [
        {"left": "timestamp_end", "right": "timestamp_start", "modifier": "LESS_THAN"}
    ]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_field_comparison_e2e")
def test_operator_options_track_column_group(live_server, page):
    """The operator <select> is filled from the chosen column's server-supplied
    `operators` (#152), so each comparison group offers the right set: bool is
    equality-only, string adds containment, ordered groups have neither extreme."""
    page.goto(live_server.url + "/test-fc-empty/")
    page.locator("[data-fc-add]").click()
    row = page.locator("[data-fc-row]").first
    left = row.locator("[data-fc-left]")
    operator = row.locator("[data-fc-op]")

    # bool column (emulated) -> EQUALS / NOT_EQUALS only.
    left.select_option("emulated")
    assert operator.locator('option[value="EQUALS"]').count() == 1
    assert operator.locator('option[value="NOT_EQUALS"]').count() == 1
    assert operator.locator('option[value="GREATER_THAN"]').count() == 0
    assert operator.locator('option[value="INCLUDES"]').count() == 0

    # string column (note) -> ordered + containment.
    left.select_option("note")
    assert operator.locator('option[value="INCLUDES"]').count() == 1
    assert operator.locator('option[value="EXCLUDES"]').count() == 1
    assert operator.locator('option[value="GREATER_THAN"]').count() == 1


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_field_comparison_e2e")
def test_or_mode_serializes_isolated_wrapper(live_server, page):
    page.goto(live_server.url + "/test-fc-empty/")
    page.locator("[data-fc-add]").click()
    row = page.locator("[data-fc-row]").first
    row.locator("[data-fc-left]").select_option("timestamp_end")
    row.locator("[data-fc-op]").select_option("LESS_THAN")
    row.locator("[data-fc-right]").select_option("timestamp_start")

    # Switch the group to OR.
    page.locator('[data-fc-mode][value="OR"]').click()
    _submit(page)

    parsed = _filter_from_url(page.url)
    assert parsed == {
        "AND": [
            {
                "OR": [
                    {
                        "field_comparisons": [
                            {
                                "left": "timestamp_end",
                                "right": "timestamp_start",
                                "modifier": "LESS_THAN",
                            }
                        ]
                    }
                ]
            }
        ]
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_field_comparison_e2e")
def test_and_prefill_round_trip(live_server, page):
    page.goto(live_server.url + "/test-fc-prefilled-and/")

    row = page.locator("[data-fc-row]").first
    assert row.locator("[data-fc-left]").input_value() == "timestamp_end"
    assert row.locator("[data-fc-op]").input_value() == "LESS_THAN"
    assert row.locator("[data-fc-right]").input_value() == "timestamp_start"
    assert page.locator('[data-fc-mode][value="AND"]').is_checked()

    # Re-applying without changes round-trips to the same shape.
    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed["field_comparisons"] == [
        {"left": "timestamp_end", "right": "timestamp_start", "modifier": "LESS_THAN"}
    ]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_field_comparison_e2e")
def test_by_day_toggle_serializes_granularity(live_server, page):
    page.goto(live_server.url + "/test-fc-empty/")
    page.locator("[data-fc-add]").click()
    row = page.locator("[data-fc-row]").first
    by_day = row.locator("[data-fc-granularity-wrap]")

    # Hidden until a datetime left column is chosen.
    assert not by_day.is_visible()
    row.locator("[data-fc-left]").select_option("timestamp_start")
    assert by_day.is_visible()
    # >= / <= are offered for the datetime (ordered) set.
    operator = row.locator("[data-fc-op]")
    assert operator.locator('option[value="LESS_THAN_OR_EQUAL"]').count() == 1

    by_day.locator("[data-fc-granularity]").check()
    operator.select_option("LESS_THAN_OR_EQUAL")
    row.locator("[data-fc-right]").select_option("timestamp_end")
    _submit(page)

    parsed = _filter_from_url(page.url)
    assert parsed["field_comparisons"] == [
        {
            "left": "timestamp_start",
            "right": "timestamp_end",
            "modifier": "LESS_THAN_OR_EQUAL",
            "granularity": "date",
        }
    ]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_field_comparison_e2e")
def test_by_day_hidden_for_non_datetime_left(live_server, page):
    page.goto(live_server.url + "/test-fc-empty/")
    page.locator("[data-fc-add]").click()
    row = page.locator("[data-fc-row]").first
    by_day = row.locator("[data-fc-granularity-wrap]")

    # Datetime → visible; switching to a non-datetime column hides + clears it.
    row.locator("[data-fc-left]").select_option("timestamp_start")
    by_day.locator("[data-fc-granularity]").check()
    assert by_day.is_visible()
    row.locator("[data-fc-left]").select_option("note")
    assert not by_day.is_visible()
    assert not by_day.locator("[data-fc-granularity]").is_checked()


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_field_comparison_e2e")
def test_granularity_prefill_round_trip(live_server, page):
    page.goto(live_server.url + "/test-fc-prefilled-granularity/")

    row = page.locator("[data-fc-row]").first
    by_day = row.locator("[data-fc-granularity-wrap]")
    assert by_day.is_visible()
    assert by_day.locator("[data-fc-granularity]").is_checked()
    assert row.locator("[data-fc-op]").input_value() == "LESS_THAN_OR_EQUAL"

    _submit(page)
    parsed = _filter_from_url(page.url)
    assert parsed["field_comparisons"] == [
        {
            "left": "timestamp_start",
            "right": "timestamp_end",
            "modifier": "LESS_THAN_OR_EQUAL",
            "granularity": "date",
        }
    ]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_field_comparison_e2e")
def test_remove_row(live_server, page):
    page.goto(live_server.url + "/test-fc-empty/")
    page.locator("[data-fc-add]").click()
    page.locator("[data-fc-add]").click()
    assert page.locator("[data-fc-row]").count() == 2
    page.locator("[data-fc-row]").first.locator("[data-fc-remove]").click()
    assert page.locator("[data-fc-row]").count() == 1
