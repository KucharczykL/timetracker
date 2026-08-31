"""What a temporal draft holds, and what it builds."""

from typing import cast

import pytest

from timetracker.temporal import (
    EMPTY_TEMPORAL_DRAFT_DATA,
    TemporalDraft,
    TemporalDraftData,
    TemporalDraftKind,
    TemporalEndpointDraft,
    TemporalQualifier,
    TemporalValue,
    TemporalValueParseError,
    temporal_draft_data,
    temporal_draft_from_data,
    temporal_input_name,
    temporal_qualifier,
)


def test_an_empty_endpoint_builds_nothing() -> None:
    assert TemporalEndpointDraft().build() is None


def test_a_year_alone_builds_a_year() -> None:
    draft = TemporalEndpointDraft(year=1984)

    assert draft.build() == TemporalValue.from_year(1984)


def test_a_year_and_a_month_build_a_month() -> None:
    draft = TemporalEndpointDraft(year=1984, month=6)

    assert draft.build() == TemporalValue.from_month(1984, 6)


def test_every_part_builds_a_day() -> None:
    draft = TemporalEndpointDraft(year=1984, month=6, day=22)

    assert draft.build() == TemporalValue.parse("1984-06-22")


def test_a_decade_alone_builds_a_decade() -> None:
    draft = TemporalEndpointDraft(decade_start_year=1980)

    assert draft.build() == TemporalValue.from_decade(1980)


def test_a_qualifier_rides_on_the_built_value() -> None:
    draft = TemporalEndpointDraft(year=1984, qualifier=TemporalQualifier.BOTH)

    assert draft.build() == TemporalValue.parse("1984%")


def test_changing_one_dimension_is_an_assignment() -> None:
    draft = TemporalEndpointDraft(year=1984)
    draft.month = 6

    assert draft.build() == TemporalValue.from_month(1984, 6)


def test_a_day_without_a_month_is_refused() -> None:
    draft = TemporalEndpointDraft(year=1984, day=22)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "incomplete_day"


def test_a_month_without_a_year_is_refused() -> None:
    draft = TemporalEndpointDraft(month=6)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "incomplete_month"


def test_a_decade_beside_a_year_is_refused() -> None:
    """The else-chain would discard one of them silently."""
    draft = TemporalEndpointDraft(year=1984, decade_start_year=1980)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "decade_with_year"


def test_a_decade_off_the_boundary_is_refused() -> None:
    draft = TemporalEndpointDraft(decade_start_year=1984)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_decade"


def test_a_day_no_calendar_holds_is_refused() -> None:
    draft = TemporalEndpointDraft(year=1985, month=2, day=30)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_date"


def test_a_month_past_december_is_refused() -> None:
    draft = TemporalEndpointDraft(year=1984, month=13)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_date"


@pytest.mark.parametrize(
    "canonical",
    ["1984", "1984-06", "1984-06-22", "198X", "1984~", "1984-06%", "198X?"],
)
def test_an_atomic_value_round_trips_through_an_endpoint(canonical: str) -> None:
    value = TemporalValue.parse(canonical)

    assert TemporalEndpointDraft.from_value(value).build() == value


def test_nothing_reads_as_an_empty_endpoint() -> None:
    assert TemporalEndpointDraft.from_value(None).is_empty


class TemporalDraftShapes:
    """Every shape these controls can write."""

    CANONICALS = (
        "1984",
        "1984-06",
        "1984-06-22",
        "198X",
        "1984~",
        "1984-06%",
        "1984/1986",
        "1984-06/1986",
        "1984~/1986~",
        "1984/1986~",
        "1984?/1986",
        "1984~/1986%",
        "1984/..",
        "../1986",
        "1984/",
        "/1986",
    )


@pytest.mark.parametrize("canonical", TemporalDraftShapes.CANONICALS)
def test_every_shape_round_trips(canonical: str) -> None:
    value = TemporalValue.parse(canonical)

    assert TemporalDraft.from_value(value).build() == value


def test_an_unknown_value_round_trips() -> None:
    value = TemporalValue.unknown()

    assert TemporalDraft.from_value(value).build() == value


def test_nothing_reads_as_an_unknown_draft() -> None:
    draft = TemporalDraft.from_value(None)

    assert draft.kind is TemporalDraftKind.UNKNOWN
    assert draft.build() == TemporalValue.unknown()


def test_an_open_end_reads_as_since() -> None:
    draft = TemporalDraft.from_value(TemporalValue.parse("1984/.."))

    assert draft.kind is TemporalDraftKind.SINCE
    assert draft.start.year == 1984


def test_an_open_start_reads_as_until() -> None:
    draft = TemporalDraft.from_value(TemporalValue.parse("../1986"))

    assert draft.kind is TemporalDraftKind.UNTIL
    assert draft.end.year == 1986


def test_an_unknown_endpoint_reads_as_a_plain_range() -> None:
    draft = TemporalDraft.from_value(TemporalValue.parse("1984/"))

    assert draft.kind is TemporalDraftKind.RANGE
    assert draft.end.is_empty


def test_since_needs_a_date_at_its_known_end() -> None:
    draft = TemporalDraft(kind=TemporalDraftKind.SINCE)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_range"


def test_a_range_with_no_known_endpoint_is_refused() -> None:
    draft = TemporalDraft(kind=TemporalDraftKind.RANGE)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_range"


def test_a_range_that_ends_before_it_starts_is_refused() -> None:
    draft = TemporalDraft(
        kind=TemporalDraftKind.RANGE,
        start=TemporalEndpointDraft(year=1986),
        end=TemporalEndpointDraft(year=1984),
    )

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_range"


