"""The temporal field in a real browser, with the script and without it.

No page hosts one until #969, so this mounts a synthetic form. The
assertion that matters is the last one: both paths store the same value.
"""

from zoneinfo import ZoneInfo

from django import forms
from django.http import HttpRequest, HttpResponse
from django.test import override_settings
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from common.components import ControlButton, Form, FormFields, ModuleScript
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.layout import render_page
from games.forms import TemporalFormField
from timetracker.urls import urlpatterns as base_urlpatterns


def _presentation() -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
    )


class ReleaseForm(forms.Form):
    released = TemporalFormField(presentation=_presentation(), label="Release date")


@csrf_exempt
def temporal_page_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ReleaseForm(data=request.POST)
        # The canonical string is what a column keeps.
        stored = "refused"
        if form.is_valid():
            value = form.cleaned_data["released"]
            stored = value.serialize() if value else "nothing"
        return HttpResponse(f'<p id="stored">{stored}</p>')
    return render_page(
        request,
        Form(method="post")[
            FormFields(ReleaseForm()),
            ControlButton(type="submit")["Save"],
        ],
        title="Temporal harness",
        # A widget renders to text, so its element's Media never bubbles.
        scripts=ModuleScript("dist/elements/temporal-field.js"),
    )


urlpatterns = [*base_urlpatterns, path("test-temporal/", temporal_page_view)]


@override_settings(ROOT_URLCONF="e2e.test_temporal_field_e2e")
def test_a_typed_day_stores_as_a_day(live_server, page):
    page.goto(f"{live_server.url}/test-temporal/")
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")

    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("19840622")
    page.click("button[type=submit]")

    assert page.inner_text("#stored") == "1984-06-22"


@override_settings(ROOT_URLCONF="e2e.test_temporal_field_e2e")
def test_the_keyboard_alone_reaches_a_decade(live_server, page):
    page.goto(f"{live_server.url}/test-temporal/")
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")

    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("1982")
    page.click("[data-temporal-disclosure]")
    page.check("[data-temporal-toggle='whole_decade_start']")
    page.click("button[type=submit]")

    assert page.inner_text("#stored") == "198X"


@override_settings(ROOT_URLCONF="e2e.test_temporal_field_e2e")
def test_a_range_reaches_both_ends(live_server, page):
    page.goto(f"{live_server.url}/test-temporal/")
    page.wait_for_selector("[data-temporal-segments='start']:not([hidden])")

    page.click("[data-date-part='year'][data-date-side='start']")
    page.keyboard.type("1984")
    page.click("[data-temporal-disclosure]")
    page.check("[data-temporal-toggle='add_end']")
    page.click("[data-date-part='year'][data-date-side='end']")
    page.keyboard.type("1986")
    page.click("button[type=submit]")

    assert page.inner_text("#stored") == "1984/1986"


@override_settings(ROOT_URLCONF="e2e.test_temporal_field_e2e")
def test_the_same_value_stores_with_no_script(live_server, browser):
    """The script enhances. Without it the native controls stand."""
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(f"{live_server.url}/test-temporal/")

    assert page.is_visible("[data-temporal-input='start_year']")
    assert page.is_hidden("[data-temporal-segments='start']")

    page.select_option("[data-temporal-input='kind']", "date")
    page.fill("[data-temporal-input='start_year']", "1984")
    page.fill("[data-temporal-input='start_month']", "6")
    page.fill("[data-temporal-input='start_day']", "22")
    page.click("button[type=submit]")

    assert page.inner_text("#stored") == "1984-06-22"
    context.close()
