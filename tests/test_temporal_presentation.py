"""The words a stored temporal value reads as."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from common.date_time_presentation import (
    DateTimePresentation,
    date_time_format_profile,
)
from common.temporal_presentation import present_temporal_value
from timetracker.temporal import TemporalQualifier, TemporalValue


def presentation(profile_id: str = "iso_8601") -> DateTimePresentation:
    return DateTimePresentation(
        profile=date_time_format_profile(profile_id),
        locale="en-us",
        timezone=ZoneInfo("UTC"),
    )


@pytest.mark.parametrize(
    ("profile_id", "expected"),
    [
        ("iso_8601", "1984-06-22"),
        ("dmy_24h", "22/06/1984"),
        ("mdy_12h", "06/22/1984"),
    ],
)
def test_a_day_reads_in_the_account_order(profile_id: str, expected: str) -> None:
    value = TemporalValue.from_day(date(1984, 6, 22))

    assert present_temporal_value(value, presentation(profile_id)) == expected


def test_a_month_reads_as_a_month_and_a_year() -> None:
    value = TemporalValue.from_month(1984, 6)

    assert present_temporal_value(value, presentation()) == "June 1984"


def test_a_month_never_prints_a_day() -> None:
    value = TemporalValue.from_month(1984, 6)

    words = present_temporal_value(value, presentation("iso_8601"))

    assert "01" not in words


def test_a_year_reads_as_four_digits() -> None:
    value = TemporalValue.from_year(1984)

    assert present_temporal_value(value, presentation()) == "1984"


def test_a_decade_reads_with_a_trailing_letter() -> None:
    value = TemporalValue.from_decade(1980)

    assert present_temporal_value(value, presentation()) == "1980s"


@pytest.mark.parametrize(
    "value",
    [None, TemporalValue.unknown()],
)
def test_nothing_stored_reads_as_unknown(value: TemporalValue | None) -> None:
    assert present_temporal_value(value, presentation()) == "Unknown"


@pytest.mark.parametrize(
    ("qualifier", "expected"),
    [
        (TemporalQualifier.APPROXIMATE, "around 1984"),
        (TemporalQualifier.UNCERTAIN, "1984 (uncertain)"),
        (TemporalQualifier.BOTH, "around 1984 (uncertain)"),
    ],
)
def test_a_qualifier_reads_in_words(
    qualifier: TemporalQualifier, expected: str
) -> None:
    value = TemporalValue.from_year(1984, qualifier=qualifier)

    assert present_temporal_value(value, presentation()) == expected


def test_a_qualifier_wraps_the_words_of_any_precision() -> None:
    value = TemporalValue.from_month(1984, 6, qualifier=TemporalQualifier.BOTH)

    words = present_temporal_value(value, presentation())

    assert words == "around June 1984 (uncertain)"


def test_no_qualifier_adds_no_words() -> None:
    value = TemporalValue.from_decade(1980)

    words = present_temporal_value(value, presentation())

    assert words == "1980s"


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        ("1984/1986", "1984 – 1986"),
        ("1984-06/1986", "June 1984 – 1986"),
        ("../1986", "until 1986"),
        ("1984/..", "since 1984"),
        ("/1986", "Unknown – 1986"),
        ("1984/", "1984 – Unknown"),
    ],
)
def test_a_range_says_each_endpoint(canonical: str, expected: str) -> None:
    value = TemporalValue.parse(canonical)

    assert present_temporal_value(value, presentation()) == expected


def test_each_endpoint_keeps_its_own_qualifier() -> None:
    value = TemporalValue.parse("1984~/1986?")

    words = present_temporal_value(value, presentation())

    assert words == "around 1984 – 1986 (uncertain)"
