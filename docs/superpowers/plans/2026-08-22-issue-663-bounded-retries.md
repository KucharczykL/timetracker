# Bounded conflict and serialization retries — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a command's transaction so that PostgreSQL killing it for a
recoverable reason costs a retry rather than the user's write, and so that an
exhausted budget arrives as a typed conflict instead of a 500.

**Architecture:** One generic runner, `run_in_transaction(operation)`, opens the
transaction it retries and refuses to nest. A SQLSTATE classifier decides what is
retryable — serialization failure, deadlock, and a `(stream, sequence)` collision
matched by constraint name, nothing else. Both conflict types share a
`CommandConflict` base so #664 can catch one thing or two.

**Tech Stack:** Django 6 / PostgreSQL 18 / psycopg 3 / pytest-django / Python 3.14.

**Spec:** [2026-08-22-issue-663-bounded-retries-design.md](../specs/2026-08-22-issue-663-bounded-retries-design.md)

## Global Constraints

- Python 3.14 only. PEP 695 syntax (`type X = ...`, `def f[T](...)`) is available and used.
- Everything runs through `make`. Never `uv run pytest` directly. Focused runs: `make test ARGS="tests/test_event_retry.py -k budget -x"`.
- `PYTEST_WORKERS=0` when debugging a threaded failure — parallel output interleaves and `-x` stops only the worker that hit it.
- Name variables with complete words: `error` not `e`, `constraint_name` not `name`.
- Comments explain non-obvious intent only. No issue or PR numbers in code comments (they belong in this plan and the spec).
- This issue adds **no migration and no model field**. `make check`'s `check-migrations` leg proves it.
- Every new module lives in `games/events/`, which #661 made a package.
- Verification gate is the full `make check`, including `e2e/`. `make check-fast` is for iterating only.

## File Structure

| File | Responsibility |
| --- | --- |
| `games/events/conflicts.py` | **Create.** `CommandConflict` and nothing else, so `idempotency.py` and `retry.py` can both import it without a cycle. |
| `games/events/retry.py` | **Create.** `RetryPolicy`, `is_retryable`, `run_in_transaction`, `RetryBudgetExhausted`, `NestedTransactionNotSupported`. |
| `games/events/idempotency.py` | **Modify.** Re-parent `IdempotencyKeyMismatch` onto `CommandConflict`. |
| `games/models.py` | **Modify.** Hoist the sequence constraint's name into a module constant referenced by both the model and `retry.py`. |
| `tests/test_event_retry.py` | **Create.** Everything about classification, backoff, refusal, real-driver evidence, and composition with idempotency. |
| `tests/test_event_idempotency.py` | **Modify.** One assertion pinning the new base class. |

---

### Task 1: The shared conflict base

**Files:**
- Create: `games/events/conflicts.py`
- Modify: `games/events/idempotency.py:39-45`
- Test: `tests/test_event_idempotency.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `games.events.conflicts.CommandConflict`, the base every later task raises or catches. `IdempotencyKeyMismatch` becomes a subclass of it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_event_idempotency.py`. It needs no database, but the file
carries a module-level `pytestmark = pytest.mark.django_db`, which is fine.

```python
def test_a_key_mismatch_is_a_command_conflict():
    #: #664 catches one base for "another command was in the way" and may
    #: narrow to the leaves for two different messages.
    assert issubclass(IdempotencyKeyMismatch, CommandConflict)
```

Add `from games.events.conflicts import CommandConflict` to the file's imports,
beside the existing `from games.events.idempotency import (...)` block.

- [ ] **Step 2: Run test to verify it fails**

Run: `make test ARGS="tests/test_event_idempotency.py -k command_conflict -x"`

Expected: collection error — `ModuleNotFoundError: No module named 'games.events.conflicts'`.

- [ ] **Step 3: Create the module**

`games/events/conflicts.py`:

```python
"""The one base for command failures a person can be shown and asked to act on.

It lives alone here so `idempotency` can raise a subclass while `retry` raises
another, without either module importing the other.
"""


class CommandConflict(Exception):
    """A command did not run because another one was in the way.

    The leaves disagree about what to do next: an exhausted retry budget means
    trying again may work, a reused key over different input means it never
    will.
    """
```

