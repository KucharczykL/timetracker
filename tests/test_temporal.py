from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime

import pytest

from timetracker.temporal import (
    TemporalEndpoint,
    TemporalEndpointKind,
    TemporalPrecision,
    TemporalQualifier,
    TemporalValue,
    TemporalValueKind,
    TemporalValueParseError,
    parse_temporal_value,
    validate_temporal_value,
)


@pytest.mark.parametrize(
    (
        "canonical",
        "lower",
        "upper",
        "kind",
        "precision",
        "known_components",
        "complete_day",
    ),
    [
        (
            None,
            None,
            None,
            TemporalValueKind.UNKNOWN,
            None,
            (False, False, False),
            False,
        ),
        (
            "2024-02-29",
            date(2024, 2, 29),
            date(2024, 2, 29),
            TemporalValueKind.ATOMIC,
            TemporalPrecision.DAY,
            (True, True, True),
            True,
        ),
        (
            "2023-02",
            date(2023, 2, 1),
            date(2023, 2, 28),
            TemporalValueKind.ATOMIC,
            TemporalPrecision.MONTH,
            (True, True, False),
            False,
        ),
        (
            "2024",
            date(2024, 1, 1),
            date(2024, 12, 31),
            TemporalValueKind.ATOMIC,
            TemporalPrecision.YEAR,
            (True, False, False),
            False,
        ),
        (
            "199X",
            date(1990, 1, 1),
            date(1999, 12, 31),
            TemporalValueKind.ATOMIC,
            TemporalPrecision.DECADE,
            (False, False, False),
            False,
        ),
        (
            "1999/2001-03",
            date(1999, 1, 1),
            date(2001, 3, 31),
            TemporalValueKind.RANGE,
            None,
            (False, False, False),
            False,
        ),
        (
            "2020/2020-01",
            date(2020, 1, 1),
            date(2020, 1, 31),
            TemporalValueKind.RANGE,
            None,
            (False, False, False),
            False,
        ),
        (
            "../2001-03",
            None,
            date(2001, 3, 31),
            TemporalValueKind.RANGE,
            None,
            (False, False, False),
            False,
        ),
        (
            "1999/..",
            date(1999, 1, 1),
            None,
            TemporalValueKind.RANGE,
            None,
            (False, False, False),
            False,
        ),
        (
            "/2001-03",
            None,
            date(2001, 3, 31),
            TemporalValueKind.RANGE,
            None,
            (False, False, False),
            False,
        ),
        (
            "1999/",
            date(1999, 1, 1),
            None,
            TemporalValueKind.RANGE,
            None,
            (False, False, False),
            False,
        ),
    ],
)
def test_temporal_value_preserves_supported_precision_and_bounds(
    canonical,
    lower,
    upper,
    kind,
    precision,
    known_components,
    complete_day,
):
    value = TemporalValue.parse(canonical)

    assert value.canonical == canonical
    assert value.lower_bound == lower
    assert value.upper_bound == upper
    assert value.kind is kind
    assert value.precision is precision
    assert (
        value.has_known_year,
        value.has_known_month,
        value.has_known_day,
    ) == known_components
    assert value.is_complete_day is complete_day
    assert value.is_exact_day is complete_day
    assert value.is_range is (kind is TemporalValueKind.RANGE)
    assert value.is_unknown is (kind is TemporalValueKind.UNKNOWN)
    assert value.serialize() == canonical
    assert TemporalValue.parse(value.serialize()) == value
    assert hash(TemporalValue.parse(value.serialize())) == hash(value)


