from unittest.mock import Mock

from timetracker import database
from timetracker.database import (
    CLOCK_SKEW_TOLERANCE_MS,
    ClockSkewWarningState,
    measure_clock_skew,
    validate_default_connection,
)
from timetracker.postgres_contract import (
    PostgresConnectionObservation,
    PostgresContract,
)


class DefaultConnection:
    alias = "default"


def test_clock_measurement_accepts_database_time_inside_latency_interval():
    measured = measure_clock_skew(
        database_time_ms=1_500,
        started_wall_ms=1_000,
        finished_wall_ms=2_000,
        round_trip_ms=1_000,
    )

    assert measured.outside_tolerance is False
    assert measured.estimated_skew_ms == 0


def test_clock_measurement_detects_positive_and_negative_skew():
    positive = measure_clock_skew(3_001, 1_000, 2_000, 25)
    negative = measure_clock_skew(-1, 1_000, 2_000, 25)

    assert positive.outside_tolerance is True
    assert positive.estimated_skew_ms > CLOCK_SKEW_TOLERANCE_MS
    assert negative.outside_tolerance is True
    assert negative.estimated_skew_ms < -CLOCK_SKEW_TOLERANCE_MS


def test_clock_warning_state_warns_once_then_rearms_after_recovery():
    state = ClockSkewWarningState()

    assert state.observe(True) is True
    assert state.observe(True) is False
    assert state.observe(False) is False
    assert state.observe(True) is True


def test_default_connection_warns_for_skew_without_rejecting_it(monkeypatch):
    observation = PostgresConnectionObservation(
        PostgresContract(180004, "UTF8", "b", "C.UTF-8"),
        3_001,
    )
    warning = Mock()
    wall_samples_ns = iter([1_000_000_000, 2_000_000_000])
    monotonic_samples_ns = iter([10_000_000_000, 10_025_000_000])

    monkeypatch.setattr(
        database, "observe_valid_postgres_connection", lambda connection: observation
    )
    monkeypatch.setattr(database.time, "time_ns", lambda: next(wall_samples_ns))
    monkeypatch.setattr(
        database.time, "monotonic_ns", lambda: next(monotonic_samples_ns)
    )
    monkeypatch.setattr(database.logger, "warning", warning)
    monkeypatch.setattr(database, "_clock_skew_warnings", ClockSkewWarningState())

    assert (
        validate_default_connection(sender=None, connection=DefaultConnection()) is None
    )
    warning.assert_called_once()
    assert "estimated_skew_ms" in warning.call_args.args[0]
