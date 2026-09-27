"""A field joined to a ⊘ that states none."""

import copy
import datetime
import re
import uuid

import pytest
from devices import create_device
from django import forms
from django.http import QueryDict
from test_temporal_form_field import presentation

from common.components import FormFields, SearchSelect, UnsetField, collect_media
from common.components.primitives import Safe
from games.forms import (
    INPUT_CLASS,
    KEEP,
    TEXTAREA_CLASS,
    ChoiceSearchSelectWidget,
    DatePickerWidget,
    DateTimeFieldWidget,
    HoursMinutesWidget,
    PrimitiveWidgetsMixin,
    SearchSelectWidget,
    TemporalFormField,
    TimeZoneRowWidget,
    UnsetFieldsForm,
    UnsetWidget,
    native_control_class,
)
from games.models import Device

UNSET_SCRIPT = "dist/elements/unset-field.js"
LETTERS = [("a", "Alpha"), ("b", "Bravo")]


def _device_options(values: list) -> list[dict]:
    return [
        {"value": str(device.pk), "label": device.name, "data": {}}
        for device in Device.objects.filter(pk__in=values)
    ]


class EditForm(UnsetFieldsForm):
    device = forms.ModelChoiceField(
        queryset=Device.objects.all(),
        required=False,
        widget=UnsetWidget(
            SearchSelectWidget(
                search_url="/devices/", options_resolver=_device_options
            ),
            none_label="No device",
        ),
    )
    note = forms.CharField(
        required=False,
        max_length=20,
        widget=UnsetWidget(forms.Textarea(attrs={"rows": 2}), none_label="No note"),
    )


def _data(**posted: str) -> QueryDict:
    data = QueryDict(mutable=True)
    for key, value in posted.items():
        data[key.replace("_", "-")] = value
    return data


def _cleaned(**posted: str) -> dict:
    form = EditForm(_data(**posted))
    assert form.is_valid(), form.errors
    return form.cleaned_data


# ── cleaning ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_an_empty_field_keeps():
    assert _cleaned(device="", note="") == {"device": KEEP, "note": KEEP}
    assert _cleaned() == {"device": KEEP, "note": KEEP}


@pytest.mark.django_db
def test_unset_states_none(owned_library):
    device = create_device(owned_library)
    cleaned = _cleaned(
        device=str(device.pk), device_unset="1", note="Left", note_unset="1"
    )
    assert cleaned == {"device": None, "note": ""}


@pytest.mark.django_db
def test_a_value_is_cleaned(owned_library):
    device = create_device(owned_library)
    assert _cleaned(device=str(device.pk), note="Hello") == {
        "device": device,
        "note": "Hello",
    }


@pytest.mark.django_db
def test_unset_wins_over_an_invalid_value():
    cleaned = _cleaned(
        device=str(uuid.uuid7()), device_unset="1", note="x" * 99, note_unset="1"
    )
    assert cleaned == {"device": None, "note": ""}
    # Without ⊘, the note's rule runs.
    form = EditForm(_data(note="x" * 99, note_unset=""))
    assert not form.is_valid()
    assert "note" in form.errors


@pytest.mark.django_db
def test_a_field_with_errors_stays_out_of_cleaned_data():
    form = EditForm(_data(device=str(uuid.uuid7())))
    assert not form.is_valid()
    assert "device" not in form.cleaned_data
    assert form.cleaned_data["note"] is KEEP


def test_a_prefixed_form_reads_its_prefixed_key():
    class NoteForm(UnsetFieldsForm):
        note = forms.CharField(
            required=False, widget=UnsetWidget(forms.Textarea(), none_label="No note")
        )

    form = NoteForm(QueryDict("edit-note=Kept&edit-note-unset=1"), prefix="edit")
    assert form.is_valid(), form.errors
    assert form.cleaned_data["note"] == ""


def test_value_omitted_only_without_both_keys():
    widget = UnsetWidget(forms.Textarea(), none_label="No note")
    assert widget.value_omitted_from_data(QueryDict(""), {}, "note")
    assert not widget.value_omitted_from_data(QueryDict("note-unset=1"), {}, "note")
    assert not widget.value_omitted_from_data(QueryDict("note=x"), {}, "note")


