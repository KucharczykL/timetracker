from random import Random

import pytest
from django.db import IntegrityError, OperationalError

from games.events.retry import (
    DEFAULT_RETRY_POLICY,
    RetryPolicy,
    is_retryable,
)
from games.models import LIBRARY_EVENT_SEQUENCE_CONSTRAINT


class FakeDiagnostic:
    def __init__(self, constraint_name: str | None) -> None:
        self.constraint_name = constraint_name


class FakeDriverError(Exception):
    """Stands in for the psycopg exception Django re-raises `from`."""

    def __init__(self, sqlstate: str, constraint_name: str | None = None) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate
        self.diag = FakeDiagnostic(constraint_name)


def wrapped(
    django_error: type[Exception],
    sqlstate: str,
    constraint_name: str | None = None,
) -> Exception:
    """Build the shape Django produces: its own exception, chained `from` the
    driver's."""
    try:
        try:
            raise FakeDriverError(sqlstate, constraint_name)
        except FakeDriverError as driver_error:
            raise django_error("wrapped") from driver_error
    except Exception as error:  # noqa: BLE001 - returning it, not handling it
        return error


#: Parametrized over the SQLSTATE, not over a built exception: an exception
#: built in the decorator is constructed once at collection time and shared by
#: every worker for the whole session, and its test id would be `error0`
#: instead of the state, so `-k 40P01` could not select a case.
@pytest.mark.parametrize(
    ("django_error", "sqlstate", "constraint_name"),
    [
        (OperationalError, "40001", None),
        (OperationalError, "40P01", None),
        (IntegrityError, "23505", LIBRARY_EVENT_SEQUENCE_CONSTRAINT),
    ],
)
def test_the_charters_three_failures_are_retryable(
    django_error, sqlstate, constraint_name
):
    assert is_retryable(wrapped(django_error, sqlstate, constraint_name)) is True


@pytest.mark.parametrize(
    ("django_error", "sqlstate", "constraint_name"),
    [
        #: The idempotency record's collision: the head lock failed to
        #: serialize two same-key commands, which is a bug and must stay
        #: visible rather than being retried away.
        (IntegrityError, "23505", "unique_library_idempotency_key"),
        (IntegrityError, "23505", None),
        (IntegrityError, "23503", None),
        (OperationalError, "57014", None),
    ],
)
def test_everything_else_is_terminal(django_error, sqlstate, constraint_name):
    assert is_retryable(wrapped(django_error, sqlstate, constraint_name)) is False


def test_an_error_that_is_not_a_database_failure_is_terminal():
    assert is_retryable(ValueError("not a database failure at all")) is False


def test_an_error_with_no_driver_cause_is_terminal():
    assert is_retryable(IntegrityError("hand-rolled, no cause")) is False


def test_the_default_budget_is_the_charters_three():
    assert DEFAULT_RETRY_POLICY.retries == 3


def test_each_delay_stays_inside_a_bound_that_doubles():
    policy = RetryPolicy(random=Random(0))
    bounds = [0.025, 0.050, 0.100]
    previous_bound = 0.0
    for attempt, bound in enumerate(bounds):
        #: Sampled repeatedly: one draw could sit inside the wrong bound.
        draws = [policy.delay_for(attempt) for _ in range(200)]
        assert min(draws) >= 0.0
        assert max(draws) <= bound
        #: The ceiling alone is satisfied by `return 0.0` and by a bound that
        #: never doubles. 200 uniform draws land within a percent of their own
        #: ceiling, so the previous bound is a floor this one must clear.
        assert max(draws) > previous_bound
        previous_bound = bound


def test_the_bound_stops_growing_at_the_cap():
    policy = RetryPolicy(retries=10, random=Random(0))
    assert max(policy.delay_for(9) for _ in range(200)) <= DEFAULT_RETRY_POLICY.max_delay


def test_a_policy_carries_its_own_randomness():
    #: Two policies seeded alike produce the same sequence, so a test asserting
    #: on delays is reproducible without patching the stdlib random module.
    first = RetryPolicy(random=Random(7))
    second = RetryPolicy(random=Random(7))
    assert first.delay_for(0) == second.delay_for(0)
