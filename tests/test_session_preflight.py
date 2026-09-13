"""What the legacy Session census reports."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from games.models import Session
from games.preflight.session import TimingVerdict, classify_timing

UTC = ZoneInfo("UTC")
START = datetime(2024, 3, 1, 10, 0, tzinfo=UTC)


def session(
    *, end: datetime | None = None, manual: timedelta | None = timedelta(0)
) -> Session:
    """An unsaved row holding only what the rule reads."""
    return Session(timestamp_start=START, timestamp_end=end, duration_manual=manual)


def test_an_end_after_the_start_with_no_manual_duration_is_timed():
    row = session(end=START + timedelta(hours=1))
    assert classify_timing(row) is TimingVerdict.TIMED


def test_an_end_equal_to_the_start_is_timed():
    assert classify_timing(session(end=START)) is TimingVerdict.TIMED


def test_no_end_with_a_manual_duration_is_duration_only():
    row = session(manual=timedelta(hours=2))
    assert classify_timing(row) is TimingVerdict.DURATION_ONLY


def test_an_end_and_a_manual_duration_is_corrected():
    row = session(end=START + timedelta(hours=1), manual=timedelta(hours=2))
    assert classify_timing(row) is TimingVerdict.CORRECTED


def test_no_end_and_no_manual_duration_is_running():
    assert classify_timing(session()) is TimingVerdict.RUNNING


def test_an_end_before_the_start_is_negative_elapsed():
    row = session(end=START - timedelta(hours=1))
    assert classify_timing(row) is TimingVerdict.NEGATIVE_ELAPSED


def test_a_reversed_row_is_named_by_its_interval_not_its_duration():
    row = session(end=START - timedelta(hours=1), manual=timedelta(hours=2))
    assert classify_timing(row) is TimingVerdict.NEGATIVE_ELAPSED


def test_a_negative_manual_duration_is_negative_manual():
    row = session(manual=timedelta(hours=-1))
    assert classify_timing(row) is TimingVerdict.NEGATIVE_MANUAL


def test_a_negative_manual_duration_outranks_a_timed_interval():
    row = session(end=START + timedelta(hours=1), manual=timedelta(hours=-1))
    assert classify_timing(row) is TimingVerdict.NEGATIVE_MANUAL


def test_a_null_manual_duration_reads_as_zero():
    assert classify_timing(session(manual=None)) is TimingVerdict.RUNNING


def test_a_null_manual_duration_leaves_a_timed_row_timed():
    row = session(end=START + timedelta(hours=1), manual=None)
    assert classify_timing(row) is TimingVerdict.TIMED


@pytest.mark.parametrize("verdict", list(TimingVerdict))
def test_every_verdict_spells_its_own_name(verdict: TimingVerdict):
    assert verdict.value == verdict.name.lower()
