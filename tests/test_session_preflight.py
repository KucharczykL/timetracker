"""What the legacy Session census reports."""

import uuid
from dataclasses import fields
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from games.models import Session
from games.preflight.session import (
    NO_COUNTS,
    PreflightCounts,
    Samples,
    TimingVerdict,
    classify_timing,
)

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


def test_counts_sum_field_by_field():
    left = PreflightCounts(sessions_in_scope=3, timed=2, day_differs=1)
    right = PreflightCounts(sessions_in_scope=4, timed=1, sole_run=5)
    assert left + right == PreflightCounts(
        sessions_in_scope=7, timed=3, day_differs=1, sole_run=5
    )


def test_the_empty_counts_are_an_identity():
    populated = PreflightCounts(sessions_in_scope=9, bucket_primary=2)
    assert populated + NO_COUNTS == populated
    assert NO_COUNTS + populated == populated


def test_counts_render_every_field():
    rendered = PreflightCounts(timed=1).as_dict()
    assert set(rendered) == {field.name for field in fields(PreflightCounts)}
    assert rendered["timed"] == 1


def test_every_verdict_has_a_count_named_after_it():
    names = {field.name for field in fields(PreflightCounts)}
    assert {verdict.value for verdict in TimingVerdict} <= names


def test_samples_render_as_strings():
    identifier = uuid.uuid4()
    rendered = Samples(running=(identifier,)).as_dict()
    assert rendered["running"] == [str(identifier)]
    assert rendered["bucket_primary"] == []
    assert set(rendered) == {field.name for field in fields(Samples)}
