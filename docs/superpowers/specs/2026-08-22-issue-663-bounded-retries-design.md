# Bounded conflict and serialization retries

Two commands that touch one library can collide in ways PostgreSQL resolves by
killing one of them. The
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
says what happens next: "PostgreSQL serialization failures, deadlocks involving
non-stream rows, and sequence constraint collisions are retried at most three
times with bounded jitter; an exhausted retry returns a visible conflict asking
the user to retry instead of discarding either write."

Nothing implements that today, and nothing can. [#661](https://github.com/KucharczykL/timetracker/issues/661)
made `lock_stream` refuse to run outside an open transaction, and
[#662](https://github.com/KucharczykL/timetracker/issues/662) built on the same
precondition: a transaction the *caller* owns. No caller exists. This issue is
the first thing that owns one, and owning it is what makes retrying possible —
a killed transaction cannot be repaired from inside itself.

## What it is

One function that runs a callable inside a transaction it opens, re-runs the
whole thing when PostgreSQL kills it for a reason retrying can fix, and turns
a spent budget into an exception a person can be shown.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| Mapping a conflict to an HTTP status, a page, or a toast | #664 |
| Command objects, authentication, authorization, dispatch | #664 |
| What a command's canonical input is | #664 |
| Projectors, and running them inside the retried transaction | #665 |
| Optional `expected_sequence` optimistic-concurrency check | #901 |

This issue owns the transaction, the retry budget, the classification of a
PostgreSQL failure as retryable, and the conflict exception hierarchy.

**The visible half stops at the exception.** The charter's "returns a visible
conflict" is delivered here as a typed exception carrying why it failed; nothing
renders it, because there are no commands and no evented views to render it
from. A response handler written now would be dead code shaped against an
imaginary caller, and #664 is a single dispatcher that will want it on itself
rather than as a global handler.

## Preconditions

Everything #661 and #662 established still holds and is not restated: READ
COMMITTED, the head lock held until commit, the record checked under that lock.

`ATOMIC_REQUESTS` is unset, so no request currently arrives inside a
transaction. That fact is load-bearing for the next section.

## Design

### The runner refuses to nest

`run_in_transaction` raises `NestedTransactionNotSupported` when the connection
is already in an atomic block. It is the exact mirror of #661's
`TransactionRequired`, and for the same reason: a function whose contract
depends on transaction state should assert that state rather than silently
deliver a weaker version of itself.

The weaker version is real and was considered. `transaction.atomic()` nests as a
savepoint; under READ COMMITTED a `ROLLBACK TO SAVEPOINT` recovers the
connection, each retried statement takes a fresh snapshot, and PostgreSQL
releases the locks acquired after the savepoint — including the head lock, since
`lock_stream` runs inside. So a nested retry would genuinely retry. What it
would *not* do is roll back anything the outer block did before entering, or
release the locks that outer work already holds. A deadlock caused by that outer
work re-deadlocks on every attempt and spends the budget for nothing, and the
caller cannot tell from the outside which kind they got.

The cost of refusing is paid in tests: `run_in_transaction` cannot be called
under pytest-django's ordinary `django_db`, which wraps each test in a
transaction, so its tests and #664's command tests need
`django_db(transaction=True)`. Nothing already written breaks — #661's and
#662's tests open their own `atomic()` and never touch the runner. The tax is
worth paying rather than avoiding: a command test running inside a wrapping
savepoint would be asserting retry behaviour it is not actually exercising, so
the cheaper test is also the one that proves less.

The consequence for deployment is that enabling `ATOMIC_REQUESTS` would disable
retries entirely. Refusing makes that a startup-visible crash on the first
command instead of a silent regression to zero retries.

**The connection checked and the connection used must be the same one.**
`transaction.atomic()` with no argument opens on `DEFAULT_DB_ALIAS`, while
`lock_stream` checks `router.db_for_write(LibraryEvent)`. Those are the same
alias in this project and the runner still resolves the alias explicitly and
passes it to `atomic(using=...)`, because a router that ever separates them
would otherwise produce a runner holding a transaction on one connection while
the lock it exists to protect is taken on another.

### The runner is generic, not a retrying `idempotent_append`

`run_in_transaction(operation)` takes a zero-argument callable and returns
whatever it returns. The alternative — a function absorbing `idempotent_append`'s
whole signature so that appending without retry protection becomes impossible —
is #662's own callback argument applied one level up, and it was rejected on two
grounds.

The retried unit is the *command transaction*, not the append. The charter
names "deadlocks involving non-stream rows" explicitly, and those rows are
projections and whatever else a command touches. An absorbing runner has no
place to put them until it grows a second callback, which pre-decides part of
#665's shape from outside #665.

And #662's omit-a-step worry does not transfer. It was an argument about N
hand-written commands each able to forget a call. #664 delivers a single
dispatch boundary, so "the runner is not used" is a one-place mistake with a
one-place test, not a per-command hazard.

A generic runner also serves #666's replay and #671's backfill, which #662
expects to reach the raw primitives directly; they get bounded retries for free
rather than needing a second mechanism.

### Retryable is a closed set, matched by SQLSTATE

`is_retryable` reads `error.__cause__.sqlstate` — Django re-raises driver errors
`from` the original, so the psycopg exception with its `sqlstate` and `diag` is
always the cause.

| SQLSTATE | Condition | Retry |
| --- | --- | --- |
| `40001` | serialization failure | always |
| `40P01` | deadlock detected | always |
| `23505` | unique violation | only on `unique_library_event_stream_sequence` |
| anything else | | never |

The narrowing on `23505` is the whole point of matching by constraint name. A
broad "retry any `IntegrityError`" would take a genuine application bug — a
duplicate slug, a double-inserted projection row — run it four times, and hand
the user a conflict telling them to retry something that will never succeed. The
constraint name is what separates "two writers raced for a sequence" from "this
code is wrong".

**The idempotency record's `unique_library_idempotency_key` violation stays
terminal.** A retry would re-enter, find the committed record and return
`ReplayedAppend`, turning an inexplicable 500 into the right answer — which is
exactly the objection. #662 established that this violation can only occur if
the head lock failed to serialize two same-key commands, meaning a bug or an
out-of-band writer, and that "the constraint names that better than a wrapper
would". Smoothing it into a conflict would delete the only signal that the
locking discipline is broken. Keeping it terminal also leaves the retryable set
exactly the charter's three.

**Sequence-collision retry is defence-in-depth.** `LockedStream.append` computes
sequences under the head lock, so under the discipline this codebase enforces
the collision is unreachable; the charter calls the unique constraint "the final
guard". A real one therefore means a writer outside the lock, and retrying is
the right response because the next attempt reads the advanced head. It is
listed among the foreclosures that this is not a substitute for the lock.

### The constraint name is one symbol, referenced twice

`LIBRARY_EVENT_SEQUENCE_CONSTRAINT` moves into `games/models.py` beside the
model and is passed to `UniqueConstraint(name=...)`; `retry.py` imports the same
symbol. A rename then changes both sides at once, by construction, with no
pinning test to keep in sync and nothing to forget.

Deriving the name at call time from `LibraryEvent._meta.constraints` by matching
the field tuple was the alternative. It removes the literal but not the
brittleness — it just encodes the field names instead of the constraint name —
and it fails *opaquely*: the lookup returns nothing, the constraint stops
matching, and sequence collisions quietly cease to be retryable with no error
anywhere.

`makemigrations` serializes the constant's value, not its symbol, so the hoist
produces no migration and leaves the existing one and the database untouched.
**This issue adds no migration and no table.**

### Two conflicts, one base, no wrapping

```
CommandConflict
├── IdempotencyKeyMismatch   (#662, re-parented)
└── RetryBudgetExhausted     (this issue)
```

`CommandConflict` lives in `games/events/conflicts.py`, a module holding nothing
else, so `idempotency.py` can import it while `retry.py` imports both without a
cycle.

The two mean opposite things to a person. An exhausted budget means *the system
was busy; try again*. A key mismatch means *this key already recorded a
different command; retrying will never work*. #664 can catch the base for one
409 or the leaves for two messages, and the type system carries the distinction
either way.

Re-parenting rather than wrapping matters because `idempotent_append` is public
and #666 and #671 are expected to call it directly. Catching the mismatch in the
runner and re-raising it as a runner-owned type would give one condition two
names depending on which door the caller came through, with the original
surviving only in `__cause__`. Re-parenting costs one line in a file #662 just
shipped, and #662's stated reason for the current base — not a `ValueError`,
because `append` raises that for an empty event sequence — is undisturbed.

**A mismatch is not retried, and no code says so.** `CommandConflict` is neither
an `OperationalError` nor an `IntegrityError`, so it passes straight through the
runner's `except` clause. The property holds by construction rather than by an
ordering someone can break while editing.

### The policy is data, and the default is the charter

```python
@dataclass(frozen=True, slots=True)
class RetryPolicy:
    retries: int = 3
    base_delay: float = 0.025
    max_delay: float = 0.200
    sleep: Callable[[float], None] = time.sleep
    random: Random = field(default_factory=Random)
```

Delay before retry `n` (zero-based) is
`random.uniform(0, min(max_delay, base_delay * 2**n))` — bounds of 25 ms, 50 ms,
100 ms, so a command that exhausts its budget adds at most ~175 ms before
failing. `retries = 3` states the charter's "at most three times" directly
rather than as an attempt count the reader has to decrement.

Carrying `sleep` and `random` as fields is what makes the timing contract
testable against values the code actually holds: a test passes a policy whose
`sleep` appends to a list and whose `Random` is seeded, then asserts the number
of delays, that each is inside its bound, and that the bounds double. The
alternative — module constants plus monkeypatched `time.sleep` and
`random.uniform` — asserts the same facts against patches of stdlib internals,
so renaming a private helper breaks the tests and the policy exists nowhere as a
value. The cost of the dataclass is two parameters production will never set.

`DEFAULT_RETRY_POLICY` is a module-level instance, so the common call passes no
policy at all. There is deliberately no `config()` setting: an operator knob for
retry counts is a tuning surface nobody has asked for, and the charter fixes the
number.

### A retry that succeeds is logged

Each retry emits a `WARNING` on the existing `"games"` logger with the attempt
number, the SQLSTATE, and the constraint name where there is one. It cannot name
the library: the runner takes an opaque callable and has no idea which library
the operation touches. That is a real cost of the generic shape chosen above,
and it is the reason the log line is a contention *rate* signal rather than a
per-library diagnostic. Exhaustion adds no separate record:
`RetryBudgetExhausted` carries `attempts` and chains the last failure as
`__cause__`, so the exception is the log entry.

The reason to log the *successful* retries is that they are otherwise
completely invisible — a library under growing contention presents only as
slower commands. The charter requires re-measuring write amplification and the
100 ms command budget every time a projector family is attached, which is
precisely when contention starts climbing, and a silent retry is the signal that
would have said so first. Volume is bounded at three lines per command.

### The operation contract is documented, not enforced

`operation` may run up to four times. It must be re-runnable from scratch, must
have no side effects outside the database (no mail, no file writes, no outbound
HTTP), and must not depend on in-memory model state surviving a rollback —
Django does not reset `pk` after a rolled-back insert, so an object created in a
failed attempt looks saved. `transaction.on_commit` callbacks registered during
a failed attempt are discarded with its rollback, which is the correct behaviour
and worth stating because it is the one side-effect mechanism that *is* safe.

None of this is checkable at runtime. It is stated in the docstring and in this
document because #664 is the caller that has to honour it.

### Retry composes with idempotency into "already done"

The interaction is the charter's "instead of discarding either write" actually
holding, and it falls out of the two mechanisms rather than being built:

1. Two commands carrying one key race; one commits.
2. The loser's transaction dies for a retryable reason.
3. The runner re-runs it. `idempotent_append` takes the head lock, finds the
   now-committed record, and returns `ReplayedAppend`.

The retried command returns the winner's sequence range rather than appending a
second time. This is pinned by a test because it is the property the whole pair
of issues exists to produce, and because it is not obvious from either module
alone.

## API contract

```python
# games/events/conflicts.py
class CommandConflict(Exception): ...


# games/events/retry.py
RETRYABLE_SQLSTATES = frozenset({"40001", "40P01"})


class NestedTransactionNotSupported(RuntimeError): ...


class RetryBudgetExhausted(CommandConflict):
    attempts: int


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    retries: int = 3
    base_delay: float = 0.025
    max_delay: float = 0.200
    sleep: Callable[[float], None] = time.sleep
    random: Random = field(default_factory=Random)


DEFAULT_RETRY_POLICY = RetryPolicy()


def is_retryable(error: Exception) -> bool: ...


def run_in_transaction[T](
    operation: Callable[[], T],
    *,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> T: ...
```

`games/events/` gains two modules; the package has one per issue since #661 made
it a package.

## Where the behaviour is pinned

`tests/test_event_retry.py`, plus one assertion added to
`tests/test_event_idempotency.py` that `IdempotencyKeyMismatch` is a
`CommandConflict`.

**No database.** `is_retryable` over a synthesized `40001`, `40P01`, a `23505`
on the sequence constraint, a `23505` on another constraint, an error with no
`__cause__`, and a plain `ValueError` · the backoff records exactly `retries`
delays, each inside `min(max_delay, base_delay * 2**n)`, with the bound doubling
across attempts under a seeded `Random`.

**`django_db(transaction=True)`** — forced by the refusal, not chosen:

- calling inside an open atomic block raises `NestedTransactionNotSupported`;
- the happy path returns the operation's value and commits it;
- a **real** duplicate-sequence insert (single-threaded: write a `LibraryEvent`
  at a sequence that already exists) retries and then raises
  `RetryBudgetExhausted` carrying `attempts` and chaining the driver error;
- a **real** two-thread deadlock — two rows locked in opposite order — is
  retried and succeeds;
- an idempotency-record unique violation propagates untouched: not retried, no
  delay recorded, no warning logged;
- `IdempotencyKeyMismatch` propagates as a `CommandConflict` without the
  operation being re-run;
- two threads issuing one key against one library: the loser's retry returns
  `ReplayedAppend` and the library holds N events, not 2N.

**Why two of those are real rather than synthesized.** The classifier's whole
job is reading `__cause__.sqlstate` and `__cause__.diag.constraint_name` through
Django's wrapper, and a test built from synthesized exceptions constructs the
fake by the same wrong attribute path it then asserts — it agrees with itself
whatever the driver does. The duplicate-sequence case is free, single-threaded,
and proves the route. The deadlock costs a `deadlock_timeout` (~1 s) and one
threaded test, and buys the other half: that psycopg's `DeadlockDetected` really
does arrive as a `django.db.OperationalError` with the SQLSTATE intact, which is
a different exception family reaching the same code.

`40001` stays synthesized. Provoking a real serialization failure under READ
COMMITTED means switching isolation for one test, which would prove the
classifier against a transaction mode the application never runs in.

## What this shape forecloses

- **Anything finer than whole-transaction retry.** A command cannot retry one
  step; the entire operation re-runs, so every part of it must be re-runnable.
- **Retrying beneath an outer transaction.** Enabling `ATOMIC_REQUESTS`, or
  calling a command from inside another command's transaction, raises rather
  than degrading — deliberately, but it is a real constraint on #664 and on any
  future bulk command that wants to wrap several commands.
- **Proven `40001` handling.** That branch is classified by construction and
  tested against a fake; the first real serialization failure in production is
  its first real execution.
- **Sequence collision as a supported path.** Retrying it is defence-in-depth
  behind the head lock, not a licence to append without one.
- **Explaining contention to a user.** `RetryBudgetExhausted` says the system was
  busy and carries an attempt count; it cannot say which other command won.
- **Attributing a retry to a library.** The runner sees only a callable, so its
  warnings count contention without locating it. Naming the library would mean
  giving the runner a library, which is the absorbing shape rejected above.
- **A shared budget.** Each `run_in_transaction` call gets its own three
  retries. A request making several calls can spend the budget several times.
- **Operator tuning.** The policy is a per-call argument with no setting behind
  it, so changing retry behaviour in a deployment means changing code.
- **Side-effecting commands.** Anything that sends, writes, or calls out during
  the transaction is unsafe under retry, and nothing enforces that.

## Verification

`make check` — the full gate including `e2e/`. Its `check-migrations` leg
already runs `makemigrations --check --dry-run`, so a green gate is itself the
proof that the constraint-name hoist emitted no migration; nothing extra needs
running. `make audit-uuid-identity` is unaffected, since no table is added.