@pytest.mark.parametrize(
    ("canonical", "start_kind", "start_value", "end_kind", "end_value"),
    [
        (
            "1999/2001-03",
            TemporalEndpointKind.KNOWN,
            "1999",
            TemporalEndpointKind.KNOWN,
            "2001-03",
        ),
        (
            "../2001-03",
            TemporalEndpointKind.OPEN,
            None,
            TemporalEndpointKind.KNOWN,
            "2001-03",
        ),
        (
            "1999/..",
            TemporalEndpointKind.KNOWN,
            "1999",
            TemporalEndpointKind.OPEN,
            None,
        ),
        (
            "/2001-03",
            TemporalEndpointKind.UNKNOWN,
            None,
            TemporalEndpointKind.KNOWN,
            "2001-03",
        ),
        (
            "1999/",
            TemporalEndpointKind.KNOWN,
            "1999",
            TemporalEndpointKind.UNKNOWN,
            None,
        ),
    ],
)
def test_temporal_range_preserves_endpoint_kind_and_value(
    canonical, start_kind, start_value, end_kind, end_value
):
    value = TemporalValue.parse(canonical)

    assert value.start is not None
    assert value.end is not None
    assert value.start.kind is start_kind
    assert value.end.kind is end_kind
    assert (
        None if value.start.value is None else value.start.value.canonical
    ) == start_value
    assert (None if value.end.value is None else value.end.value.canonical) == end_value
    assert value.start.is_known is (start_kind is TemporalEndpointKind.KNOWN)
    assert value.start.is_unknown is (start_kind is TemporalEndpointKind.UNKNOWN)
    assert value.start.is_open is (start_kind is TemporalEndpointKind.OPEN)
    assert value.end.is_known is (end_kind is TemporalEndpointKind.KNOWN)
    assert value.end.is_unknown is (end_kind is TemporalEndpointKind.UNKNOWN)
    assert value.end.is_open is (end_kind is TemporalEndpointKind.OPEN)


def test_temporal_named_constructors_generate_canonical_values():
    assert TemporalValue.unknown() == TemporalValue.parse(None)
    assert TemporalValue.from_day(date(2024, 2, 29)).canonical == "2024-02-29"
    assert TemporalValue.from_month(2024, 2).canonical == "2024-02"
    assert TemporalValue.from_year(2024).canonical == "2024"
    assert TemporalValue.from_decade(1990).canonical == "199X"
    assert (
        TemporalValue.range(
            start=TemporalEndpoint.known(TemporalValue.from_year(1999)),
            end=TemporalEndpoint.open(),
        ).canonical
        == "1999/.."
    )


def test_temporal_values_and_endpoints_are_immutable():
    value = TemporalValue.parse("2024")
    endpoint = TemporalEndpoint.known(value)

    with pytest.raises(FrozenInstanceError):
        value.canonical = "2025"
    with pytest.raises(FrozenInstanceError):
        endpoint.kind = TemporalEndpointKind.OPEN


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (True, "invalid_type"),
        (2024, "invalid_type"),
        ([], "invalid_type"),
        ("", "invalid_syntax"),
        (" 2024", "invalid_syntax"),
        ("2024 ", "invalid_syntax"),
        ("199x", "invalid_syntax"),
        ("２０２４", "invalid_syntax"),
        ("٢٠٢٤-٠٢", "invalid_syntax"),
        ("2024‐02", "invalid_syntax"),
        ("2024⁄02", "invalid_syntax"),
        ("2023-02-29", "invalid_date"),
        ("2024-13", "invalid_date"),
        ("2024-00-01", "invalid_date"),
        ("2024-01-00", "invalid_date"),
        ("2024/2023", "invalid_range"),
        ("../..", "invalid_range"),
        ("../", "invalid_range"),
        ("/..", "invalid_range"),
        ("/", "invalid_range"),
        ("2024/2025/2026", "invalid_range"),
        ("?2024", "unsupported_component_qualifier"),
        ("2024-?02", "unsupported_component_qualifier"),
        ("~2024-02-29", "unsupported_component_qualifier"),
        ("2024?~", "invalid_qualifier"),
        ("2024~?", "invalid_qualifier"),
        ("2024??", "invalid_qualifier"),
        ("2024-02-29~~", "invalid_qualifier"),
        ("~/2025", "unsupported_endpoint_qualifier"),
        ("..?/2025", "unsupported_endpoint_qualifier"),
        ("2024/%", "unsupported_endpoint_qualifier"),
        ("?", "invalid_syntax"),
        ("~", "invalid_syntax"),
        ("%", "invalid_syntax"),
        ("2001-21~", "unsupported_season"),
        ("[2020~]", "unsupported_set"),
        ("2024-01-01T12:00~", "unsupported_timestamp"),
        ("19X4~", "unsupported_unspecified_component"),
        ("0000~", "unsupported_year"),
        ("10000~", "unsupported_year"),
        ("Y170000002~", "unsupported_year"),
        ("-1985~", "unsupported_year"),
        ("2001-21", "unsupported_season"),
        ("[2020,2021]", "unsupported_set"),
        ("{2020,2021}", "unsupported_set"),
        ("2004-XX", "unsupported_unspecified_component"),
        ("1985-04-XX", "unsupported_unspecified_component"),
        ("1985-XX-XX", "unsupported_unspecified_component"),
        ("XXXX-XX-12", "unsupported_unspecified_component"),
        ("2004-XX/2005", "unsupported_unspecified_component"),
        ("0000", "unsupported_year"),
        ("0000-01", "unsupported_year"),
        ("0000-01-01", "unsupported_year"),
        ("000X", "unsupported_year"),
        ("-1985", "unsupported_year"),
        ("Y170000002", "unsupported_year"),
        ("10000", "unsupported_year"),
        ("10000-01", "unsupported_year"),
        ("10000-01-01", "unsupported_year"),
        ("2024/10000-01", "unsupported_year"),
        ("10000-01/2024", "unsupported_year"),
        ("2024-01-01T12:00:00", "unsupported_timestamp"),
    ],
)
def test_temporal_validation_fails_closed_with_precise_code(value, code):
    with pytest.raises(TemporalValueParseError) as caught:
        parse_temporal_value(value)

    assert caught.value.code == code
    assert str(caught.value)


