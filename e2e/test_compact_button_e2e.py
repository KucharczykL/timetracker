"""Compact buttons fit their control without growing it."""

import pytest
from django.http import HttpResponse
from django.test import override_settings
from django.urls import path, reverse
from playwright.sync_api import FloatRect, Page

from common.components import ComboboxDropdown, FilterSelect, SearchSelect

OPTIONS = [{"value": "1", "label": "Hades", "data": {}}]


def harness_view(request):
    facet = ComboboxDropdown(
        label="Game",
        content=FilterSelect(
            field_name="game",
            options=OPTIONS,
            layout="panel",
            search_aria_label="Game",
        ),
        id="facet-dropdown",
    )
    field = SearchSelect(name="device", selected=OPTIONS, options=OPTIONS)
    return HttpResponse(f"""<!DOCTYPE html><html><head>
    <link rel="icon" href="data:,">
    <link rel="stylesheet" href="/static/base.css">
    <script type="module" src="/static/js/dist/elements/search-select.js"></script>
    <script type="module" src="/static/js/dist/elements/drop-down.js"></script>
    </head><body style="padding:24px;width:400px">
    <div>{field}</div><div style="margin-top:24px">{facet}</div>
    </body></html>""")


urlpatterns = [path("compact/", harness_view)]


def _box(page: Page, selector: str) -> FloatRect:
    box = page.locator(selector).first.bounding_box()
    assert box is not None, selector
    return box


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="e2e.test_compact_button_e2e")
def test_row_actions_and_clear_fit_their_control(live_server, page: Page):
    page.goto(f"{live_server.url}/compact/")
    clear = _box(page, "[data-search-select-clear]")
    field = _box(page, "search-select[name=device] [data-search-select-box]")
    assert clear["height"] == 32 and clear["width"] == 32
    assert field["height"] == 42

    page.locator("#facet-dropdownLink").click()
    row = _box(page, "[role=dialog] [data-search-select-option]")
    action = _box(page, '[data-search-select-action="include"]')
    assert row["height"] == 36
    assert action["height"] == 32
    assert row["y"] <= action["y"] and action["y"] + 32 <= row["y"] + row["height"]


@pytest.mark.django_db(transaction=True)
def test_date_time_buttons_fit_the_field_at_phone_width(
    live_server, page: Page, e2e_user
):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    page.goto(f"{live_server.url}{reverse('games:add_session')}")

    buttons = page.locator("[data-date-picker-calendar-toggle], [data-date-time-copy]")
    assert buttons.count() >= 2
    for index in range(buttons.count()):
        box = buttons.nth(index).bounding_box()
        assert box is not None
        assert box["height"] == 32 and box["width"] == 32
    overflowing = page.evaluate(
        """() => [...document.querySelectorAll('[data-date-picker-calendar-toggle]')]
            .map(button => button.parentElement)
            .filter(field => field.scrollWidth > field.clientWidth + 1).length"""
    )
    assert overflowing == 0
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
