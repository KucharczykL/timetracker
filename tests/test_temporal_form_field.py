"""What the temporal control renders, and what it binds."""

from typing import cast
from zoneinfo import ZoneInfo

import pytest
from django import forms

from common.components import collect_media, render
from common.components.temporal_field import TemporalField
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.forms import (
    INPUT_CLASS,
    TemporalFormField,
    TemporalWidget,
    apply_primitive_widget_classes,
)
from timetracker.temporal import (
    EMPTY_TEMPORAL_DRAFT_DATA,
    TemporalDraft,
    TemporalDraftData,
    TemporalQualifier,
    TemporalValue,
    temporal_draft_data,
)


def posted(**overrides: str) -> TemporalDraftData:
    return cast(TemporalDraftData, dict(EMPTY_TEMPORAL_DRAFT_DATA) | overrides)


def presentation() -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
    )


def markup(
    data: TemporalDraftData | None = None,
    *,
    required: bool = False,
    invalid: bool = False,
) -> str:
    node = TemporalField(
        name="release",
        data=data if data is not None else posted(kind="unknown"),
        label="Release date",
        presentation=presentation(),
        input_id="id_release",
        required=required,
        invalid=invalid,
    )
    return str(render(node))


@pytest.mark.parametrize(
    "input_name",
    [
        "release-kind",
        "release-year",
        "release-month",
        "release-day",
        "release-decade",
        "release-end-year",
        "release-end-month",
        "release-end-day",
        "release-approximate",
        "release-uncertain",
        "release-end-decade",
        "release-end-approximate",
        "release-end-uncertain",
    ],
)
def test_every_posted_input_is_rendered(input_name: str) -> None:
    assert f'name="{input_name}"' in markup()


def test_the_script_only_enhances() -> None:
    """Every posted control is here, named, and shown."""
    node = TemporalField(
        name="release",
        data=posted(kind="unknown"),
        label="Release date",
        presentation=presentation(),
        input_id="id_release",
    )
    media = collect_media(node)

    assert media.js == ("dist/elements/temporal-field.js",)
    assert 'name="release-year"' in str(render(node))


def test_the_segments_wait_for_the_script() -> None:
    """Shown before the upgrade, they would be a second date field."""
    html = markup()

    assert '<div data-temporal-segments="start" hidden' in html
    assert '<div data-temporal-segments="end" hidden' in html


def test_no_script_still_reaches_every_posted_control() -> None:
    """Hidden, an end date and a qualifier would be unreachable."""
    html = markup()

    assert '<div data-temporal-end-group="">' in html
    # The three hidden extras hold the nameless toggles alone.
    assert html.count('data-temporal-extra=""') == 7
    assert html.count('data-temporal-extra="" hidden') == 3


def test_a_segment_carries_the_stored_part_zero_padded() -> None:
    data = temporal_draft_data(
        TemporalDraft.from_value(TemporalValue.parse("1984-06-22"))
    )
    segments = markup(data).split('data-temporal-segments="start"')[1]

    assert 'value="1984" data-date-part="year" data-date-side="start"' in segments
    assert 'value="06" data-date-part="month" data-date-side="start"' in segments
    assert 'value="22" data-date-part="day" data-date-side="start"' in segments


def test_a_stored_decade_renders_its_own_shape() -> None:
    """An upgrade unhides this; it never rebuilds it."""
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("198X")))
    start = markup(data).split('data-temporal-segments="start"')[1]

    assert 'value="1980" data-date-part="year"' in start
    assert '<span data-temporal-part="month" hidden' in start
    suffix = start.split('data-temporal-decade-suffix=""')[1].split("</span>")[0]
    assert "hidden" not in suffix
    assert suffix.endswith(">s")


def test_each_endpoint_has_an_unnamed_scratch_input() -> None:
    """Named, it would post a fourteenth thing the server cannot read."""
    html = markup()

    assert '<input data-temporal-scratch="start" type="hidden">' in html
    assert '<input data-temporal-scratch="end" type="hidden">' in html


def test_every_script_only_toggle_is_rendered_and_nameless() -> None:
    """An empty name is never submitted, so these stay off the wire."""
    html = markup()

    for toggle in ("whole_decade_start", "whole_decade_end", "open_start"):
        assert f'data-temporal-toggle="{toggle}"' in html
    assert html.count('name=""') == 3
    # The end says it once, so the end itself offers no toggle.
    assert 'data-temporal-toggle="open_end"' not in html


def test_the_end_shape_radios_are_grouped_and_disabled() -> None:
    """A radio needs a name to group. Disabled keeps it off the wire."""
    html = markup()

    for shape in ("end_none", "end_date", "end_open"):
        assert f'disabled="disabled" data-temporal-toggle="{shape}"' in html
    assert html.count('name="release-end-shape"') == 3