- [ ] **Step 4: Re-parent the mismatch**

In `games/events/idempotency.py`, add to the imports:

```python
from games.events.conflicts import CommandConflict
```

and change the class:

```python
class IdempotencyKeyMismatch(CommandConflict):
    """Raised when a key already belongs to a command with different input.

    Not a ValueError: `LockedStream.append` raises that for an empty event
    sequence, and a conflict must become a visible retry prompt while that
    programming error surfaces as the bug it is.
    """
```

Note the docstring drops the `#663` reference (that issue is now this code) but
keeps the reasoning, per the comment-style constraint.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_event_idempotency.py -x"`

Expected: PASS, all of #662's existing tests included — nothing there catches
`IdempotencyKeyMismatch` via `ValueError`, so widening its ancestry breaks none
of them.

- [ ] **Step 6: Commit**

```bash
git add games/events/conflicts.py games/events/idempotency.py tests/test_event_idempotency.py
git commit -m "feat: give command conflicts one base to be caught by"
```

---

### Task 2: One symbol for the sequence constraint name

**Files:**
- Modify: `games/models.py:1362-1372` (the `LibraryEvent.Meta.constraints` tuple)
- Test: none of its own — `make check-migrations` is the assertion.

**Interfaces:**
- Consumes: nothing.
- Produces: `games.models.LIBRARY_EVENT_SEQUENCE_CONSTRAINT: str`, imported by Task 3's classifier.

**Gotcha:** `makemigrations` serializes the constant's *value*, not its name, so
this emits no migration. If a migration does appear, the constant's value does
not match the literal it replaced — fix the value, delete the migration.

- [ ] **Step 1: Add the constant**

In `games/models.py`, immediately above `class LibraryEvent(models.Model):`:

```python
#: Named here rather than inline so the retry classifier, which must recognise
#: this collision by name, cannot drift from the constraint it matches.
LIBRARY_EVENT_SEQUENCE_CONSTRAINT = "unique_library_event_stream_sequence"
```

- [ ] **Step 2: Reference it from the constraint**

Inside `LibraryEvent.Meta.constraints`, change the first entry:

```python
            models.UniqueConstraint(
                fields=("stream", "sequence"),
                name=LIBRARY_EVENT_SEQUENCE_CONSTRAINT,
            ),
```

- [ ] **Step 3: Prove no migration was produced**

Run: `make check-migrations`

Expected: exits 0 with `No changes detected`. If it exits non-zero, the value
differs from the original literal.

- [ ] **Step 4: Commit**

```bash
git add games/models.py
git commit -m "refactor: name the event sequence constraint once"
```

---

### Task 3: Classification and backoff

**Files:**
- Create: `games/events/retry.py`
- Test: `tests/test_event_retry.py`

**Interfaces:**
- Consumes: `CommandConflict` (Task 1), `LIBRARY_EVENT_SEQUENCE_CONSTRAINT` (Task 2).
- Produces:
  - `RETRYABLE_SQLSTATES: frozenset[str]`
  - `is_retryable(error: Exception) -> bool`
  - `RetryPolicy` — frozen dataclass with `retries: int = 3`, `base_delay: float = 0.025`, `max_delay: float = 0.200`, `sleep: Callable[[float], None] = time.sleep`, `random: Random`, and a method `delay_for(attempt: int) -> float`
  - `DEFAULT_RETRY_POLICY: RetryPolicy`
  - `RetryBudgetExhausted(CommandConflict)` with an `attempts: int` attribute
  - `NestedTransactionNotSupported(RuntimeError)`

**Gotcha:** these tests must not touch the database and must not carry
`django_db`. Everything here is a pure function over an exception object.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_event_retry.py`:

```python
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


