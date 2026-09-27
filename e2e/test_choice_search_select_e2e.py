"""A fixed-choice SearchSelect in a real browser, posting a real form.

One field holds none through its empty choice; the other declares none,
so its × leaves the key out, which a bulk form reads as "leave as it is".
"""

import pytest
from django import forms
from django.http import HttpRequest, HttpResponse
from django.test import override_settings
from django.urls import path
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
from games.forms import ChoiceSearchSelectWidget
from timetracker.urls import urlpatterns as base_urlpatterns

LETTERS = [("a", "Alpha"), ("b", "Bravo"), ("c", "Charlie")]


class LetterForm(forms.Form):
    with_none = forms.TypedChoiceField(
        required=False,
        choices=[("", "No letter"), *LETTERS],
        empty_value=None,
        widget=ChoiceSearchSelectWidget(),
    )
    without_none = forms.TypedChoiceField(
        required=False,
        choices=LETTERS,
        empty_value=None,
        widget=ChoiceSearchSelectWidget(placeholder="Keep: mixed"),
    )


@csrf_exempt
def letter_page_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = LetterForm(data=request.POST)
        assert form.is_valid(), form.errors
        return HttpResponse(
            "".join(
                f'<p id="{name}">{form.cleaned_data[name]!r}</p>'
                f'<p id="{name}-posted">{name in request.POST}</p>'
                for name in form.fields
            )
        )
    return render_page(
        request,
        Form(method="post")[
            FormFields(LetterForm(initial={"with_none": "a", "without_none": "a"})),
            ControlButton(type="submit")["Save"],
        ],
        title="Fixed choices harness",
        # A widget renders to text, so its element's Media never bubbles; an
        # anonymous page has no navbar to load drop-down.js either.
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/drop-down.js"),
        ),
    )


urlpatterns = [
    *base_urlpatterns,
    path("test-fixed-choices/", letter_page_view),
]


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


def _open(page: Page, live_server):
    page.goto(f"{live_server.url}/test-fixed-choices/")


def _picker(page: Page, name: str):
    picker = page.locator(f"search-select[name='{name}']")
    return picker, picker.locator("[data-search-select-search]")


def _submit(page: Page) -> None:
    with page.expect_navigation():
        page.get_by_role("button", name="Save").click()


HARNESS = override_settings(ROOT_URLCONF="e2e.test_choice_search_select_e2e")


@HARNESS
def test_a_click_picks_a_choice(live_server, page: Page, console_errors):
    _open(page, live_server)
    picker, search = _picker(page, "with_none")
    expect(search).to_have_value("Alpha")

    search.click()
    picker.get_by_role("option", name="Bravo").click()
    expect(search).to_have_value("Bravo")

    _submit(page)
    assert page.inner_text("#with_none") == "'b'"
    assert console_errors == []


@HARNESS
def test_the_keyboard_picks_a_choice(live_server, page: Page, console_errors):
    _open(page, live_server)
    _, search = _picker(page, "without_none")

    search.click()
    search.fill("")
    # An empty query highlights the first choice; one step reaches the second.
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(search).to_have_value("Bravo")

    _submit(page)
    assert page.inner_text("#without_none") == "'b'"
    assert console_errors == []


@HARNESS
def test_typing_filters_the_choices_but_keeps_none(live_server, page: Page):
    _open(page, live_server)
    picker, search = _picker(page, "with_none")

    search.click()
    search.fill("char")
    expect(picker.get_by_role("option", name="Charlie")).to_be_visible()
    expect(picker.get_by_role("option", name="Alpha")).to_be_hidden()
    expect(picker.get_by_role("option", name="Bravo")).to_be_hidden()
    expect(picker.get_by_role("option", name="No letter")).to_be_visible()


@HARNESS
def test_clear_holds_none_where_the_choices_state_one(
    live_server, page: Page, console_errors
):
    _open(page, live_server)
    picker, search = _picker(page, "with_none")

    picker.get_by_role("button", name="Clear").click()
    expect(search).to_have_value("No letter")

    _submit(page)
    assert page.inner_text("#with_none") == "None"
    assert page.inner_text("#with_none-posted") == "True"
    assert console_errors == []


@HARNESS
def test_clear_leaves_the_key_out_where_the_choices_state_no_none(
    live_server, page: Page, console_errors
):
    _open(page, live_server)
    picker, search = _picker(page, "without_none")

    picker.get_by_role("button", name="Clear").click()
    expect(search).to_have_value("")
    expect(search).to_have_attribute("placeholder", "Keep: mixed")

    _submit(page)
    assert page.inner_text("#without_none") == "None"
    assert page.inner_text("#without_none-posted") == "False"
    assert console_errors == []
