"""What the legacy Session census reports."""

import uuid
from dataclasses import fields
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from games.models import Session
from games.preflight.session import (
    NO_COUNTS,
    AssignmentOutcome,
    PreflightCounts,
    RunInterval,
    Samples,
    TimingVerdict,
    assign_run,
    claims,
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


DAY = date(2024, 3, 1)


def interval(started: date | None = None, completed: date | None = None) -> RunInterval:
    """A run bounded by whichever days are known."""
    return RunInterval(uuid.uuid4(), started, completed)


def test_a_sole_run_takes_the_session_however_far_outside_it_falls():
    only = interval(date(2020, 1, 1), date(2020, 2, 1))
    assignment = assign_run([only], DAY)
    assert assignment.outcome is AssignmentOutcome.SOLE_RUN
    assert assignment.run_id == only.run_id
    assert assignment.claimers == 0


def test_a_sole_run_stating_no_day_still_takes_the_session():
    assignment = assign_run([interval()], DAY)
    assert assignment.outcome is AssignmentOutcome.SOLE_RUN


def test_a_game_with_no_live_run_buckets():
    assignment = assign_run([], DAY)
    assert assignment.outcome is AssignmentOutcome.BUCKET
    assert assignment.run_id is None
    assert assignment.claimers == 0


def test_one_claimer_among_several_runs_takes_the_session():
    claimer = interval(date(2024, 2, 1), date(2024, 4, 1))
    other = interval(date(2023, 1, 1), date(2023, 2, 1))
    assignment = assign_run([other, claimer], DAY)
    assert assignment.outcome is AssignmentOutcome.CONTAINED
    assert assignment.run_id == claimer.run_id
    assert assignment.claimers == 1


def test_a_day_inside_no_run_buckets():
    runs = [
        interval(date(2023, 1, 1), date(2023, 2, 1)),
        interval(date(2025, 1, 1), date(2025, 2, 1)),
    ]
    assignment = assign_run(runs, DAY)
    assert assignment.outcome is AssignmentOutcome.BUCKET
    assert assignment.claimers == 0


def test_a_day_inside_two_runs_buckets_and_counts_both():
    runs = [
        interval(date(2024, 1, 1), date(2024, 4, 1)),
        interval(date(2024, 2, 1), date(2024, 5, 1)),
    ]
    assignment = assign_run(runs, DAY)
    assert assignment.outcome is AssignmentOutcome.BUCKET
    assert assignment.run_id is None
    assert assignment.claimers == 2


def test_a_start_only_run_claims_its_start_day_and_every_later_one():
    run = interval(started=DAY)
    assert claims(run, DAY)
    assert claims(run, DAY + timedelta(days=3650))
    assert not claims(run, DAY - timedelta(days=1))


def test_a_completion_only_run_claims_its_day_and_every_earlier_one():
    run = interval(completed=DAY)
    assert claims(run, DAY)
    assert claims(run, DAY - timedelta(days=3650))
    assert not claims(run, DAY + timedelta(days=1))


def test_a_dated_run_claims_both_its_endpoints_and_nothing_outside():
    run = interval(DAY, DAY + timedelta(days=7))
    assert claims(run, DAY)
    assert claims(run, DAY + timedelta(days=7))
    assert not claims(run, DAY - timedelta(days=1))
    assert not claims(run, DAY + timedelta(days=8))


def test_a_run_stating_no_day_claims_nothing():
    assert not claims(interval(), DAY)