def test_the_posted_controls_carry_their_draft_key() -> None:
    """The element addresses them by the key the server reads."""
    html = markup()

    assert 'data-temporal-input="kind"' in html
    assert 'data-temporal-input="start_year"' in html
    assert 'data-temporal-input="end_uncertain"' in html


def test_a_plain_stored_date_needs_no_disclosure() -> None:
    data = temporal_draft_data(
        TemporalDraft.from_value(TemporalValue.parse("1984-06-22"))
    )

    assert 'expanded="false"' in markup(data)


def test_a_stored_range_opens_expanded() -> None:
    data = temporal_draft_data(
        TemporalDraft.from_value(TemporalValue.parse("1984/1986"))
    )

    assert 'expanded="true"' in markup(data)


def test_a_stored_qualifier_opens_expanded() -> None:
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984~")))

    assert 'expanded="true"' in markup(data)


def test_text_a_segment_cannot_hold_keeps_the_native_controls() -> None:
    """Segments take digits. Hiding them would swallow what was typed."""
    html = markup(posted(kind="date", start_year="nineteen"))

    assert "<temporal-field" not in html
    assert 'name="release-year" value="nineteen"' in html


def test_the_control_says_when_its_precision_changes() -> None:
    assert 'data-temporal-announcement="" role="status" aria-live="polite"' in markup()


def test_the_kind_select_offers_every_shape() -> None:
    html = markup()

    for kind in ("date", "range", "since", "until", "unknown"):
        assert f'value="{kind}"' in html


def test_the_stored_kind_is_the_selected_one() -> None:
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("198X")))

    assert '<option value="date" selected' in markup(data)


def test_a_stored_part_is_the_input_value() -> None:
    data = temporal_draft_data(
        TemporalDraft.from_value(TemporalValue.parse("1984-06-22"))
    )
    html = markup(data)

    assert 'name="release-year" value="1984"' in html
    assert 'name="release-month" value="6"' in html
    assert 'name="release-day" value="22"' in html


def test_a_qualifier_checks_its_box() -> None:
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984%")))
    html = markup(data)

    assert 'name="release-approximate" value="on"' in html
    assert 'name="release-uncertain" value="on"' in html
    assert html.count("checked") == 2


def test_only_the_qualified_end_checks_its_box() -> None:
    """A shared pair would tick the start too, and store it."""
    data = temporal_draft_data(
        TemporalDraft.from_value(TemporalValue.parse("1984/1986~"))
    )
    html = markup(data)
    end_box = html.split('name="release-end-approximate"')[1].split(">")[0]

    assert "checked" in end_box
    assert html.count("checked") == 1


def test_an_unchecked_qualifier_leaves_its_box_alone() -> None:
    assert "checked" not in markup()


def test_each_endpoint_names_its_own_parts() -> None:
    """Otherwise a screen reader reads two spinbuttons named Year."""
    html = markup()

    assert (
        '<fieldset class="flex flex-col gap-1" data-temporal-endpoint="start">' in html
    )
    for legend in ("Start", "End"):
        assert f'data-temporal-extra="">{legend}</legend>' in html


def test_a_shape_the_form_never_offers_echoes_back() -> None:
    """Showing Date instead would invent a shape nobody picked."""
    html = markup(posted(kind="season"))

    assert '<option value="season" selected' in html
    assert html.count('selected="selected"') == 1


def test_the_first_control_takes_the_label_target() -> None:
    assert 'id="id_release"' in markup()


def test_the_group_names_itself_after_the_row_label() -> None:
    assert 'aria-labelledby="id_release-label"' in markup()


def test_an_invalid_field_says_so() -> None:
    assert 'aria-invalid="true"' in markup(invalid=True)


class ReleaseForm(forms.Form):
    """A plain form, so the field is tested and not a page."""

    released = TemporalFormField(
        presentation=presentation(), label="Release date", required=False
    )


def post(**overrides: str) -> dict[str, str]:
    """A POST body naming the form's one field."""
    return {f"released-{suffix}": text for suffix, text in overrides.items()}


def test_an_empty_post_cleans_to_nothing() -> None:
    form = ReleaseForm(data={"released-kind": "unknown"})

    assert form.is_valid()
    assert form.cleaned_data["released"] is None


def test_a_posted_month_cleans_to_a_month_value() -> None:
    form = ReleaseForm(data=post(kind="date", year="1984", month="6"))

    assert form.is_valid()
    assert form.cleaned_data["released"] == TemporalValue.from_month(1984, 6)


def test_a_posted_range_cleans_to_a_range_value() -> None:
    form = ReleaseForm(data=post(kind="range", year="1984", **{"end-year": "1986"}))

    assert form.is_valid()
    assert form.cleaned_data["released"] == TemporalValue.parse("1984/1986")