@pytest.mark.parametrize(
    "error",
    [
        wrapped(OperationalError, "40001"),
        wrapped(OperationalError, "40P01"),
        wrapped(IntegrityError, "23505", LIBRARY_EVENT_SEQUENCE_CONSTRAINT),
    ],
)
def test_the_charters_three_failures_are_retryable(error):
    assert is_retryable(error) is True


@pytest.mark.parametrize(
    "error",
    [
        #: #662's record collision: the head lock failed to serialize two
        #: same-key commands, which is a bug and must stay visible.
        wrapped(IntegrityError, "23505", "unique_library_idempotency_key"),
        wrapped(IntegrityError, "23505", None),
        wrapped(IntegrityError, "23503"),
        wrapped(OperationalError, "57014"),
        ValueError("not a database failure at all"),
    ],
)
def test_everything_else_is_terminal(error):
    assert is_retryable(error) is False


def test_an_error_with_no_driver_cause_is_terminal():
    assert is_retryable(IntegrityError("hand-rolled, no cause")) is False


def test_the_default_budget_is_the_charters_three():
    assert DEFAULT_RETRY_POLICY.retries == 3


def test_each_delay_stays_inside_a_bound_that_doubles():
    policy = RetryPolicy(random=Random(0))
    bounds = [0.025, 0.050, 0.100]
    for attempt, bound in enumerate(bounds):
        #: Sampled repeatedly: one draw could sit inside the wrong bound.
        draws = [policy.delay_for(attempt) for _ in range(200)]
        assert min(draws) >= 0.0
        assert max(draws) <= bound


def test_the_bound_stops_growing_at_the_cap():
    policy = RetryPolicy(retries=10, random=Random(0))
    assert max(policy.delay_for(9) for _ in range(200)) <= DEFAULT_RETRY_POLICY.max_delay


