"""Words for a stored temporal value, at the precision it knows.

``str(value)`` prints the canonical string, ``1984-06~``. That is the storage
form and not a sentence: it hides the precision behind punctuation and states
the qualifier as a symbol. This module answers words instead.

Every calendar decision belongs to :class:`DateTimePresentation` — the account
owns the order of the parts. This module decides only which parts there are.
"""

from datetime import date

from common.date_time_presentation import DateTimePresentation
from timetracker.temporal import TemporalPrecision, TemporalQualifier, TemporalValue

UNKNOWN_TEXT = "Unknown"

_APPROXIMATE_PREFIX = "around "
_UNCERTAIN_SUFFIX = " (uncertain)"


def present_temporal_value(
    value: TemporalValue | None, presentation: DateTimePresentation
) -> str:
    """The words for ``value``, or ``Unknown`` where it states nothing."""
    if value is None or value.is_unknown:
        return UNKNOWN_TEXT
    return _present_atomic(value, presentation)


def _present_atomic(value: TemporalValue, presentation: DateTimePresentation) -> str:
    return _qualified(_at_precision(value, presentation), value.qualifier)


def _qualified(words: str, qualifier: TemporalQualifier | None) -> str:
    """A symbol is storage. A reader gets words."""
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
            return f"{_four_digits(value.decade_start_year)}s"
        case _:
            return UNKNOWN_TEXT


def _day_date(value: TemporalValue) -> date:
    """The stored day. Every part is present at this precision."""
    year, month, day = value.year, value.month, value.day
    if year is None or month is None or day is None:
        raise ValueError("A day temporal value states every part.")
    return date(year, month, day)


def _month_date(value: TemporalValue) -> date:
    """A carrier for the month style. The day never reaches a reader."""
    year, month = value.year, value.month
    if year is None or month is None:
        raise ValueError("A month temporal value states both parts.")
    return date(year, month, 1)


def _four_digits(year: int | None) -> str:
    return UNKNOWN_TEXT if year is None else f"{year:04d}"