def test_a_posted_since_cleans_to_an_open_end() -> None:
    form = ReleaseForm(data=post(kind="since", year="1984"))

    assert form.is_valid()
    assert form.cleaned_data["released"] == TemporalValue.parse("1984/..")


def test_a_posted_qualifier_cleans_onto_the_value() -> None:
    form = ReleaseForm(data=post(kind="date", year="1984", approximate="on"))

    assert form.is_valid()
    assert form.cleaned_data["released"] == TemporalValue.from_year(
        1984, qualifier=TemporalQualifier.APPROXIMATE
    )


def test_a_disagreement_is_a_field_error_with_a_sentence() -> None:
    form = ReleaseForm(data=post(kind="date", month="6"))

    assert not form.is_valid()
    assert form.errors["released"] == ["A month needs a year beside it."]


def test_a_refused_submission_re_renders_what_was_typed() -> None:
    """Not a normalized guess. The characters a person typed."""
    form = ReleaseForm(data=post(kind="date", year="nineteen", month="6"))

    assert not form.is_valid()
    html = str(form["released"])

    assert 'name="released-year" value="nineteen"' in html
    assert 'name="released-month" value="6"' in html


def test_a_stored_value_renders_as_its_parts() -> None:
    form = ReleaseForm(initial={"released": TemporalValue.parse("198X")})
    html = str(form["released"])

    assert 'name="released-decade" value="1980"' in html
    assert '<option value="date" selected' in html


def test_an_omitted_control_is_reported_as_omitted() -> None:
    widget = TemporalWidget(presentation=presentation(), label="Release date")

    assert widget.value_omitted_from_data({}, {}, "released")
    assert not widget.value_omitted_from_data({"released-kind": "date"}, {}, "released")


def test_an_untouched_field_has_not_changed() -> None:
    field = TemporalFormField(
        presentation=presentation(), label="Release date", required=False
    )
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984")))

    assert not field.has_changed(TemporalValue.parse("1984"), data)


def test_an_untouched_asymmetric_range_has_not_changed() -> None:
    """Re-saving a record must not widen a date nobody touched."""
    field = TemporalFormField(
        presentation=presentation(), label="Release date", required=False
    )
    value = TemporalValue.parse("1984/1986~")
    data = temporal_draft_data(TemporalDraft.from_value(value))

    assert not field.has_changed(value, data)
    assert field.to_python(data) == value


def test_one_end_alone_can_be_made_approximate() -> None:
    form = ReleaseForm(
        data=post(
            kind="range",
            year="1984",
            **{"end-year": "1986", "end-approximate": "on"},
        )
    )

    assert form.is_valid()
    assert form.cleaned_data["released"] == TemporalValue.parse("1984/1986~")


def test_a_disabled_field_has_not_changed() -> None:
    """Nobody can touch a disabled control, so nothing it posts counts."""
    field = TemporalFormField(
        presentation=presentation(), label="Release date", required=False, disabled=True
    )
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984-06")))

    assert not field.has_changed(TemporalValue.parse("1984"), data)


def test_a_part_the_shape_never_reads_is_a_field_error() -> None:
    form = ReleaseForm(data=post(kind="date", year="1984", **{"end-year": "1986"}))

    assert not form.is_valid()
    assert form.errors["released"] == [
        "A date reads the start only. Clear the end, or pick Range."
    ]


def test_a_typed_date_is_never_swallowed_by_the_default_shape() -> None:
    """The shape a fresh control renders must refuse, not discard."""
    form = ReleaseForm(data=post(kind="unknown", year="1998"))

    assert not form.is_valid()
    assert form.errors["released"] == [
        "Pick a shape for the date you typed, or clear it."
    ]


def test_a_changed_part_has_changed() -> None:
    field = TemporalFormField(
        presentation=presentation(), label="Release date", required=False
    )
    data = temporal_draft_data(TemporalDraft.from_value(TemporalValue.parse("1984-06")))

    assert field.has_changed(TemporalValue.parse("1984"), data)


def test_the_composite_widget_keeps_its_own_classes() -> None:
    """A native-control class on a composite is styling at a distance."""
    form = ReleaseForm()
    apply_primitive_widget_classes(form.fields)

    assert INPUT_CLASS not in form.fields["released"].widget.attrs.get("class", "")


def test_a_required_field_refuses_an_unknown_value() -> None:
    class RequiredReleaseForm(forms.Form):
        released = TemporalFormField(
            presentation=presentation(), label="Release date", required=True
        )

    form = RequiredReleaseForm(data={"released-kind": "unknown"})

    assert not form.is_valid()
