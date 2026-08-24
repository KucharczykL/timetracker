import uuid
from random import Random
from threading import Barrier, Thread
from typing import TypedDict

import pytest
from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    transaction,
)
from django.utils import timezone

from games.events.append import AppendResult, lock_stream
from games.events.idempotency import IdempotencyKeyMismatch, idempotent_append
from games.events.retry import (
    DEFAULT_RETRY_POLICY,
    NestedTransactionNotSupported,
    RetryBudgetExhausted,
    RetryPolicy,
    is_retryable,
    run_in_transaction,
)
from games.events.vocabulary import EventSpec, NewEvent
from games.models import (
    LIBRARY_EVENT_SEQUENCE_CONSTRAINT,
    LibraryEvent,
    LibraryIdempotencyRecord,
    Platform,
)


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
    assert (
        max(policy.delay_for(9) for _ in range(200)) <= DEFAULT_RETRY_POLICY.max_delay
    )


def test_a_policy_carries_its_own_randomness():
    #: Two policies seeded alike produce the same sequence, so a test asserting
    #: on delays is reproducible without patching the stdlib random module.
    first = RetryPolicy(random=Random(7))
    second = RetryPolicy(random=Random(7))
    assert first.delay_for(0) == second.delay_for(0)


class RecordingSleep:
    """Stands in for time.sleep, so the suite never actually waits."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def recording_policy(**overrides) -> tuple[RetryPolicy, RecordingSleep]:
    sleeper = RecordingSleep()
    return RetryPolicy(sleep=sleeper, random=Random(0), **overrides), sleeper


def games_records(caplog):
    #: pytest attaches caplog's handler to the root logger for the whole test
    #: as well, so any WARNING from a propagating django.* logger would show up
    #: in an unfiltered caplog.records.
    return [record for record in caplog.records if record.name.startswith("games")]


@pytest.mark.django_db(transaction=True)
def test_it_returns_what_the_operation_returns():
    assert run_in_transaction(lambda: "recorded") == "recorded"


@pytest.mark.django_db(transaction=True)
def test_it_refuses_to_retry_beneath_another_transaction():
    with (
        transaction.atomic(),
        pytest.raises(NestedTransactionNotSupported),
    ):
        run_in_transaction(lambda: "never reached")


@pytest.mark.django_db(transaction=True)
def test_a_retryable_failure_that_clears_is_retried_and_succeeds():
    policy, sleeper = recording_policy()
    attempts = []

    def operation():
        attempts.append(len(attempts))
        if len(attempts) < 3:
            raise wrapped(OperationalError, "40P01")
        return "recorded"

    assert run_in_transaction(operation, policy=policy) == "recorded"
    assert len(attempts) == 3
    assert len(sleeper.delays) == 2


@pytest.mark.django_db(transaction=True)
def test_an_always_failing_retryable_error_exhausts_the_budget():
    policy, sleeper = recording_policy()
    attempts = []

    def operation():
        attempts.append(len(attempts))
        raise wrapped(OperationalError, "40001")

    with pytest.raises(RetryBudgetExhausted) as raised:
        run_in_transaction(operation, policy=policy)

    #: Three retries after the first attempt, per the charter.
    assert len(attempts) == 4
    assert raised.value.attempts == 4
    assert len(sleeper.delays) == 3
    assert isinstance(raised.value.__cause__, OperationalError)


@pytest.mark.django_db(transaction=True)
def test_a_terminal_failure_is_raised_untouched_and_never_delayed(
    capture_games_logger,
):
    policy, sleeper = recording_policy()
    attempts = []

    def operation():
        attempts.append(len(attempts))
        raise wrapped(IntegrityError, "23505", "unique_library_idempotency_key")

    with capture_games_logger() as caplog, pytest.raises(IntegrityError):
        run_in_transaction(operation, policy=policy)

    assert len(attempts) == 1
    assert sleeper.delays == []
    assert games_records(caplog) == []


@pytest.mark.django_db(transaction=True)
def test_a_conflict_is_neither_retried_nor_reclassified():
    policy, sleeper = recording_policy()
    attempts = []

    def operation():
        attempts.append(len(attempts))
        raise IdempotencyKeyMismatch("the key already recorded something else")

    with pytest.raises(IdempotencyKeyMismatch):
        run_in_transaction(operation, policy=policy)

    assert len(attempts) == 1
    assert sleeper.delays == []


@pytest.mark.django_db(transaction=True)
def test_each_retry_is_logged(capture_games_logger):
    policy, _ = recording_policy()

    def operation():
        raise wrapped(OperationalError, "40P01")

    with capture_games_logger() as caplog, pytest.raises(RetryBudgetExhausted):
        run_in_transaction(operation, policy=policy)

    #: One line per retry, none for the exhaustion: the exception is that record.
    retry_logs = games_records(caplog)
    assert len(retry_logs) == 3
    assert "40P01" in retry_logs[0].getMessage()


class ProbePayload(TypedDict):
    probe: bool


PROBE_RECORDED = EventSpec(
    "probe.recorded", aggregate_type="probe", payload=ProbePayload
)


def one_event() -> NewEvent:
    return NewEvent(
        spec=PROBE_RECORDED,
        aggregate_id=uuid.uuid7(),
        payload={},
    )


@pytest.mark.django_db(transaction=True)
def test_a_real_sequence_collision_is_recognised_and_retried(owned_library):
    """The classifier's whole job is reading a real psycopg error through
    Django's wrapper. Only a real one proves the attribute path."""
    with transaction.atomic():
        first = lock_stream(owned_library).append(
            [one_event()],
            actor=None,
            correlation_id=uuid.uuid7(),
            idempotency_key="seed",
        )

    policy, sleeper = recording_policy()
    attempts = []

    def operation():
        attempts.append(len(attempts))
        #: Deliberately outside the head lock, at a sequence already taken.
        LibraryEvent.objects.create(
            library=owned_library,
            stream_id=first.stream_id,
            sequence=first.last_sequence,
            event_type="probe.recorded",
            aggregate_type="probe",
            aggregate_id=uuid.uuid7(),
            payload={},
            recorded_at=timezone.now(),
            effective_time=None,
            actor=None,
            correlation_id=uuid.uuid7(),
            idempotency_key="collides",
        )

    with pytest.raises(RetryBudgetExhausted) as raised:
        run_in_transaction(operation, policy=policy)

    assert len(attempts) == 4
    assert len(sleeper.delays) == 3
    assert isinstance(raised.value.__cause__, IntegrityError)
    assert LIBRARY_EVENT_SEQUENCE_CONSTRAINT in str(raised.value.__cause__)


