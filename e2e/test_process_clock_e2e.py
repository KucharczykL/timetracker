"""The browser suite runs off the calendar's date too."""

import pytest
from calendar_days import process_day

from games.reads.calendar import calendar_today

pytestmark = pytest.mark.django_db(transaction=True)


def test_the_suite_runs_the_process_clock_off_a_fresh_calendar(e2e_library):
    """The autouse fixture's own claim."""
    assert calendar_today(e2e_library) != process_day()
