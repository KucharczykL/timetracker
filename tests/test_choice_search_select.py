"""SearchSelect over a field's fixed choices."""

import copy
import re

import pytest
from django import forms

from common.components import FormFields, SearchSelect, render
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


def _hidden_values(html: str) -> list[str]:
    hidden = [
        tag
        for tag in re.findall(r"<input[^>]*>", html)
        if 'type="hidden"' in tag and 'name="choice"' in tag
    ]
    return [value for tag in hidden for value in re.findall(r'value="([^"]*)"', tag)]


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
    assert _hidden_values(html) == ["b"]


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
    with django_assert_num_queries(0), pytest.raises(TypeError):
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


def test_a_none_key_is_the_empty_choice():
    html = _render(_optional([(None, "Unknown"), *LETTERS]))
    assert 'none-label="Unknown"' in html
    assert "data-search-select-none=" in html


def test_integer_keys_post_as_text():
    field = forms.TypedChoiceField(
        required=False,
        choices=[(1, "One"), (2, "Two")],
        coerce=int,
        empty_value=None,
        widget=ChoiceSearchSelectWidget(),
    )
    html = _render(field, initial=2)
    assert 'value="Two"' in _search_box(html)
    assert _hidden_values(html) == ["2"]


def test_a_list_value_is_refused():
    with pytest.raises(TypeError):
        ChoiceSearchSelectWidget().render("choice", ["a", "b"])


@pytest.mark.parametrize(
    "field",
    [
        forms.MultipleChoiceField(choices=LETTERS),
        forms.ModelChoiceField(queryset=Device.objects.none()),
    ],
    ids=["multiple", "model"],
)
def test_host_choices_refuses(field):
    with pytest.raises(TypeError):
        host_choices(field, ChoiceSearchSelectWidget())


def test_clear_names_the_field_label():
    html = _render(_optional(LETTERS))
    clear = re.search(r"<button[^>]*aria-describedby=\"([^\"]+)\"", html)
    assert clear is not None
    assert f'id="{clear.group(1)}"' in html
    assert clear.group(1).startswith("id_choice")


def test_clearable_and_autofocus_reach_the_component():
    html = _render(_optional(LETTERS, clearable=False, autofocus=True))
    assert "autofocus" in _search_box(html)
    assert 'aria-label="Clear"' not in html


def test_an_explicit_empty_placeholder_stays_empty():
    assert 'placeholder=""' in _search_box(_render(_optional(LETTERS, placeholder="")))


def test_form_instances_hold_their_own_choices():
    widget = ChoiceSearchSelectWidget()
    widget.choices = list(LETTERS)
    copied = copy.deepcopy(widget)
    assert copied.choices == widget.choices
    assert copied.choices is not widget.choices


def _host_tag(html: str) -> str:
    start = html.index("<search-select")
    return html[start : html.index(">", start)]


def test_widget_data_attrs_reach_the_host():
    field = _optional(LETTERS)
    field.widget.attrs.update(
        {"data-setting-key": "THEME", "data-live-setting-control": ""}
    )
    host = _host_tag(_render(field))
    assert 'data-setting-key="THEME"' in host
    assert "data-live-setting-control" in host


def test_input_state_attrs_reach_the_search_box():
    field = _optional(LETTERS)
    field.widget.attrs.update({"aria-describedby": "help-id"})
    field.disabled = True
    box = _search_box(_render(field))
    assert re.search(r'\sdisabled(=""|\s|$)', box)
    assert 'aria-describedby="help-id"' in box


def test_an_attr_with_no_home_is_refused():
    field = _optional(LETTERS)
    field.widget.attrs["readonly"] = True
    with pytest.raises(ValueError, match="readonly"):
        _render(field)


def test_false_spelled_flags_stay_off():
    widget = ChoiceSearchSelectWidget()
    widget.choices = list(LETTERS)
    html = widget.render(
        "choice",
        None,
        {"id": "id_choice", "disabled": "false", "aria-invalid": "false"},
    )
    box = _search_box(html)
    assert not re.search(r'\sdisabled(=""|\s|$)', box)
    assert "aria-invalid" not in box


def test_an_invalid_field_marks_its_search_box():
    widget = ChoiceSearchSelectWidget()
    widget.choices = list(LETTERS)
    html = widget.render("choice", None, {"id": "id_choice", "aria-invalid": "true"})
    assert 'aria-invalid="true"' in _search_box(html)


