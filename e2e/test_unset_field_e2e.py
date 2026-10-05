"""⊘ posting none from a real form."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django import forms
from django.http import HttpRequest, HttpResponse
from django.test import override_settings
from django.urls import path
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt
from playwright.sync_api import Page, expect

from common.components import (
    ControlButton,
    Form,
    FormFields,
)
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.layout import render_page
from games.forms import (
    ChoiceSearchSelectWidget,
    DatePickerWidget,
    PrimitiveWidgetsMixin,
    TemporalFormField,
    UnsetFieldsForm,
    UnsetWidget,
)
from timetracker.urls import urlpatterns as base_urlpatterns

LETTERS = [("a", "Alpha"), ("b", "Bravo")]
PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


class EditForm(PrimitiveWidgetsMixin, UnsetFieldsForm):
    letter = forms.ChoiceField(
        required=False,
        choices=LETTERS,
        widget=UnsetWidget(
            ChoiceSearchSelectWidget(placeholder="Keep: mixed"),
            none_label="No letter",
        ),
    )
    note = forms.CharField(
        required=False,
        widget=UnsetWidget(
            forms.Textarea(attrs={"rows": 2, "placeholder": "Keep: mixed"}),
            none_label="No note",
        ),
    )
    day = forms.DateField(
        required=False,
        widget=UnsetWidget(
            DatePickerWidget(presentation=PRESENTATION, label="Day"),
            none_label="No day",
        ),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        when = TemporalFormField(
            presentation=PRESENTATION, label="When", required=False
        )
        when.widget = UnsetWidget(when.widget, none_label="No date")
        self.fields["when"] = when


@csrf_exempt
def edit_page_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = EditForm(data=request.POST)
        assert form.is_valid(), form.errors
        return HttpResponse(
            "".join(
                f'<p id="{name}">{escape(repr(form.cleaned_data[name]))}</p>'
                for name in form.fields
            )
        )
    return render_page(
        request,
        Form(method="post")[
            FormFields(
                EditForm(
                    initial={
                        "letter": "a",
                        "note": "Hello",
                        "day": datetime.date(2024, 5, 6),
                        "when": "1997",
                    }
                )
            ),
            ControlButton(type="submit")["Save"],
        ],
        title="Unset field harness",
    )


urlpatterns = [
    *base_urlpatterns,
    path("test-unset-field/", edit_page_view),
]

HARNESS = override_settings(ROOT_URLCONF="e2e.test_unset_field_e2e")


@pytest.fixture
def console_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    return errors


def _open(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}/test-unset-field/")


def _submit(page: Page) -> None:
    with page.expect_navigation():
        page.get_by_role("button", name="Save").click()


def _search(page: Page):
    return page.locator("search-select[name='letter'] [data-search-select-search]")


@HARNESS
def test_pressing_states_none_on_both(live_server, page: Page, console_errors):
    _open(page, live_server)
    note = page.locator("textarea[name='note']")
    expect(note).to_have_value("Hello")
    expect(_search(page)).to_have_value("Alpha")

    for label in ("No letter", "No note"):
        toggle = page.get_by_role("button", name=label)
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "true")
    expect(note).to_be_disabled()
    expect(note).to_have_value("")
    expect(note).to_have_attribute("placeholder", "No note")
    expect(_search(page)).to_be_disabled()
    expect(_search(page)).to_have_attribute("placeholder", "No letter")

    _submit(page)
    assert page.inner_text("#letter") == "''"
    assert page.inner_text("#note") == "''"
    assert console_errors == []


@HARNESS
def test_pressing_again_posts_the_value(live_server, page: Page, console_errors):
    _open(page, live_server)
    for label in ("No letter", "No note"):
        toggle = page.get_by_role("button", name=label)
        toggle.click()
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "false")
    expect(page.locator("textarea[name='note']")).to_have_value("Hello")
    expect(_search(page)).to_have_value("Alpha")

    _submit(page)
    assert page.inner_text("#letter") == "'a'"
    assert page.inner_text("#note") == "'Hello'"
    assert console_errors == []


@HARNESS
def test_a_pressed_picker_ignores_its_clear_and_box(
    live_server, page: Page, console_errors
):
    _open(page, live_server)
    toggle = page.get_by_role("button", name="No letter")
    toggle.click()
    clear = page.locator("search-select[name='letter'] [data-search-select-clear]")
    expect(clear).to_be_hidden()
    clear.dispatch_event("click")
    _search(page).click(force=True)
    expect(page.get_by_role("option", name="Bravo")).to_be_hidden()
    toggle.click()
    expect(_search(page)).to_have_value("Alpha")

    _submit(page)
    assert page.inner_text("#letter") == "'a'"
    assert console_errors == []


@HARNESS
def test_an_emptied_field_keeps(live_server, page: Page, console_errors):
    _open(page, live_server)
    page.locator("textarea[name='note']").fill("")
    page.locator("search-select[name='letter'] [data-search-select-clear]").click()

    _submit(page)
    assert page.inner_text("#letter") == "<Keep.KEEP: 'keep'>"
    assert page.inner_text("#note") == "<Keep.KEEP: 'keep'>"
    assert console_errors == []


@HARNESS
def test_composites_state_none_and_restore(live_server, page: Page, console_errors):
    _open(page, live_server)
    _submit(page)
    untouched_when = page.inner_text("#when")
    _open(page, live_server)
    day = page.locator("date-picker [data-date-picker-hidden]")
    expect(day).to_have_value("2024-05-06")
    page.get_by_role("button", name="No day").click()
    expect(day).to_have_value("")
    expect(page.locator("date-picker input[data-date-part]").first).to_be_disabled()
    page.get_by_role("button", name="No date").click()
    page.get_by_role("button", name="No date").click()

    _submit(page)
    assert page.inner_text("#day") == "None"
    assert page.inner_text("#when") == untouched_when
    assert console_errors == []


@HARNESS
def test_a_temporal_field_states_none(live_server, page: Page, console_errors):
    _open(page, live_server)
    page.get_by_role("button", name="No date").click()
    _submit(page)
    assert page.inner_text("#when") == "None"
    assert console_errors == []