def test_a_year_no_grammar_holds_is_refused() -> None:
    """The sentence names the control, not the grammar."""
    draft = TemporalEndpointDraft(year=0)

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "invalid_year"
    assert str(refusal.value) == "A year is a number from 1 to 9999."


def test_a_part_an_unknown_shape_never_reads_is_refused() -> None:
    """The shape a fresh control offers must not swallow a date."""
    draft = TemporalDraft(start=TemporalEndpointDraft(year=1998))

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "unread_parts"


def test_an_end_a_date_never_reads_is_refused() -> None:
    draft = TemporalDraft(
        kind=TemporalDraftKind.DATE,
        start=TemporalEndpointDraft(year=1984),
        end=TemporalEndpointDraft(year=1986),
    )

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "unread_parts"


def test_an_end_beside_since_is_refused() -> None:
    draft = TemporalDraft(
        kind=TemporalDraftKind.SINCE,
        start=TemporalEndpointDraft(year=1984),
        end=TemporalEndpointDraft(year=1986),
    )

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "unread_parts"


def test_a_start_beside_until_is_refused() -> None:
    draft = TemporalDraft(
        kind=TemporalDraftKind.UNTIL,
        start=TemporalEndpointDraft(year=1984),
        end=TemporalEndpointDraft(year=1986),
    )

    with pytest.raises(TemporalValueParseError) as refusal:
        draft.build()

    assert refusal.value.code == "unread_parts"


def test_a_qualifier_alone_leaves_an_unknown_draft_alone() -> None:
    """A box modifies a date. With no date it states nothing."""
    data = posted(kind="unknown", start_approximate="on")

    assert temporal_draft_from_data(data).build() == TemporalValue.unknown()


def test_a_date_draft_with_no_part_builds_unknown() -> None:
    draft = TemporalDraft(kind=TemporalDraftKind.DATE)

    assert draft.build() == TemporalValue.unknown()


def test_an_asymmetric_range_is_written_one_end_at_a_time() -> None:
    """One shared pair would make the start approximate too."""
    data = posted(
        kind="range", start_year="1984", end_year="1986", end_approximate="on"
    )

    assert temporal_draft_from_data(data).build() == TemporalValue.parse("1984/1986~")


def test_each_endpoint_keeps_its_own_qualifier() -> None:
    draft = TemporalDraft.from_value(TemporalValue.parse("1984/1986~"))

    assert draft.start.qualifier is None
    assert draft.end.qualifier is TemporalQualifier.APPROXIMATE


@pytest.mark.parametrize(
    ("approximate", "uncertain", "expected"),
    [
        (False, False, None),
        (True, False, TemporalQualifier.APPROXIMATE),
        (False, True, TemporalQualifier.UNCERTAIN),
        (True, True, TemporalQualifier.BOTH),
    ],
)
def test_two_checkboxes_name_one_qualifier(
    approximate: bool, uncertain: bool, expected: TemporalQualifier | None
) -> None:
    assert temporal_qualifier(approximate=approximate, uncertain=uncertain) is expected


def posted(**overrides: str) -> TemporalDraftData:
    """Empty posted data with the named keys replaced."""
    return cast(TemporalDraftData, dict(EMPTY_TEMPORAL_DRAFT_DATA) | overrides)


def test_an_empty_post_reads_as_an_unknown_draft() -> None:
    assert temporal_draft_from_data(posted()).build() == TemporalValue.unknown()


def test_posted_parts_read_as_numbers() -> None:
    data = posted(kind="date", start_year="1984", start_month="6")

    assert temporal_draft_from_data(data).build() == TemporalValue.from_month(1984, 6)


def test_surrounding_space_is_ignored() -> None:
    data = posted(kind="date", start_year=" 1984 ")

    assert temporal_draft_from_data(data).build() == TemporalValue.from_year(1984)


def test_a_part_that_is_not_a_number_is_refused() -> None:
    data = posted(kind="date", start_year="nineteen")

    with pytest.raises(TemporalValueParseError) as refusal:
        temporal_draft_from_data(data)

    assert refusal.value.code == "invalid_number"


def test_a_kind_the_form_does_not_offer_is_refused() -> None:
    data = posted(kind="season")

    with pytest.raises(TemporalValueParseError) as refusal:
        temporal_draft_from_data(data)

    assert refusal.value.code == "invalid_kind"


def test_a_checked_box_qualifies_both_endpoints() -> None:
    data = posted(
        kind="range",
        start_year="1984",
        start_approximate="on",
        start_uncertain="on",
        end_year="1986",
        end_approximate="on",
        end_uncertain="on",
    )

    assert temporal_draft_from_data(data).build() == TemporalValue.parse("1984%/1986%")


def test_an_unchecked_box_qualifies_nothing() -> None:
    data = posted(kind="date", start_year="1984")

    assert temporal_draft_from_data(data).build() == TemporalValue.from_year(1984)


@pytest.mark.parametrize("canonical", TemporalDraftShapes.CANONICALS)
def test_a_stored_value_survives_the_wire(canonical: str) -> None:
    value = TemporalValue.parse(canonical)
    data = temporal_draft_data(TemporalDraft.from_value(value))

    assert temporal_draft_from_data(data).build() == value


def test_the_wire_names_every_input_after_the_field() -> None:
    assert temporal_input_name("release", "kind") == "release-kind"
    assert temporal_input_name("release", "start_year") == "release-year"
    assert temporal_input_name("release", "end_decade") == "release-end-decade"


def test_the_wire_carries_a_kind_for_an_unknown_draft() -> None:
    data = temporal_draft_data(TemporalDraft())

    assert data["kind"] == "unknown"