def test_revert_on_leave_reaches_the_host():
    assert 'revert-on-leave="true"' in _host_tag(
        _render(_optional(LETTERS, revert_on_leave=True))
    )
    assert "revert-on-leave" not in _host_tag(_render(_optional(LETTERS)))


@pytest.mark.parametrize(
    "host_data",
    [{"title": "x"}, {"data-toggle": ""}],
    ids=["not data", "reserved"],
)
def test_host_data_is_refused(host_data):
    with pytest.raises(ValueError):
        SearchSelect(name="choice", host_data=host_data)


@pytest.mark.parametrize("shape", [{"multi_select": True}, {"panel": True}])
def test_revert_on_leave_is_single_select_and_field_hosted(shape):
    with pytest.raises(ValueError, match="revert_on_leave"):
        SearchSelect(name="choice", revert_on_leave=True, **shape)


def test_a_required_field_marks_its_search_box():
    assert 'aria-required="true"' in _search_box(_render(_required(LETTERS)))
    assert "aria-required" not in _search_box(_render(_optional(LETTERS)))


def test_required_reaches_the_search_box():
    html = render(SearchSelect(name="choice", required=True))
    assert 'aria-required="true"' in _search_box(html)
    assert "aria-required" not in _search_box(render(SearchSelect(name="choice")))


def _swapped(field: forms.Field) -> forms.Field:
    fields = {"choice": field}
    apply_primitive_widget_classes(fields)
    return fields["choice"]


@pytest.mark.parametrize(
    "field",
    [
        forms.ChoiceField(choices=LETTERS),
        forms.TypedChoiceField(choices=LETTERS, coerce=str),
    ],
    ids=["choice", "typed"],
)
def test_a_plain_select_becomes_the_picker(field):
    widget = _swapped(field).widget
    assert isinstance(widget, ChoiceSearchSelectWidget)
    assert widget.is_required
    assert widget.revert_on_leave
    assert widget.choices == LETTERS


def _clears(field: forms.Field) -> bool:
    return "data-search-select-clear" in _render(field)


def test_a_swapped_field_clears_only_with_a_none_row():
    assert _clears(
        _swapped(forms.ChoiceField(required=False, choices=[PROMPT, *LETTERS]))
    )
    for field in (
        forms.ChoiceField(required=False, choices=LETTERS),
        forms.ChoiceField(choices=[PROMPT, *LETTERS]),
    ):
        assert not _clears(_swapped(field))


def test_the_clear_follows_a_later_choices_assignment():
    field = _swapped(forms.ChoiceField(required=False, choices=LETTERS))
    field.choices = [PROMPT, *LETTERS]
    assert _clears(field)


def test_aria_required_follows_the_form():
    class QuietForm(forms.Form):
        use_required_attribute = False
        choice = forms.ChoiceField(choices=LETTERS)

    form = QuietForm()
    apply_primitive_widget_classes(form.fields)
    assert "aria-required" not in _search_box(str(FormFields(form)))


def test_a_later_choices_assignment_reaches_the_swapped_widget():
    field = _swapped(forms.ChoiceField(choices=LETTERS))
    field.choices = [("z", "Z")]
    assert field.widget.choices == [("z", "Z")]


def test_a_swapped_field_keeps_its_widget_attrs():
    field = forms.ChoiceField(
        choices=LETTERS, widget=forms.Select(attrs={"data-kind": "x"})
    )
    assert 'data-kind="x"' in _host_tag(_render(_swapped(field)))


def test_a_swapped_field_refuses_an_attr_with_no_home():
    field = forms.ChoiceField(
        choices=LETTERS, widget=forms.Select(attrs={"title": "x"})
    )
    with pytest.raises(ValueError, match="title"):
        _render(_swapped(field))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field",
    [
        forms.ModelChoiceField(queryset=Device.objects.all()),
        forms.MultipleChoiceField(choices=LETTERS),
        forms.ChoiceField(choices=LETTERS, widget=forms.RadioSelect),
        forms.ChoiceField(choices=LETTERS, widget=forms.SelectMultiple),
    ],
    ids=["model", "multiple", "radio", "select multiple"],
)
def test_other_choice_widgets_stay(field):
    widget = field.widget
    assert _swapped(field).widget is widget
