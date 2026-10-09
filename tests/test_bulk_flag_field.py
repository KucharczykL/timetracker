"""A bulk flag's field, widget and held state."""

from types import SimpleNamespace

import pytest
from django import forms

from games.bulk_edit import (
    FLAG_CHECKED,
    FLAG_UNCHECKED,
    flag_field,
    held_flag,
)
from games.forms import (
    INPUT_CLASS,
    TRI_STATE_HINTS,
    PrimitiveWidgetsMixin,
    TriStateCheckboxWidget,
)


class FlagForm(PrimitiveWidgetsMixin, forms.Form):
    mastered = flag_field("Mastered")


def clean(raw: str | None) -> object:
    form = FlagForm(data={} if raw is None else {"mastered": raw})
    assert form.is_valid(), form.errors
    return form.cleaned_data["mastered"]


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [(None, None), ("", None), (FLAG_CHECKED, True), (FLAG_UNCHECKED, False)],
)
def test_the_posted_word_cleans_to_its_state(raw, cleaned):
    assert clean(raw) is cleaned


def test_an_unknown_word_is_an_invalid_choice():
    form = FlagForm(data={"mastered": "maybe"})

    assert not form.is_valid()
    assert "mastered" in form.errors


def test_the_widget_words_are_the_choice_keys():
    field = FlagForm().fields["mastered"]
    choice_keys = [key for key, _label in field.choices if key != ""]

    assert choice_keys == [FLAG_CHECKED, FLAG_UNCHECKED]
    assert isinstance(field.widget, TriStateCheckboxWidget)
    assert field.widget.words.checked == FLAG_CHECKED
    assert field.widget.words.unchecked == FLAG_UNCHECKED


def test_the_widget_takes_no_text_input_class_after_the_mixin():
    widget = FlagForm().fields["mastered"].widget

    assert INPUT_CLASS not in widget.attrs.get("class", "")
    assert "class" not in widget.attrs


def test_the_widget_is_a_checkbox_to_the_form_layout():
    assert TriStateCheckboxWidget.input_type == "checkbox"
    assert not isinstance(TriStateCheckboxWidget(words=None), forms.CheckboxInput)


def test_a_held_checked_flag_renders_checked_with_nothing_posted():
    form = FlagForm(initial={"mastered": True})
    form.fields["mastered"].widget.held = "checked"

    markup = str(form["mastered"])

    assert 'data-tri-state-value=""' in markup
    assert f">{TRI_STATE_HINTS.kept}</span>" in markup
    assert " checked" in markup


def test_a_stated_word_renders_as_the_posted_value():
    widget = TriStateCheckboxWidget(words=flag_field("x").widget.words)
    widget.held = "mixed"

    markup = widget.render("mastered", FLAG_CHECKED)

    assert 'value="True"' in markup
    assert TRI_STATE_HINTS.changed in markup


def test_the_widget_reads_the_raw_posted_string():
    widget = TriStateCheckboxWidget(words=flag_field("x").widget.words)

    assert widget.value_from_datadict({"mastered": "False"}, {}, "mastered") == "False"
    assert widget.value_from_datadict({}, {}, "mastered") is None


@pytest.mark.parametrize(
    ("values", "held"),
    [
        ([True, True], "checked"),
        ([False, False], "unchecked"),
        ([True, False], "mixed"),
        ([True, False, True], "mixed"),
    ],
)
def test_held_flag_states_what_the_rows_agree_on(values, held):
    rows = [SimpleNamespace(flag=value) for value in values]

    assert held_flag(rows, lambda row: row.flag) == held


def test_held_flag_refuses_no_rows():
    with pytest.raises(ValueError):
        held_flag([], lambda row: row.flag)