def test_validate_temporal_value_accepts_values_without_replacing_them():
    value = TemporalValue.parse("2024-02")

    assert parse_temporal_value(value) is value
    assert validate_temporal_value(value) is None


@pytest.mark.parametrize(
    ("constructor", "args", "error"),
    [
        (TemporalValue.from_day, ("2024-01-01",), TypeError),
        (TemporalValue.from_day, (datetime(2024, 1, 1, tzinfo=UTC),), TypeError),
        (TemporalValue.from_month, (True, 1), TypeError),
        (TemporalValue.from_month, (2024, False), TypeError),
        (TemporalValue.from_year, (True,), TypeError),
        (TemporalValue.from_decade, (1991,), ValueError),
        (TemporalValue.from_decade, (0,), ValueError),
        (TemporalValue.from_decade, (True,), TypeError),
    ],
)
def test_temporal_named_constructors_reject_incoherent_input(constructor, args, error):
    with pytest.raises(error):
        constructor(*args)


def test_known_endpoint_rejects_non_atomic_and_wrong_values():
    with pytest.raises(TypeError):
        TemporalEndpoint.known("2024")
    with pytest.raises(ValueError):
        TemporalEndpoint.known(TemporalValue.unknown())
    with pytest.raises(ValueError):
        TemporalEndpoint.known(TemporalValue.parse("2024/2025"))


def test_temporal_range_constructor_requires_endpoints_and_known_bound():
    with pytest.raises(TypeError):
        TemporalValue.range(start="2024", end=TemporalEndpoint.open())
    with pytest.raises(TemporalValueParseError) as caught:
        TemporalValue.range(
            start=TemporalEndpoint.open(), end=TemporalEndpoint.unknown()
        )
    assert caught.value.code == "invalid_range"


def test_atomic_and_unknown_values_do_not_alias_range_endpoints():
    assert TemporalValue.parse("2024").start is None
    assert TemporalValue.parse("2024").end is None
    assert TemporalValue.unknown().start is None
    assert TemporalValue.unknown().end is None


@pytest.mark.parametrize(
    ("canonical", "qualifier", "precision", "lower", "upper"),
    [
        (
            "1984-06-11~",
            TemporalQualifier.APPROXIMATE,
            TemporalPrecision.DAY,
            date(1984, 6, 11),
            date(1984, 6, 11),
        ),
        (
            "1984-06?",
            TemporalQualifier.UNCERTAIN,
            TemporalPrecision.MONTH,
            date(1984, 6, 1),
            date(1984, 6, 30),
        ),
        (
            "1984%",
            TemporalQualifier.BOTH,
            TemporalPrecision.YEAR,
            date(1984, 1, 1),
            date(1984, 12, 31),
        ),
        (
            "198X~",
            TemporalQualifier.APPROXIMATE,
            TemporalPrecision.DECADE,
            date(1980, 1, 1),
            date(1989, 12, 31),
        ),
        ("1984", None, TemporalPrecision.YEAR, date(1984, 1, 1), date(1984, 12, 31)),
    ],
)
def test_a_qualifier_says_how_sure_and_never_moves_the_bounds(
    canonical, qualifier, precision, lower, upper
):
    value = TemporalValue.parse(canonical)

    assert value.canonical == canonical
    assert value.qualifier is qualifier
    assert value.precision is precision
    assert value.lower_bound == lower
    assert value.upper_bound == upper
    assert value.kind is TemporalValueKind.ATOMIC
    assert value.is_uncertain is (
        qualifier in (TemporalQualifier.UNCERTAIN, TemporalQualifier.BOTH)
    )
    assert value.is_approximate is (
        qualifier in (TemporalQualifier.APPROXIMATE, TemporalQualifier.BOTH)
    )
    assert TemporalValue.parse(value.serialize()) == value


