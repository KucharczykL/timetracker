"""A SearchSelect over a form field's fixed choices."""

import pytest
from django import forms

from common.components import FormFields
from games.forms import (
    ChoiceSearchSelectWidget,
    apply_primitive_widget_classes,
    host_choices,
)
from games.models import Device

LETTERS = [("a", "A"), ("b", "B"), ("c", "C")]
SITE_DEFAULT = ("", "Use site default (UTC)")
PROMPT = ("", "---------")


def _render(field: forms.Field, initial=None) -> str:
    class OneFieldForm(forms.Form):
        pass

    form = OneFieldForm(initial={"choice": initial})
    form.fields["choice"] = field
    return str(FormFields(form))


def _search_box(html: str) -> str:
    marker = html.index("data-search-select-search")
    return html[html.rindex("<", 0, marker) : html.index(">", marker)]


def _optional(choices, **widget) -> forms.TypedChoiceField:
    return forms.TypedChoiceField(
        required=False,
        choices=choices,
        empty_value=None,
        widget=ChoiceSearchSelectWidget(**widget),
    )


def _required(choices, **widget) -> forms.ChoiceField:
    return forms.ChoiceField(choices=choices, widget=ChoiceSearchSelectWidget(**widget))


def test_every_choice_is_a_row():
    html = _render(_optional(LETTERS))
    for value, label in LETTERS:
        assert f'data-value="{value}"' in html
        assert f'data-label="{label}"' in html
    assert 'search-url=""' in html


def test_an_optional_empty_choice_is_the_none_row():
    html = _render(_optional([SITE_DEFAULT, *LETTERS]))
    assert "data-search-select-none-option" in html
    assert 'data-label="Use site default (UTC)"' in html
    assert "data-search-select-none=" in html
    assert 'value="Use site default (UTC)"' in _search_box(html)


def test_an_empty_choice_anywhere_is_the_none_row():
    html = _render(_optional([*LETTERS, ("", "Nothing")]))
    assert 'none-label="Nothing"' in html


def test_a_value_no_choice_names_holds_none():
    html = _render(_optional([SITE_DEFAULT, *LETTERS]), initial="gone")
    assert "data-search-select-none=" in html
    assert 'value="gone"' not in html


def test_without_an_empty_choice_nothing_is_picked():
    html = _render(_optional(LETTERS, placeholder="Keep: mixed"), initial="gone")
    assert "data-search-select-none" not in html
    assert 'placeholder="Keep: mixed"' in _search_box(html)
    assert " value=" not in _search_box(html)


def test_a_required_empty_choice_is_dropped():
    html = _render(_required([PROMPT, *LETTERS]))
    assert "---------" not in html
    assert "data-search-select-none" not in html
    assert 'placeholder="Choose…"' in _search_box(html)


def test_the_caller_placeholder_wins():
    html = _render(_required([PROMPT, *LETTERS], placeholder="Pick one"))
    assert 'placeholder="Pick one"' in _search_box(html)


def test_a_required_field_without_an_empty_choice():
    html = _render(_required(LETTERS))
    assert "data-search-select-none" not in html
    assert html.count("data-search-select-option") >= len(LETTERS)


def test_a_held_value_shows_its_label():
    html = _render(_optional([SITE_DEFAULT, *LETTERS]), initial="b")
    assert 'value="B"' in _search_box(html)
    assert 'name="choice" value="b"' in html or 'value="b" name="choice"' in html


def test_a_bool_initial_matches_its_key():
    field = _optional([("True", "Yes"), ("False", "No")])
    assert 'value="No"' in _search_box(_render(field, initial=False))


@pytest.mark.parametrize(
    "field",
    [
        pytest.param(
            forms.CharField(required=False, widget=ChoiceSearchSelectWidget()),
            id="no choices",
        ),
        pytest.param(_optional([("Letters", LETTERS)]), id="grouped"),
    ],
)
def test_it_refuses(field):
    with pytest.raises(ValueError):
        _render(field)


@pytest.mark.django_db
def test_it_refuses_a_queryset_before_reading_it(django_assert_num_queries):
    field = forms.ModelChoiceField(
        queryset=Device.objects.all(), widget=ChoiceSearchSelectWidget()
    )
    with django_assert_num_queries(0), pytest.raises(ValueError):
        _render(field)


def test_host_choices_after_a_swap():
    field = forms.TypedChoiceField(
        required=False, choices=[SITE_DEFAULT, *LETTERS], empty_value=None
    )
    host_choices(field, ChoiceSearchSelectWidget())
    html = _render(field)
    assert 'data-label="B"' in html
    assert "data-search-select-none-option" in html


def test_host_choices_after_required_changes():
    field = _required([SITE_DEFAULT, *LETTERS])
    field.required = False
    host_choices(field, field.widget)
    assert "data-search-select-none-option" in _render(field)


@pytest.mark.parametrize(
    ("data", "expected"),
    [({"choice": "False"}, False), ({"choice": ""}, None), ({}, None)],
    ids=["picked", "none", "absent"],
)
def test_the_post_cleans(data, expected):
    class EmulatedForm(forms.Form):
        choice = forms.TypedChoiceField(
            required=False,
            choices=[("True", "Yes"), ("False", "No")],
            coerce=lambda value: value == "True",
            empty_value=None,
            widget=ChoiceSearchSelectWidget(),
        )

    form = EmulatedForm(data)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["choice"] is expected


def test_native_classes_never_reach_it():
    field = _optional(LETTERS)
    apply_primitive_widget_classes({"choice": field})
    assert "class" not in field.widget.attrs