# ── rendering ────────────────────────────────────────────────────────────────


def _toggle(html: str) -> str:
    marker = html.index("data-unset-field-toggle")
    return html[html.rindex("<", 0, marker) : html.index(">", marker)]


def _checkbox(html: str) -> str:
    marker = html.index("data-unset-field-state")
    return html[html.rindex("<", 0, marker) : html.index(">", marker)]


def test_the_component_names_its_parts():
    html = str(
        UnsetField(
            name="note",
            none_label="No note",
            field=lambda shape: Safe(f'<textarea data-shape="{shape}"></textarea>'),
            describedby="id_note-label",
        )
    )
    assert '<unset-field name="note" none-label="No note"' in html
    assert 'data-shape="start"' in html
    toggle = _toggle(html)
    assert 'aria-pressed="false"' in toggle
    assert 'aria-label="No note"' in toggle
    assert 'aria-describedby="id_note-label"' in toggle
    assert "rounded-e-base" in toggle
    assert "[unset-field:not(:defined)_&amp;]:hidden" in toggle
    checkbox = _checkbox(html)
    assert 'name="note-unset"' in checkbox
    assert 'autocomplete="off"' in checkbox
    assert "checked" not in checkbox
    assert "[unset-field:defined_&amp;]:hidden" in html


def test_a_pressed_component_checks_its_box():
    html = str(
        UnsetField(
            name="note", none_label="No note", field=lambda shape: Safe(""), unset=True
        )
    )
    assert 'aria-pressed="true"' in _toggle(html)
    assert "checked" in _checkbox(html)


@pytest.mark.django_db
def test_a_bound_form_shown_again_stays_pressed():
    html = str(FormFields(EditForm(_data(note="Left", note_unset="1"))))
    note = html[html.index('<unset-field name="note"') :]
    assert "checked" in _checkbox(note)
    assert 'aria-pressed="true"' in _toggle(note)


@pytest.mark.django_db
def test_form_fields_shape_both_controls_and_carry_the_script():
    rendered = FormFields(EditForm())
    html = str(rendered)
    textarea = re.search(r"<textarea[^>]*>", html)
    assert textarea is not None
    assert native_control_class(forms.Textarea(), "start") in textarea.group(0)
    assert 'maxlength="20"' in textarea.group(0)
    assert 'rows="2"' in textarea.group(0)
    box = html[html.index("data-search-select-box") :]
    assert "rounded-s-base" in box[: box.index(">")]
    assert UNSET_SCRIPT in collect_media(rendered).js


def test_form_fields_refuse_a_plain_form():
    class PlainForm(forms.Form):
        note = forms.CharField(
            required=False, widget=UnsetWidget(forms.Textarea(), none_label="No note")
        )

    with pytest.raises(TypeError, match="UnsetFieldsForm"):
        FormFields(PlainForm())
    with pytest.raises(TypeError, match="UnsetFieldsForm"):
        PlainForm(QueryDict("note=")).is_valid()


def test_the_label_targets_the_inner_control():
    class NoteForm(UnsetFieldsForm):
        note = forms.CharField(
            required=False, widget=UnsetWidget(forms.Textarea(), none_label="No note")
        )

    assert NoteForm()["note"].id_for_label == "id_note"


# ── shapes ───────────────────────────────────────────────────────────────────


def test_a_start_shaped_box_squares_its_end():
    html = str(SearchSelect(name="device", shape="start"))
    box = html[html.index("data-search-select-box") :]
    tag = box[: box.index(">")]
    assert "rounded-s-base" in tag
    assert "rounded-base" not in tag


def test_the_full_shape_keeps_the_public_classes():
    assert native_control_class(forms.TextInput()) == INPUT_CLASS
    assert native_control_class(forms.Textarea()) == TEXTAREA_CLASS
    assert native_control_class(forms.Textarea(), "start").endswith("rounded-s-base")


