"""Words for a stored temporal value, at the precision it knows.

``str(value)`` prints the canonical string, ``1984-06~``. That is the storage
form and not a sentence: it hides the precision behind punctuation and states
the qualifier as a symbol. This module answers words instead.

Every calendar decision belongs to :class:`DateTimePresentation` — the account
owns the order of the parts. This module decides only which parts there are.
"""

from datetime import date

from common.date_time_presentation import DateTimePresentation
from timetracker.temporal import TemporalPrecision, TemporalValue

UNKNOWN_TEXT = "Unknown"


def present_temporal_value(
    value: TemporalValue | None, presentation: DateTimePresentation
) -> str:
    """The words for ``value``, or ``Unknown`` where it states nothing."""
    if value is None or value.is_unknown:
        return UNKNOWN_TEXT
    return _at_precision(value, presentation)


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
