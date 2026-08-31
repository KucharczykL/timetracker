"""What a temporal draft holds, and what it builds."""

import pytest

from timetracker.temporal import (
    TemporalEndpointDraft,
    TemporalQualifier,
    TemporalValue,
    TemporalValueParseError,
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