# ── refusals ─────────────────────────────────────────────────────────────────


def _host(field: forms.Field) -> UnsetFieldsForm:
    class OneForm(UnsetFieldsForm):
        pass

    form = OneForm()
    form.fields["one"] = field
    return form


def _render(field: forms.Field) -> str:
    return str(FormFields(_host(field)))


def test_a_required_field_is_refused():
    field = forms.CharField(widget=UnsetWidget(forms.Textarea(), none_label="No note"))
    with pytest.raises(ValueError, match="cannot keep"):
        _render(field)


def test_a_picker_with_a_none_row_is_refused():
    picker = SearchSelectWidget(
        search_url="/x/", options_resolver=_device_options, none_label="No device"
    )
    field = forms.CharField(
        required=False, widget=UnsetWidget(picker, none_label="No device")
    )
    with pytest.raises(ValueError, match="offers none"):
        _render(field)


def test_a_fixed_choice_picker_with_an_empty_choice_is_refused():
    field = forms.ChoiceField(
        required=False,
        choices=[("", "No letter"), *LETTERS],
        widget=UnsetWidget(ChoiceSearchSelectWidget(), none_label="No letter"),
    )
    with pytest.raises(ValueError, match="offers none"):
        _render(field)


@pytest.mark.parametrize(
    "inner",
    [
        forms.CheckboxInput(),
        forms.HiddenInput(),
        forms.SelectMultiple(choices=LETTERS),
        SearchSelectWidget(
            search_url="/x/", options_resolver=_device_options, multi_select=True
        ),
        SearchSelectWidget(
            search_url="/x/", options_resolver=_device_options, commit_sole_option=True
        ),
        SearchSelectWidget(
            search_url="/x/",
            options_resolver=_device_options,
            params={"game": {"field": "game"}},
        ),
    ],
)
def test_widgets_a_toggle_cannot_join_are_refused(inner):
    with pytest.raises(TypeError):
        UnsetWidget(inner, none_label="None")


def test_a_write_meant_for_the_inner_widget_is_refused():
    widget = UnsetWidget(
        SearchSelectWidget(search_url="/x/", options_resolver=_device_options),
        none_label="No device",
    )
    with pytest.raises(AttributeError, match=".widget"):
        widget.placeholder = "Keep: mixed"  # type: ignore[attr-defined]
    with pytest.raises(AttributeError, match=".widget"):
        widget.input_type = "email"  # type: ignore[attr-defined]
    widget.widget.placeholder = "Keep: mixed"
    widget.attrs["placeholder"] = "fine"


# ── Django plumbing ──────────────────────────────────────────────────────────


def test_choices_reach_the_inner_widget():
    field = forms.ChoiceField(
        required=False,
        choices=LETTERS,
        widget=UnsetWidget(ChoiceSearchSelectWidget(), none_label="No letter"),
    )
    html = _render(field)
    assert "Bravo" in html


def test_form_instances_do_not_share_the_inner_widget():
    class NoteForm(UnsetFieldsForm):
        note = forms.CharField(
            required=False, widget=UnsetWidget(forms.Textarea(), none_label="No note")
        )

    first, second = NoteForm(), NoteForm()
    first_widget = first.fields["note"].widget
    second_widget = second.fields["note"].widget
    assert isinstance(first_widget, UnsetWidget)
    assert isinstance(second_widget, UnsetWidget)
    assert first_widget.widget is not second_widget.widget
    copied = copy.deepcopy(first_widget)
    assert copied.widget is not first_widget.widget


# ── reviewer-found paths ─────────────────────────────────────────────────────


class DynamicForm(UnsetFieldsForm):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["note"] = forms.CharField(
            required=False, widget=UnsetWidget(forms.Textarea(), none_label="No note")
        )


