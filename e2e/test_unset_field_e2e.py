"""The ⊘ toggle posting none from a real form."""

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
    Fragment,
    ModuleScript,
)
from common.layout import render_page
from games.forms import (
    ChoiceSearchSelectWidget,
    PrimitiveWidgetsMixin,
    UnsetFieldsForm,
    UnsetWidget,
)
from timetracker.urls import urlpatterns as base_urlpatterns

LETTERS = [("a", "Alpha"), ("b", "Bravo")]


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
            FormFields(EditForm(initial={"letter": "a", "note": "Hello"})),
            ControlButton(type="submit")["Save"],
        ],
        title="Unset field harness",
        # Picker Media does not bubble yet.
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/drop-down.js"),
        ),
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
def test_an_emptied_field_keeps(live_server, page: Page, console_errors):
    _open(page, live_server)
    page.locator("textarea[name='note']").fill("")
    page.locator("search-select[name='letter'] [data-search-select-clear]").click()

    _submit(page)
    assert page.inner_text("#letter") == "<Keep.KEEP: 'keep'>"
    assert page.inner_text("#note") == "<Keep.KEEP: 'keep'>"
    assert console_errors == []


@HARNESS
def test_without_scripting_the_checkbox_states_none(live_server, browser):
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    try:
        _open(page, live_server)
        expect(page.get_by_role("button", name="No note")).to_be_hidden()
        page.get_by_role("checkbox", name="No note").check()
        _submit(page)
        assert page.inner_text("#note") == "''"
    finally:
        context.close()
