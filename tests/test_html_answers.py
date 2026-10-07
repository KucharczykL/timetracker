import pytest
from django import forms
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.test import Client, override_settings
from django.urls import path
from html_answers import NATIVE_SELECT_SHOWN_AT, html_answer_faults

from common.components import FormFields
from games.forms import PrimitiveWidgetsMixin
from games.models import Platform

LETTERS = (("a", "Alpha"), ("b", "Bravo"))


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


urlpatterns = [
    path("model-pick/", model_pick),
    path("choice-pick/", choice_pick),
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
    page = HttpResponse("<select name='x'></select>", content_type="text/html")
    assert html_answer_faults(NATIVE_SELECT_SHOWN_AT, page) == []
    assert html_answer_faults("/tracker/settings/", page) != []


def test_a_floating_panel_must_be_a_manual_popover():
    page = HttpResponse("<div data-menu hidden></div>", content_type="text/html")
    assert html_answer_faults("/tracker/", page) != []


def test_a_dialog_page_holding_a_select_is_a_fault():
    page = JsonResponse({"kind": "page", "html": "<select name='x'></select>"})
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
