"""End-to-end Playwright test for the RangeSlider JS synchronization, cross-over, and clamping behavior."""

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path

from common.components import FilterBar


def _bar_page(filter_json: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Range Slider E2E</title>
    <script src="/static/js/htmx.min.js"></script>
    <script src="/static/js/dist/range_slider.js" type="module"></script>
    <script src="/static/js/dist/search_select.js" type="module"></script>
    <script src="/static/js/dist/filter_bar.js" type="module"></script>
</head>
<body>
    {FilterBar(filter_json=filter_json, preset_list_url="/p/l", preset_save_url="/p/s")}
</body>
</html>"""


def empty_bar_view(request):
    return HttpResponse(_bar_page())


urlpatterns = [
    path("test-range-slider/", empty_bar_view),
]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_range_slider_e2e")
def test_range_slider_crossover_min_higher_than_max(live_server, page):
    page.goto(live_server.url + "/test-range-slider/")

    # 1. Start with known state: Min is empty, Max is empty
    min_input = page.locator('input[name="filter-session-count-min"]')
    max_input = page.locator('input[name="filter-session-count-max"]')

    # 2. Type "20" into max input
    max_input.fill("20")

    # 3. Type "50" into min input (which is higher than 20)
    min_input.fill("50")

    # 4. Max input should have automatically synchronized/snapped to 50
    assert max_input.input_value() == "50"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_range_slider_e2e")
def test_range_slider_crossover_max_less_than_min(live_server, page):
    page.goto(live_server.url + "/test-range-slider/")

    min_input = page.locator('input[name="filter-session-count-min"]')
    max_input = page.locator('input[name="filter-session-count-max"]')

    # 1. Type "50" into min input
    min_input.fill("50")

    # 2. Type "30" into max input (which is less than 50)
    max_input.fill("30")

    # 3. Min input should have automatically synchronized/snapped to 30
    assert min_input.input_value() == "30"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_range_slider_e2e")
def test_range_slider_strict_bounds_clamping_on_blur(live_server, page):
    page.goto(live_server.url + "/test-range-slider/")

    min_input = page.locator('input[name="filter-session-count-min"]')
    max_input = page.locator('input[name="filter-session-count-max"]')

    # 1. Type value higher than dataMax (100 is max, type "150")
    max_input.fill("150")
    max_input.blur()  # triggers "change" event

    assert max_input.input_value() == "100"

    # 2. Type value lower than dataMin (0 is min, type "-20")
    min_input.fill("-20")
    min_input.blur()  # triggers "change" event

    assert min_input.input_value() == "0"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_range_slider_e2e")
def test_range_slider_empty_max_thumb_does_not_jump_to_beginning(live_server, page):
    page.goto(live_server.url + "/test-range-slider/")

    # Locate handles
    max_handle = page.locator(
        '.range-handle-max[data-target="filter-session-count-max"]'
    )

    # Initially, max_input is empty, so handle should sit at 100% (far right)
    style = max_handle.get_attribute("style")
    assert "left:100%" in style or "left: 100%" in style

    # Set min to 50
    min_input = page.locator('input[name="filter-session-count-min"]')
    min_input.fill("50")

    # Max handle should STILL stay at 100% since max input is still empty (defaults to max_value)
    style = max_handle.get_attribute("style")
    assert "left:100%" in style or "left: 100%" in style
