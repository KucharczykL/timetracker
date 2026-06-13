"""End-to-end Playwright tests for the DateRangePicker component.

Exercises the behaviour layers the rendering tests cannot reach
(``date_range_picker.js``): segmented digit entry with right-to-left
placeholder fill and auto-advance, Backspace reverting a part, the calendar
popup's anchor-style range picking, presets, the Cancel / Clear / Select
footer, and the ``filter_bar.js`` serialization of the hidden ISO inputs
into a ``DateCriterion``.

Like the other filter-bar e2e modules, the bar is served from its own
minimal URLconf (no auth, no CSS) — the JS only cares about the DOM.
"""

import datetime
import json
import urllib.parse

import pytest
from django.http import HttpResponse
from django.test import override_settings

from common.components import PurchaseFilterBar
from django.urls import path


def _bar_page(filter_json: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Date range picker E2E</title>
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/range_slider.js" type="module"></script>
    <script src="/static/js/search_select.js" type="module"></script>
    <script src="/static/js/date_range_picker.js" defer></script>
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
            "date_purchased": {
                "value": "2024-03-15",
                "value2": "2024-09-20",
                "modifier": "BETWEEN",
            }
        }
    )
    return HttpResponse(_bar_page(filter_json))


urlpatterns = [
    path("test-date-range-picker/", empty_bar_view),
    path("test-date-range-picker-prefilled/", prefilled_bar_view),
]


PICKER = '[data-date-range-picker][data-input-name-prefix="filter-date-purchased"]'
POPUP = PICKER + " [data-date-range-calendar]"
HIDDEN_MIN = 'input[name="filter-date-purchased-min"]'
HIDDEN_MAX = 'input[name="filter-date-purchased-max"]'


def _segment(page, side: str, part: str):
    return page.locator(
        f'{PICKER} input[data-date-side="{side}"][data-date-part="{part}"]'
    )


def _day_cell(page, iso_date: str):
    return page.locator(
        f'{PICKER} [data-date-range-grid] button[data-date="{iso_date}"]'
    )


def _popup_is_open(page) -> bool:
    return "hidden" not in (page.locator(POPUP).get_attribute("class") or "")


def _submit_filter_bar(page):
    with page.expect_navigation():
        page.evaluate(
            "document.getElementById('filter-bar-form')"
            ".dispatchEvent(new Event('submit', {cancelable: true}))"
        )


def _filter_from_url(url: str) -> dict:
    query = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(query)
    raw = params.get("filter", [""])[0]
    return json.loads(raw) if raw else {}


