"""Words for a stored temporal value.

The value renders as its dataclass repr. This answers words.
"""

from datetime import date

from common.components.core import Node
from common.components.elements import Span
from common.date_time_presentation import DateTimePresentation
from timetracker.temporal import (
    TemporalEndpoint,
    TemporalPrecision,
    TemporalQualifier,
    TemporalValue,
)

UNKNOWN_TEXT = "Unknown"

_APPROXIMATE_PREFIX = "around "
_UNCERTAIN_SUFFIX = " (uncertain)"
_RANGE_JOINER = " – "


def present_temporal_value(
    value: TemporalValue | None, presentation: DateTimePresentation
) -> str:
    """The words for ``value``, or ``Unknown``."""
    if value is None or value.is_unknown:
        return UNKNOWN_TEXT
    if value.is_range:
        return _present_range(value, presentation)
    return _present_atomic(value, presentation)


def TemporalText(
    value: TemporalValue | None,
    presentation: DateTimePresentation,
    *,
    class_: str = "",
) -> Node:
    """The same words, as a placeable span."""
    return Span(class_=class_)[present_temporal_value(value, presentation)]


def _present_atomic(value: TemporalValue, presentation: DateTimePresentation) -> str:
    return _qualified(_at_precision(value, presentation), value.qualifier)


def _present_range(value: TemporalValue, presentation: DateTimePresentation) -> str:
    start, end = value.start, value.end
    if start is None or end is None:
        return UNKNOWN_TEXT
    if start.is_open:
        return f"until {_present_endpoint(end, presentation)}"
    if end.is_open:
        return f"since {_present_endpoint(start, presentation)}"
    start_words = _present_endpoint(start, presentation)
    end_words = _present_endpoint(end, presentation)
    return f"{start_words}{_RANGE_JOINER}{end_words}"


def _present_endpoint(
    endpoint: TemporalEndpoint, presentation: DateTimePresentation
) -> str:
    if endpoint.value is None:
        return UNKNOWN_TEXT
    return _present_atomic(endpoint.value, presentation)


def _qualified(words: str, qualifier: TemporalQualifier | None) -> str:
    """A reader gets words, not a symbol."""
    if qualifier is None:
        return words
    if qualifier is TemporalQualifier.APPROXIMATE:
        return f"{_APPROXIMATE_PREFIX}{words}"
    if qualifier is TemporalQualifier.UNCERTAIN:
        return f"{words}{_UNCERTAIN_SUFFIX}"
    return f"{_APPROXIMATE_PREFIX}{words}{_UNCERTAIN_SUFFIX}"


def _at_precision(value: TemporalValue, presentation: DateTimePresentation) -> str:
    match value.precision:
        case TemporalPrecision.DAY:
            return presentation.format(_day_date(value), "date")
        case TemporalPrecision.MONTH:
            return presentation.format(_month_date(value), "month_year")
        case TemporalPrecision.YEAR:
            return _four_digits(value.year)
        case TemporalPrecision.DECADE:
            return _decade(value.decade_start_year)
        case _:
            return UNKNOWN_TEXT


def _day_date(value: TemporalValue) -> date:
    """The stored day. Every part is present."""
    year, month, day = value.year, value.month, value.day
    if year is None or month is None or day is None:
        raise ValueError("A day temporal value states every part.")
    return date(year, month, day)


def _month_date(value: TemporalValue) -> date:
    """A carrier for the month style.

    The day is a fabrication. ``month_year`` discards it, and no
    other style may read this date.
    """
    year, month = value.year, value.month
    if year is None or month is None:
        raise ValueError("A month temporal value states both parts.")
    return date(year, month, 1)


def _four_digits(year: int | None) -> str:
    return UNKNOWN_TEXT if year is None else f"{year:04d}"


def _decade(start_year: int | None) -> str:
    """The plural letter never follows the sentinel."""
    return UNKNOWN_TEXT if start_year is None else f"{start_year:04d}s"
