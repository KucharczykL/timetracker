"""What the temporal control renders, and what it binds."""

from typing import cast

import pytest

from common.components import collect_media, render
from common.components.temporal_field import TemporalField
from timetracker.temporal import (
    EMPTY_TEMPORAL_DRAFT_DATA,
    TemporalDraft,
    TemporalDraftData,
    TemporalValue,
    temporal_draft_data,
)


def posted(**overrides: str) -> TemporalDraftData:
    return cast(TemporalDraftData, dict(EMPTY_TEMPORAL_DRAFT_DATA) | overrides)


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
        "release-end-decade",
        "release-approximate",
        "release-uncertain",
    ],
)
def test_every_posted_input_is_rendered(input_name: str) -> None:
    assert f'name="{input_name}"' in markup()


def test_the_control_carries_no_script() -> None:
    """The whole point: this works with scripting off."""
    node = TemporalField(
        name="release",
        data=posted(kind="unknown"),
        label="Release date",
        input_id="id_release",
    )
    media = collect_media(node)

    assert media.js == ()
    assert media.js_external == ()


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


def test_an_unchecked_qualifier_leaves_its_box_alone() -> None:
    assert "checked" not in markup()


def test_the_first_control_takes_the_label_target() -> None:
    assert 'id="id_release"' in markup()


def test_the_group_names_itself_after_the_row_label() -> None:
    assert 'aria-labelledby="id_release-label"' in markup()


def test_an_invalid_field_says_so() -> None:
    assert 'aria-invalid="true"' in markup(invalid=True)