# ── Segmented manual entry ──────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_typing_fills_parts_and_serializes_between(live_server, page):
    """Digits flow through the parts (DD → MM → YYYY → DD …) with
    auto-advance, ending in a BETWEEN criterion on submit."""
    page.goto(live_server.url + "/test-date-range-picker/")
    _segment(page, "min", "day").click()
    page.keyboard.type("1503202420092024")
    assert page.locator(HIDDEN_MIN).input_value() == "2024-03-15"
    assert page.locator(HIDDEN_MAX).input_value() == "2024-09-20"
    _submit_filter_bar(page)
    parsed = _filter_from_url(page.url)
    assert parsed == {
        "date_purchased": {
            "value": "2024-03-15",
            "value2": "2024-09-20",
            "modifier": "BETWEEN",
        }
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_placeholder_fills_from_the_right(live_server, page):
    """Typing 19 into the YYYY part shows YYY1 then YY19."""
    page.goto(live_server.url + "/test-date-range-picker/")
    year_segment = _segment(page, "min", "year")
    year_segment.click()
    page.keyboard.press("1")
    assert year_segment.input_value() == "YYY1"
    page.keyboard.press("9")
    assert year_segment.input_value() == "YY19"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_min_side_only_serializes_greater_than(live_server, page):
    page.goto(live_server.url + "/test-date-range-picker/")
    _segment(page, "min", "day").click()
    page.keyboard.type("15062024")
    _submit_filter_bar(page)
    parsed = _filter_from_url(page.url)
    assert parsed == {
        "date_purchased": {"value": "2024-06-15", "modifier": "GREATER_THAN"}
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_backspace_reverts_part_to_placeholder(live_server, page):
    page.goto(live_server.url + "/test-date-range-picker/")
    _segment(page, "min", "day").click()
    page.keyboard.type("15032024")
    assert page.locator(HIDDEN_MIN).input_value() == "2024-03-15"
    month_segment = _segment(page, "min", "month")
    month_segment.click()
    page.keyboard.press("Backspace")
    assert month_segment.input_value() == ""
    # An incomplete date no longer commits to the hidden input.
    assert page.locator(HIDDEN_MIN).input_value() == ""


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_only_numbers_can_be_typed(live_server, page):
    page.goto(live_server.url + "/test-date-range-picker/")
    day_segment = _segment(page, "min", "day")
    day_segment.click()
    page.keyboard.type("ab-/")
    assert day_segment.input_value() == ""


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_invalid_calendar_date_does_not_commit(live_server, page):
    """31-02-2024 fills all parts but is not a real date — no hidden value."""
    page.goto(live_server.url + "/test-date-range-picker/")
    _segment(page, "min", "day").click()
    page.keyboard.type("31022024")
    assert page.locator(HIDDEN_MIN).input_value() == ""


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_clicking_container_activates_first_part(live_server, page):
    page.goto(live_server.url + "/test-date-range-picker/")
    page.locator(PICKER + " [data-date-range-field]").click(position={"x": 5, "y": 5})
    focused = page.evaluate(
        "document.activeElement.getAttribute('data-date-part') + ':' +"
        "document.activeElement.getAttribute('data-date-side')"
    )
    assert focused == "day:min"


# ── Calendar popup ──────────────────────────────────────────────────────────


def _open_calendar(page):
    page.locator(PICKER + " [data-date-range-calendar-toggle]").click()


def _current_month_iso(day_of_month: int) -> str:
    today = datetime.date.today()
    return today.replace(day=day_of_month).isoformat()


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_calendar_pick_range_then_select(live_server, page):
    page.goto(live_server.url + "/test-date-range-picker/")
    _open_calendar(page)
    assert _popup_is_open(page)
    first_pick = _current_month_iso(10)
    second_pick = _current_month_iso(20)
    _day_cell(page, first_pick).click()
    assert page.locator(HIDDEN_MIN).input_value() == first_pick
    assert page.locator(HIDDEN_MAX).input_value() == ""
    _day_cell(page, second_pick).click()
    assert page.locator(HIDDEN_MAX).input_value() == second_pick
    page.locator(PICKER + " [data-date-range-select]").click()
    assert not _popup_is_open(page)
    _submit_filter_bar(page)
    parsed = _filter_from_url(page.url)
    assert parsed == {
        "date_purchased": {
            "value": first_pick,
            "value2": second_pick,
            "modifier": "BETWEEN",
        }
    }


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_picking_before_start_restarts_the_range(live_server, page):
    """With the StartDate anchored, picking an earlier date clears the range
    and the clicked date becomes the new StartDate."""
    page.goto(live_server.url + "/test-date-range-picker/")
    _open_calendar(page)
    _day_cell(page, _current_month_iso(20)).click()
    _day_cell(page, _current_month_iso(10)).click()
    assert page.locator(HIDDEN_MIN).input_value() == _current_month_iso(10)
    assert page.locator(HIDDEN_MAX).input_value() == ""


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_completed_range_anchor_moves_to_end(live_server, page):
    """After both dates are picked the EndDate becomes the anchor, so a
    further pick inside the range moves the StartDate."""
    page.goto(live_server.url + "/test-date-range-picker/")
    _open_calendar(page)
    _day_cell(page, _current_month_iso(10)).click()
    _day_cell(page, _current_month_iso(20)).click()
    _day_cell(page, _current_month_iso(15)).click()
    assert page.locator(HIDDEN_MIN).input_value() == _current_month_iso(15)
    assert page.locator(HIDDEN_MAX).input_value() == _current_month_iso(20)


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_preset_fills_both_dates(live_server, page):
    page.goto(live_server.url + "/test-date-range-picker/")
    _open_calendar(page)
    page.locator(PICKER + ' [data-date-range-preset="last_7_days"]').click()
    today = datetime.date.today()
    assert (
        page.locator(HIDDEN_MIN).input_value()
        == (today - datetime.timedelta(days=6)).isoformat()
    )
    assert page.locator(HIDDEN_MAX).input_value() == today.isoformat()
    # Presets keep the popup open; Select commits and closes.
    assert _popup_is_open(page)


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_clear_clears_dates_but_keeps_popup_open(live_server, page):
    page.goto(live_server.url + "/test-date-range-picker/")
    _open_calendar(page)
    _day_cell(page, _current_month_iso(10)).click()
    _day_cell(page, _current_month_iso(20)).click()
    page.locator(PICKER + " [data-date-range-clear]").click()
    assert page.locator(HIDDEN_MIN).input_value() == ""
    assert page.locator(HIDDEN_MAX).input_value() == ""
    assert _popup_is_open(page)


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_cancel_clears_dates_and_closes_popup(live_server, page):
    page.goto(live_server.url + "/test-date-range-picker/")
    _open_calendar(page)
    _day_cell(page, _current_month_iso(10)).click()
    _day_cell(page, _current_month_iso(20)).click()
    page.locator(PICKER + " [data-date-range-cancel]").click()
    assert page.locator(HIDDEN_MIN).input_value() == ""
    assert page.locator(HIDDEN_MAX).input_value() == ""
    assert not _popup_is_open(page)


# ── Prefill round-trip ──────────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_date_range_picker_e2e")
def test_prefilled_picker_round_trips_unchanged(live_server, page):
    page.goto(live_server.url + "/test-date-range-picker-prefilled/")
    assert _segment(page, "min", "day").input_value() == "15"
    assert _segment(page, "min", "month").input_value() == "03"
    assert _segment(page, "min", "year").input_value() == "2024"
    assert _segment(page, "max", "day").input_value() == "20"
    assert page.locator(HIDDEN_MIN).input_value() == "2024-03-15"
    assert page.locator(HIDDEN_MAX).input_value() == "2024-09-20"
    _submit_filter_bar(page)
    parsed = _filter_from_url(page.url)
    assert parsed["date_purchased"] == {
        "value": "2024-03-15",
        "value2": "2024-09-20",
        "modifier": "BETWEEN",
    }