def test_a_field_added_after_init_states_none():
    form = DynamicForm(QueryDict("note=Left&note-unset=1"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["note"] == ""
    assert "checked" in _checkbox(str(FormFields(form)))


def test_only_the_posted_one_presses():
    form = DynamicForm(QueryDict("note=Kept&note-unset=0"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["note"] == "Kept"


def test_zero_is_a_value_not_keep():
    class CountForm(UnsetFieldsForm):
        count = forms.IntegerField(
            required=False,
            widget=UnsetWidget(forms.NumberInput(), none_label="No count"),
        )

    form = CountForm(QueryDict("count=0"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["count"] == 0


def test_a_native_select_gets_its_choices_and_shape():
    field = forms.ChoiceField(
        required=False,
        choices=LETTERS,
        widget=UnsetWidget(forms.Select(), none_label="No letter"),
    )
    html = _render(field)
    select = re.search(r"<select[^>]*>", html)
    assert select is not None
    assert "rounded-s-base" in select.group(0)
    assert "Bravo" in html


def test_the_mixin_leaves_one_corner_class():
    class MixedForm(PrimitiveWidgetsMixin, UnsetFieldsForm):
        note = forms.CharField(
            required=False, widget=UnsetWidget(forms.Textarea(), none_label="No note")
        )

    textarea = re.search(r"<textarea[^>]*>", str(FormFields(MixedForm())))
    assert textarea is not None
    assert "rounded-s-base" in textarea.group(0)
    assert "rounded-base" not in textarea.group(0)


def test_an_embedded_unset_field_carries_the_script():
    class HostForm(UnsetFieldsForm):
        host = forms.CharField(required=False)
        note = forms.CharField(
            required=False, widget=UnsetWidget(forms.Textarea(), none_label="No note")
        )

    rendered = FormFields(HostForm(), embedded={"note": "host"})
    assert UNSET_SCRIPT in collect_media(rendered).js


def test_a_picker_reading_a_toggled_field_is_refused():
    class DrivenForm(UnsetFieldsForm):
        note = forms.CharField(
            required=False, widget=UnsetWidget(forms.Textarea(), none_label="No note")
        )
        pick = forms.CharField(
            required=False,
            widget=SearchSelectWidget(
                search_url="/x/",
                options_resolver=_device_options,
                params={"note": {"field": "note"}},
            ),
        )

    with pytest.raises(ValueError, match="params read"):
        DrivenForm(QueryDict("")).is_valid()


# ── composites ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "inner", [forms.DateInput(), forms.PasswordInput(), forms.URLInput()]
)
def test_text_like_inputs_are_joinable(inner):
    UnsetWidget(inner, none_label="None")


def test_every_text_like_input_joins():
    field = forms.EmailField(
        required=False, widget=UnsetWidget(forms.EmailInput(), none_label="No email")
    )
    html = _render(field)
    assert "rounded-s-base" in re.search(r'<input type="email"[^>]*>', html).group(0)


class RangeInput(forms.widgets.Input):
    input_type = "range"


@pytest.mark.parametrize(
    "inner",
    [
        forms.RadioSelect(choices=LETTERS),
        forms.ClearableFileInput(),
        forms.CheckboxInput(),
        forms.HiddenInput(),
        forms.MultipleHiddenInput(),
        RangeInput(),
    ],
)
def test_widgets_with_no_empty_are_refused(inner):
    with pytest.raises(TypeError):
        UnsetWidget(inner, none_label="None")


def test_the_time_zone_row_is_refused():
    with pytest.raises(TypeError):
        UnsetWidget(
            TimeZoneRowWidget(label="Zone", display_zone="UTC", capture_default=False),
            none_label="None",
        )


def _date_time_field() -> forms.DateTimeField:
    return forms.DateTimeField(
        required=False,
        widget=UnsetWidget(
            DateTimeFieldWidget(presentation=presentation(), label="At"),
            none_label="No time",
        ),
    )


def _temporal_field() -> TemporalFormField:
    field = TemporalFormField(presentation=presentation(), label="When", required=False)
    field.widget = UnsetWidget(field.widget, none_label="No date")
    return field


def _date_field() -> forms.DateField:
    return forms.DateField(
        required=False,
        widget=UnsetWidget(
            DatePickerWidget(presentation=presentation(), label="Day"),
            none_label="No day",
        ),
    )


COMPOSITES = [
    (_date_field, "date-picker"),
    (_date_time_field, "date-time-field"),
    (_temporal_field, "temporal-field"),
]


@pytest.mark.parametrize(("build", "tag"), COMPOSITES)
def test_a_composite_stands_beside_its_toggle(build, tag):
    form = _host(build())
    html = str(FormFields(form))
    row = html[html.index("<unset-field") :]
    assert "flex items-start gap-2" in row
    assert f"<{tag}" in row
    assert "rounded-e-base" not in _toggle(row)
    assert f"dist/elements/{tag}.js" in collect_media(FormFields(form)).js


@pytest.mark.parametrize(
    ("posted", "cleaned"),
    [
        ("one=", KEEP),
        ("one=2024-05-06&one-unset=1", None),
        ("one=2024-05-06", datetime.date(2024, 5, 6)),
    ],
)
def test_a_composite_cleans_keep_none_and_value(posted, cleaned):
    class DayForm(UnsetFieldsForm):
        one = _date_field()

    form = DayForm(QueryDict(posted))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["one"] == cleaned


def test_a_field_whose_empty_is_a_value_is_refused():
    field = forms.CharField(
        required=False,
        empty_value="unnamed",
        widget=UnsetWidget(forms.TextInput(), none_label="No name"),
    )
    with pytest.raises(ValueError, match="cleans to"):
        _render(field)


@pytest.mark.parametrize("inner", [HoursMinutesWidget(), forms.NullBooleanSelect()])
def test_multi_part_and_three_state_widgets_are_refused(inner):
    with pytest.raises(TypeError):
        UnsetWidget(inner, none_label="None")


def test_the_toggle_carries_its_field_scripts():
    js = collect_media(FormFields(_host(_date_field()))).js
    assert UNSET_SCRIPT in js
    assert "dist/elements/date-picker.js" in js


@pytest.mark.parametrize(
    ("posted", "cleaned"),
    [
        ("one=", KEEP),
        ("one=2026-07-27T14:30:00%2B00:00&one-unset=1", None),
    ],
)
def test_a_date_time_composite_cleans_keep_and_none(posted, cleaned):
    class AtForm(UnsetFieldsForm):
        one = _date_time_field()

    form = AtForm(QueryDict(posted))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["one"] == cleaned


def test_a_date_time_composite_cleans_a_value():
    class AtForm(UnsetFieldsForm):
        one = _date_time_field()

    form = AtForm(QueryDict("one=2026-07-27T14:30:00%2B00:00"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["one"] not in (None, KEEP)


@pytest.mark.parametrize(
    ("posted", "outcome"),
    [
        ("one-kind=unknown", "keep"),
        ("one-kind=date&one-year=1997&one-unset=1", "none"),
        ("one-kind=date&one-year=1997", "value"),
    ],
)
def test_a_temporal_composite_cleans_keep_none_and_value(posted, outcome):
    form = UnsetFieldsForm(QueryDict(posted))
    form.fields["one"] = _temporal_field()
    assert form.is_valid(), form.errors
    cleaned = form.cleaned_data["one"]
    if outcome == "keep":
        assert cleaned is KEEP
    elif outcome == "none":
        assert cleaned is None
    else:
        assert cleaned not in (None, KEEP)


class RefusingField(forms.CharField):
    def to_python(self, value):
        if value in self.empty_values:
            raise forms.ValidationError("Say something.")
        return super().to_python(value)


class BrokenField(forms.CharField):
    def clean(self, value):
        return value.strip()


def test_a_field_refusing_empty_is_refused():
    field = RefusingField(
        required=False, widget=UnsetWidget(forms.TextInput(), none_label="None")
    )
    with pytest.raises(ValueError, match="refused"):
        _render(field)


def test_a_field_breaking_on_empty_names_itself():
    field = BrokenField(
        required=False, widget=UnsetWidget(forms.TextInput(), none_label="None")
    )
    with pytest.raises(TypeError, match="one: clean"):
        _render(field)