def test_a_range_qualifies_each_endpoint_on_its_own():
    value = TemporalValue.parse("1984/1986~")

    assert value.kind is TemporalValueKind.RANGE
    assert value.qualifier is None
    assert value.start is not None
    assert value.end is not None
    assert value.start.qualifier is None
    assert value.end.qualifier is TemporalQualifier.APPROXIMATE
    assert value.lower_bound == date(1984, 1, 1)
    assert value.upper_bound == date(1986, 12, 31)


def test_an_endpoint_without_a_value_answers_no_qualifier():
    assert TemporalEndpoint.unknown().qualifier is None
    assert TemporalEndpoint.open().qualifier is None
    assert TemporalValue.unknown().qualifier is None
    assert TemporalValue.unknown().is_approximate is False


def test_how_precise_and_how_sure_are_two_questions():
    """`1984-06-11%` is an exact day the writer is unsure of. Both are true."""
    exact_but_unsure = TemporalValue.parse("1984-06-11%")

    assert exact_but_unsure.is_exact_day is True
    assert exact_but_unsure.is_complete_day is True
    assert exact_but_unsure.has_known_day is True
    assert exact_but_unsure.is_uncertain is True
    assert exact_but_unsure.is_approximate is True

    assert TemporalValue.parse("1984-06-11").is_exact_day is True
    assert TemporalValue.parse("1984~").is_exact_day is False


def test_named_constructors_write_the_symbol_they_are_given():
    approximate = TemporalQualifier.APPROXIMATE
    uncertain = TemporalQualifier.UNCERTAIN
    both = TemporalQualifier.BOTH

    assert (
        TemporalValue.from_day(date(2024, 2, 29), qualifier=both).canonical
        == "2024-02-29%"
    )
    assert (
        TemporalValue.from_month(2024, 2, qualifier=uncertain).canonical == "2024-02?"
    )
    assert TemporalValue.from_year(2024, qualifier=approximate).canonical == "2024~"
    assert TemporalValue.from_decade(1990, qualifier=approximate).canonical == "199X~"
    assert TemporalValue.from_year(2024).canonical == "2024"

    start = TemporalEndpoint.known(TemporalValue.from_year(1984, qualifier=approximate))
    end = TemporalEndpoint.known(TemporalValue.from_year(1986, qualifier=approximate))
    assert TemporalValue.range(start=start, end=end).canonical == "1984~/1986~"

    with pytest.raises(TypeError):
        TemporalValue.from_year(2024, qualifier="approximate")


@pytest.mark.parametrize(
    ("canonical", "year", "month", "day", "decade_start_year"),
    [
        ("1984-06-11", 1984, 6, 11, None),
        ("1984-06-11~", 1984, 6, 11, None),
        ("1984-06", 1984, 6, None, None),
        ("1984", 1984, None, None, None),
        ("198X", None, None, None, 1980),
        ("198X~", None, None, None, 1980),
        ("1984/1986", None, None, None, None),
        (None, None, None, None, None),
    ],
)
def test_a_value_reads_apart_into_the_parts_its_precision_knows(
    canonical, year, month, day, decade_start_year
):
    value = TemporalValue.parse(canonical)

    assert value.year == year
    assert value.month == month
    assert value.day == day
    assert value.decade_start_year == decade_start_year


def test_an_endpoint_delegates_the_parts_of_the_value_it_holds():
    value = TemporalValue.parse("1984-06?")
    known = TemporalEndpoint.known(value)

    assert (known.year, known.month, known.day) == (1984, 6, None)
    assert known.decade_start_year is None
    assert known.qualifier is TemporalQualifier.UNCERTAIN

    for endpoint in (TemporalEndpoint.unknown(), TemporalEndpoint.open()):
        assert endpoint.year is None
        assert endpoint.month is None
        assert endpoint.day is None
        assert endpoint.decade_start_year is None