@pytest.mark.django_db(transaction=True)
def test_a_real_deadlock_is_recognised_and_the_victim_retries():
    """Deadlock arrives as django.db.OperationalError wrapping psycopg's
    DeadlockDetected -- a different exception family than the collision above,
    reaching the same classifier."""
    first = Platform.objects.create(name="deadlock-a")
    second = Platform.objects.create(name="deadlock-b")

    #: A barrier, not an Event with a timeout: if the two threads fail to meet,
    #: this raises BrokenBarrierError into the thread and the test reports it,
    #: where a lapsed Event would let both run serially and fail the retry
    #: assertion with nothing explaining why.
    both_near_locked = Barrier(2, timeout=10)
    results: list[str] = []
    retried: list[float] = []
    errors: list[BaseException] = []

    def run(near: uuid.UUID, far: uuid.UUID) -> None:
        close_old_connections()
        first_pass = True

        def operation() -> str:
            nonlocal first_pass
            Platform.objects.select_for_update().get(pk=near)
            if first_pass:
                #: Only the opening attempt rendezvouses. The victim's retry
                #: runs after the winner committed, with nobody left to meet --
                #: waiting again would break the barrier on a timeout.
                first_pass = False
                both_near_locked.wait()
            Platform.objects.select_for_update().get(pk=far)
            return "recorded"

        policy = RetryPolicy(sleep=retried.append, random=Random(0))
        try:
            results.append(run_in_transaction(operation, policy=policy))
        except BaseException as error:  # noqa: BLE001 - return thread failures
            errors.append(error)
        finally:
            close_old_connections()

    forward = Thread(target=run, args=(first.pk, second.pk), name="deadlock-forward")
    backward = Thread(target=run, args=(second.pk, first.pk), name="deadlock-backward")
    forward.start()
    backward.start()
    forward.join(timeout=30)
    backward.join(timeout=30)

    assert not errors, errors
    #: A live thread still holds row locks, and this test class TRUNCATEs at
    #: teardown -- asserting here fails the test instead of hanging the worker.
    assert not forward.is_alive()
    assert not backward.is_alive()

    #: PostgreSQL kills exactly one; the runner gives it back.
    assert results == ["recorded", "recorded"]
    assert len(retried) >= 1


@pytest.mark.django_db(transaction=True)
def test_a_rolled_back_attempt_leaves_no_record_for_the_retry_to_replay(
    owned_library,
):
    """The attempt's events and its idempotency record share one transaction.
    If only the record survived a rollback, the retry would replay a range whose
    events no longer exist -- a command silently lost."""
    policy, sleeper = recording_policy()
    attempts = []

    def operation():
        attempts.append(len(attempts))
        result = idempotent_append(
            owned_library,
            idempotency_key="shared-key",
            command_input={"note": "one action"},
            build=lambda _stream: [one_event()],
            actor=None,
            correlation_id=uuid.uuid7(),
        )
        #: After the write, so the first attempt has something to roll back.
        if len(attempts) == 1:
            raise wrapped(OperationalError, "40001")
        return result

    result = run_in_transaction(operation, policy=policy)

    assert len(attempts) == 2
    assert len(sleeper.delays) == 1
    #: An AppendResult, not a ReplayedAppend: the second attempt found no
    #: record, because the first attempt's rolled back with its events.
    assert isinstance(result, AppendResult)
    assert (result.first_sequence, result.last_sequence) == (1, 1)
    #: Read after the runner returned, on a committed connection: this is the
    #: only assertion in the suite that the happy path commits at all.
    assert LibraryEvent.objects.filter(library=owned_library).count() == 1
    assert (
        LibraryIdempotencyRecord.objects.filter(
            library=owned_library, idempotency_key="shared-key"
        ).count()
        == 1
    )
