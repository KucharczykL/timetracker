import pytest
from asgiref.sync import async_to_sync
from django import forms
from django.http import (
    HttpRequest,
    HttpResponse,
    JsonResponse,
    StreamingHttpResponse,
)
from django.test import AsyncClient, Client, override_settings
from django.urls import path
from html_answers import NATIVE_SELECT_SHOWN_AT, html_answer_faults

from common.components import FormFields
from games.forms import PrimitiveWidgetsMixin
from games.models import Platform

LETTERS = (("a", "Alpha"), ("b", "Bravo"))
SELECT_MARKUP = "<select name='x'></select>"


class ModelPickForm(PrimitiveWidgetsMixin, forms.Form):
    platform = forms.ModelChoiceField(queryset=Platform.objects.none())


class ChoicePickForm(PrimitiveWidgetsMixin, forms.Form):
    letter = forms.ChoiceField(choices=LETTERS)


def _page(form: forms.Form) -> HttpResponse:
    return HttpResponse(str(FormFields(form)), content_type="text/html")


def model_pick(request: HttpRequest) -> HttpResponse:
    return _page(ModelPickForm())


def choice_pick(request: HttpRequest) -> HttpResponse:
    return _page(ChoicePickForm())


def dialog_select(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"kind": "page", "html": SELECT_MARKUP})


urlpatterns = [
    path("model-pick/", model_pick),
    path("choice-pick/", choice_pick),
    path("dialog-select/", dialog_select),
]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_a_model_field_on_the_default_widget_fails():
    with pytest.raises(AssertionError, match="native select"):
        Client().get("/model-pick/")


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_a_fixed_choice_field_renders_its_picker():
    assert Client().get("/choice-pick/").status_code == 200


def test_the_settings_kit_may_show_a_native_select():
    page = HttpResponse(SELECT_MARKUP, content_type="text/html")
    assert html_answer_faults(NATIVE_SELECT_SHOWN_AT, page) == []
    assert html_answer_faults("/tracker/settings/", page) != []


def test_a_floating_panel_must_be_a_manual_popover():
    page = HttpResponse("<div data-menu hidden></div>", content_type="text/html")
    assert html_answer_faults("/tracker/", page) != []


def test_a_dialog_page_holding_a_select_is_a_fault():
    page = JsonResponse({"kind": "page", "html": SELECT_MARKUP})
    assert html_answer_faults("/tracker/x/", page, dialog=True) != []
    assert html_answer_faults("/tracker/x/", page) == []


def test_a_json_list_is_no_dialog_page():
    assert (
        html_answer_faults("/api/x/", JsonResponse([], safe=False), dialog=True) == []
    )


def test_an_element_named_select_something_passes():
    page = HttpResponse("<select-list></select-list>", content_type="text/html")
    assert html_answer_faults("/tracker/", page) == []


def test_a_refused_page_is_checked_too():
    page = HttpResponse("<select>", content_type="text/html", status=400)
    assert html_answer_faults("/tracker/", page) != []


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_a_dialog_request_reads_the_page_answer():
    with pytest.raises(AssertionError, match="native select"):
        Client().get("/dialog-select/", headers={"X-Form-Dialog": "1"})
    assert Client().get("/dialog-select/").status_code == 200


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_an_async_dialog_request_is_checked_too():
    get = async_to_sync(AsyncClient().get)
    with pytest.raises(AssertionError, match="native select"):
        get("/dialog-select/", headers={"X-Form-Dialog": "1"})
    assert get("/dialog-select/").status_code == 200


def test_an_uppercase_select_is_a_fault():
    page = HttpResponse("<SELECT name='x'>", content_type="TEXT/HTML")
    assert html_answer_faults("/tracker/", page) != []


def test_a_dialog_is_no_floating_panel():
    page = HttpResponse("<dialog data-menu></dialog>", content_type="text/html")
    assert html_answer_faults("/tracker/", page) == []


def test_a_panel_tag_with_a_digit_is_read():
    page = HttpResponse("<h2 data-menu></h2>", content_type="text/html")
    assert html_answer_faults("/tracker/", page) != []


def test_a_streamed_html_answer_is_refused():
    page = StreamingHttpResponse(iter(["<p>"]), content_type="text/html")
    with pytest.raises(AssertionError, match="streamed"):
        html_answer_faults("/tracker/", page)


def test_a_streamed_file_passes():
    page = StreamingHttpResponse(iter([b"x"]), content_type="application/zip")
    assert html_answer_faults("/tracker/", page) == []