def test_a_policy_carries_its_own_randomness():
    #: Two policies seeded alike produce the same sequence, so a test asserting
    #: on delays is reproducible without patching the stdlib random module.
    first = RetryPolicy(random=Random(7))
    second = RetryPolicy(random=Random(7))
    assert first.delay_for(0) == second.delay_for(0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_event_retry.py -x"`

Expected: collection error — `ModuleNotFoundError: No module named 'games.events.retry'`.

- [ ] **Step 3: Write the module**

Create `games/events/retry.py`:

```python
"""Bounded retries for the failures PostgreSQL resolves by killing a
transaction.

The transaction is opened here, because a killed transaction cannot be repaired
from inside itself.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from random import Random

from django.db import IntegrityError, OperationalError, router, transaction

from games.events.conflicts import CommandConflict
from games.models import LIBRARY_EVENT_SEQUENCE_CONSTRAINT, LibraryEvent

logger = logging.getLogger("games")

#: Serialization failure and deadlock. Both mean the command may still succeed;
#: neither says anything about the command being wrong.
RETRYABLE_SQLSTATES = frozenset({"40001", "40P01"})

UNIQUE_VIOLATION = "23505"


class NestedTransactionNotSupported(RuntimeError):
    """Raised when a retry is asked for beneath someone else's transaction,
    where a rollback cannot undo what that transaction already did."""


class RetryBudgetExhausted(CommandConflict):
    """Every attempt lost to a concurrent write. Nothing was recorded."""

    def __init__(self, attempts: int) -> None:
        super().__init__(
            f"The command lost to a concurrent write on all {attempts} "
            "attempts. Nothing was recorded; try again."
        )
        self.attempts = attempts


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many times, how long between, and who does the waiting.

    `sleep` and `random` are fields so a test can assert on the delays the code
    actually produces instead of on patches of the standard library.
    """

    retries: int = 3
    base_delay: float = 0.025
    max_delay: float = 0.200
    sleep: Callable[[float], None] = time.sleep
    random: Random = field(default_factory=Random)

    def delay_for(self, attempt: int) -> float:
        """Full jitter: uniform over a bound that doubles until it caps."""
        bound = min(self.max_delay, self.base_delay * 2**attempt)
        return self.random.uniform(0, bound)


DEFAULT_RETRY_POLICY = RetryPolicy()


def _sqlstate(error: Exception) -> str | None:
    #: Django re-raises driver errors `from` the original, so the psycopg
    #: exception carrying sqlstate and diag is always the cause.
    return getattr(error.__cause__, "sqlstate", None)


def _constraint_name(error: Exception) -> str | None:
    diagnostic = getattr(error.__cause__, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def is_retryable(error: Exception) -> bool:
    """Whether running the same transaction again could succeed.

    A unique violation qualifies only on the event sequence constraint. Any
    other one is an application bug, and retrying it four times would spend the
    budget to tell the user to retry something that can never work.
    """
    sqlstate = _sqlstate(error)
    if sqlstate in RETRYABLE_SQLSTATES:
        return True
    if sqlstate == UNIQUE_VIOLATION:
        return _constraint_name(error) == LIBRARY_EVENT_SEQUENCE_CONSTRAINT
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test ARGS="tests/test_event_retry.py -x"`

Expected: PASS (12 tests, counting the parametrized cases). Ignore that `LibraryEvent`, `IntegrityError`,
`OperationalError`, `router`, and `transaction` are imported but unused so far —
Task 4 uses every one. If `make lint` is run now it will flag them; that is
expected and resolved by the next task.

- [ ] **Step 5: Commit**

```bash
git add games/events/retry.py tests/test_event_retry.py
git commit -m "feat: classify which database failures a retry could fix"
```

---

### Task 4: The runner

**Files:**
- Modify: `games/events/retry.py`
- Test: `tests/test_event_retry.py`

**Interfaces:**
- Consumes: everything from Task 3.
- Produces: `run_in_transaction[T](operation: Callable[[], T], *, policy: RetryPolicy = DEFAULT_RETRY_POLICY) -> T`.

**Gotchas:**
- These tests need `@pytest.mark.django_db(transaction=True)`. The runner
  refuses to run inside the transaction plain `django_db` wraps each test in;
  that refusal is the design, not an obstacle to route around.
- `transaction.atomic()` with no argument opens on `DEFAULT_DB_ALIAS`, while
  `lock_stream` checks `router.db_for_write(LibraryEvent)`. Resolve the alias
  once and pass it to both, so the connection checked is the connection used.
- Use `while True` rather than `for attempt in range(...)`: the loop always
  returns or raises, but a `for` leaves mypy demanding an unreachable tail.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_event_retry.py`. Add these imports at the top of the file:

```python
from django.db import transaction

from games.events.retry import (
    NestedTransactionNotSupported,
    RetryBudgetExhausted,
    run_in_transaction,
)
```

```python
class RecordingSleep:
    """Stands in for time.sleep, so the suite never actually waits."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def recording_policy(**overrides) -> tuple[RetryPolicy, RecordingSleep]:
    sleeper = RecordingSleep()
    return RetryPolicy(sleep=sleeper, random=Random(0), **overrides), sleeper


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
    assert caplog.records == []


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
    assert len(caplog.records) == 3
    assert "40P01" in caplog.records[0].getMessage()
```

Add `from games.events.idempotency import IdempotencyKeyMismatch` to the file's
imports.

**Gotcha — do not reach for a bare `caplog`.** The `games` logger sets
`propagate=False` in `timetracker/settings.py`, so caplog's root handler never
sees its records and a bare `caplog.at_level(...)` silently captures nothing,
making the assertion above pass or fail for the wrong reason. `tests/conftest.py`
already provides the `capture_games_logger` fixture for exactly this; it attaches
caplog's handler to the `games` logger for the block. Use it as written.

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test ARGS="tests/test_event_retry.py -x"`

Expected: `ImportError: cannot import name 'run_in_transaction'`.

- [ ] **Step 3: Write the runner**

Append to `games/events/retry.py`:

```python
def run_in_transaction[T](
    operation: Callable[[], T],
    *,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> T:
    """Run `operation` in a transaction, re-running it when PostgreSQL kills
    the transaction for a reason another attempt could clear.

    `operation` may run up to `policy.retries + 1` times, so it must be
    re-runnable from scratch and must have no effects outside the database: no
    mail, no file writes, no outbound calls. It must not rely on in-memory model
    state surviving a rollback either -- Django leaves `pk` set on an object
    whose insert was rolled back. Callbacks registered with
    `transaction.on_commit` are safe: a failed attempt discards its own.
    """
    #: One alias for the check and the transaction. Unqualified atomic() would
    #: open on the default connection while lock_stream inspects the routed one.
    alias = router.db_for_write(LibraryEvent)
    if transaction.get_connection(alias).in_atomic_block:
        raise NestedTransactionNotSupported(
            "run_in_transaction opens the transaction it retries: rolling back "
            "here could not undo what an enclosing transaction already did, so "
            "its retries would be weaker than they look."
        )

    attempt = 0
    while True:
        try:
            with transaction.atomic(using=alias):
                return operation()
        except (IntegrityError, OperationalError) as error:
            #: A CommandConflict is neither of these, so a key mismatch leaves
            #: by the ordinary route without a case of its own.
            if not is_retryable(error):
                raise
            if attempt == policy.retries:
                raise RetryBudgetExhausted(attempt + 1) from error
            constraint_name = _constraint_name(error)
            logger.warning(
                "Retrying a command after SQLSTATE %s%s (attempt %d of %d).",
                _sqlstate(error),
                f" on {constraint_name}" if constraint_name else "",
                attempt + 1,
                policy.retries + 1,
            )
            policy.sleep(policy.delay_for(attempt))
            attempt += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test ARGS="tests/test_event_retry.py -x"`

Expected: PASS (19 tests).

- [ ] **Step 5: Check types and lint**

Run: `make typecheck && make lint`

Expected: both clean. The unused imports flagged after Task 3 are all consumed now.

- [ ] **Step 6: Commit**

```bash
git add games/events/retry.py tests/test_event_retry.py
git commit -m "feat: retry a command's transaction within a bounded budget"
```

---

### Task 5: Evidence against the real driver

**Files:**
- Test: `tests/test_event_retry.py`

**Interfaces:**
- Consumes: `run_in_transaction`, `RetryBudgetExhausted` (Task 4); `lock_stream`, `NewEvent` from `games.events.append`.
- Produces: nothing importable. This task exists because Tasks 3 and 4 proved the
  classifier only against exceptions the tests themselves built — a wrong
  attribute path (`__cause__.sqlstate`, `__cause__.diag.constraint_name`) would
  be reproduced identically by the fake and agree with itself.

**Gotchas:**
- Threads need `close_old_connections()` on entry and exit; see
  `tests/test_event_append.py` for the established shape.
- The deadlock test costs roughly one `deadlock_timeout` (~1 s). That is the
  price of the evidence.
- Lock two rows that are *not* the stream head — the charter's wording is
  "deadlocks involving non-stream rows", and the head lock is single-row so it
  cannot deadlock against itself.
- `owned_library` is the existing fixture used throughout `tests/test_event_*`.

- [ ] **Step 1: Write the real sequence-collision test**

Append to `tests/test_event_retry.py`, adding these imports:

```python
import uuid
from threading import Event, Thread

from django.db import close_old_connections
from django.utils import timezone

from games.events.append import NewEvent, lock_stream
from games.models import LibraryEvent, Platform
```

```python
def one_event() -> NewEvent:
    return NewEvent(
        event_type="probe.recorded",
        aggregate_type="probe",
        aggregate_id=uuid.uuid4(),
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
            correlation_id=uuid.uuid4(),
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
            aggregate_id=uuid.uuid4(),
            payload={},
            recorded_at=timezone.now(),
            effective_time=None,
            actor=None,
            correlation_id=uuid.uuid4(),
            idempotency_key="collides",
        )

    with pytest.raises(RetryBudgetExhausted) as raised:
        run_in_transaction(operation, policy=policy)

    assert len(attempts) == 4
    assert len(sleeper.delays) == 3
    assert isinstance(raised.value.__cause__, IntegrityError)
    assert LIBRARY_EVENT_SEQUENCE_CONSTRAINT in str(raised.value.__cause__)
```

- [ ] **Step 2: Run it**

Run: `make test ARGS="tests/test_event_retry.py -k real_sequence_collision -x" PYTEST_WORKERS=0`

Expected: PASS. **If it fails with the operation running once instead of four
times**, `is_retryable` is not seeing the constraint name — inspect
`error.__cause__.diag.constraint_name` in a debugger before changing the test.
That failure is precisely what this task exists to catch.

- [ ] **Step 3: Write the real deadlock test**

```python
@pytest.mark.django_db(transaction=True)
def test_a_real_deadlock_is_recognised_and_the_victim_retries():
    """Deadlock arrives as django.db.OperationalError wrapping psycopg's
    DeadlockDetected -- a different exception family than the collision above,
    reaching the same classifier."""
    first = Platform.objects.create(name="deadlock-a")
    second = Platform.objects.create(name="deadlock-b")

    both_hold_one = Event()
    holders = 0
    results: list[str] = []
    retried: list[float] = []

    def lock_in_order(near: int, far: int) -> str:
        nonlocal holders

        def operation() -> str:
            nonlocal holders
            Platform.objects.select_for_update().get(pk=near)
            holders += 1
            if holders >= 2:
                both_hold_one.set()
            #: Only the first pass waits; a retry runs after the winner
            #: committed and must not block on an event that already fired.
            both_hold_one.wait(timeout=5)
            Platform.objects.select_for_update().get(pk=far)
            return "recorded"

        policy = RetryPolicy(sleep=retried.append, random=Random(0))
        close_old_connections()
        try:
            return run_in_transaction(operation, policy=policy)
        finally:
            close_old_connections()

    def run(near: int, far: int) -> None:
        results.append(lock_in_order(near, far))

    forward = Thread(target=run, args=(first.pk, second.pk), name="deadlock-forward")
    backward = Thread(target=run, args=(second.pk, first.pk), name="deadlock-backward")
    forward.start()
    backward.start()
    forward.join(timeout=30)
    backward.join(timeout=30)

    #: PostgreSQL kills exactly one; the runner gives it back.
    assert results == ["recorded", "recorded"]
    assert len(retried) >= 1
```

- [ ] **Step 4: Run it**

Run: `make test ARGS="tests/test_event_retry.py -k real_deadlock -x" PYTEST_WORKERS=0`

Expected: PASS in roughly 1–2 seconds (one `deadlock_timeout`).

**If it hangs to the 30 s join timeout**, the two threads are not actually
contending — confirm both got past `select_for_update` on their near row before
either reached its far row. **If it fails with an unretried
`OperationalError`**, psycopg's `DeadlockDetected` is not reaching
`is_retryable` with SQLSTATE `40P01`; print `error.__cause__.sqlstate` before
touching the classifier.

- [ ] **Step 5: Commit**

```bash
git add tests/test_event_retry.py
git commit -m "test: prove the classifier against real driver failures"
```

---

### Task 6: Retry and idempotency compose into "already done"

**Files:**
- Test: `tests/test_event_retry.py`

**Interfaces:**
- Consumes: `run_in_transaction` (Task 4), `idempotent_append` and
  `ReplayedAppend` from `games.events.idempotency`.
- Produces: nothing importable. This pins the property the pair of issues exists
  to produce, which neither module states on its own.

**Gotcha:** a threaded test must not assert on the ORM until the server-rendered
write has committed; here both threads are joined first, so the reads happen
after both transactions ended.

- [ ] **Step 1: Write the test**

Append to `tests/test_event_retry.py`, adding
`from games.events.idempotency import ReplayedAppend, idempotent_append` to the
imports:

```python
@pytest.mark.django_db(transaction=True)
def test_a_retried_command_replays_the_winners_range(owned_library):
    """A loser that retries finds the winner's record and returns its range,
    rather than appending the same human action twice."""
    started = Event()
    outcomes: list[object] = []

    def issue() -> None:
        close_old_connections()
        try:
            started.wait(timeout=5)
            outcomes.append(
                run_in_transaction(
                    lambda: idempotent_append(
                        owned_library,
                        idempotency_key="shared-key",
                        command_input={"note": "one action"},
                        build=lambda _stream: [one_event()],
                        actor=None,
                        correlation_id=uuid.uuid4(),
                    )
                )
            )
        finally:
            close_old_connections()

    threads = [Thread(target=issue, name=f"issuer-{index}") for index in range(2)]
    for thread in threads:
        thread.start()
    started.set()
    for thread in threads:
        thread.join(timeout=30)

    assert len(outcomes) == 2
    replays = [result for result in outcomes if isinstance(result, ReplayedAppend)]
    assert len(replays) == 1
    #: One human action, one event -- not one per issuer.
    assert LibraryEvent.objects.filter(library=owned_library).count() == 1
    ranges = {(result.first_sequence, result.last_sequence) for result in outcomes}
    assert ranges == {(1, 1)}
```

- [ ] **Step 2: Run it**

Run: `make test ARGS="tests/test_event_retry.py -k replays_the_winners -x" PYTEST_WORKERS=0`

Expected: PASS. **If both outcomes are `AppendResult`**, the two threads never
overlapped — the losing thread ran entirely after the winner committed, which is
still a correct replay but proves nothing about contention; check that
`started.wait` is releasing both threads together.

- [ ] **Step 3: Commit**

```bash
git add tests/test_event_retry.py
git commit -m "test: prove a retried duplicate replays instead of appending"
```

---

### Task 7: Amend #661's and #662's specs, and gate

**Files:**
- Modify: `docs/superpowers/specs/2026-08-22-issue-662-command-idempotency-design.md`
- Modify: `docs/superpowers/specs/2026-08-21-issue-661-stream-sequence-allocation-design.md`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. This is the propagation step — a slice that changes a
  sibling's stated contract amends that sibling's spec rather than leaving it
  describing code that no longer exists.

Both amendments use the blockquote form #661's spec already established for
being superseded (see its `append_events` note, added by #662):

```markdown
> **Amended by [#663](https://github.com/KucharczykL/timetracker/issues/663).**
> …
```

- [ ] **Step 1: Amend #662's spec**

In `2026-08-22-issue-662-command-idempotency-design.md`, the section
"`IdempotencyKeyMismatch` is its own exception, and it spares the transaction"
opens with "It derives from `Exception` directly, not `ValueError`." Add a
blockquote after that paragraph recording that #663 re-parented it onto
`CommandConflict` so a dispatcher can catch one base for both conflicts, and
that the original reasoning is undisturbed — the new base is not a `ValueError`
either, so an empty-build programming error still surfaces as a bug.

Also update that spec's ownership-boundary table row "Retrying and classifying
`IdempotencyKeyMismatch` into a visible conflict | #663" — it is now delivered,
not pending. Leave the row; append "(delivered)" to the owner cell.

- [ ] **Step 2: Amend #661's spec**

`2026-08-21-issue-661-stream-sequence-allocation-design.md:95` has the section
"The caller owns the transaction", which names `TransactionRequired` and leaves
the owner unnamed because none existed. Add a blockquote after that section
recording that #663 introduced `run_in_transaction` as that owner, and that it
raises the mirror exception `NestedTransactionNotSupported` when a transaction
is already open — so the two functions now bracket the valid state from both
sides.

- [ ] **Step 3: Run the full gate**

Run: `make check`

Expected: green, including `e2e/` and the `check-migrations` leg proving Task 2
emitted no migration. This is the verification gate; a hand-picked subset is not
a substitute.

- [ ] **Step 4: Confirm the identity audit is untouched**

Run: `make audit-uuid-identity`

Expected: passes. No table was added, so no registry entry is needed.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/
git commit -m "docs: record the conflict base in the idempotency spec"
```

---

## Follow-up issues to file

None. Every deferral in the spec is already owned by an existing issue: response
mapping and the dispatch boundary by #664, projectors inside the retried
transaction by #665, and `expected_sequence` by #901.
