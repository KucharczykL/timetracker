# The optional expected-sequence concurrency check — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a caller that read the library stream at N refuse to proceed if the
head has moved, checked under the lock where the comparison is meaningful.

**Architecture:** Two additions to `games/events/append.py` — a
`StreamSequenceMismatch` conflict and a `LockedStream.require_sequence` method —
plus an optional `expected_sequence` parameter on `append` that calls the method.
Nothing above `LockedStream` changes. No migration, no schema change, no data
change, no new module.

**Spec:** `docs/superpowers/specs/2026-08-25-issue-901-expected-sequence-check-design.md`
— read it before Task 1. It carries the *why*; this plan carries the *what* and
the order.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, pytest + pytest-django.

## Global Constraints

- **Python 3.14 only.** PEP 758's bare `except A, B:` applies **without** a
  binding; a clause needing the error is `except (A, B) as error:`.
- **Drive everything through `make`.** Focused runs:
  `make test ARGS="tests/test_event_append.py -k require_sequence -x"`.
- **`PYTEST_WORKERS=0` for every run touching Task 2.** Thread tests interleave
  their output under xdist and `-x` stops only the worker that hit the failure.
- **Iterate on `make check-fast`; gate on the full `make check`.**
- **Docstrings in `games/events/` are seven words or fewer**, one line. Commit
  `b172180a` cut the whole package to that; a longer one will be cut in review.
- **Comments explain obscure intent only.** No issue or PR references in code.
- **Complete words in identifiers.**
- **This must land before #667**, which is its only planned caller.

---

## File structure

**Modify `games/events/append.py`** — one exception class, one method, one
parameter. `StreamSequenceMismatch` lives here rather than in `conflicts.py`
because `conflicts.py` holds the base alone and each raising module owns its
leaf, the arrangement `idempotency.py` and `retry.py` already follow. Adds one
import: `from games.events.conflicts import CommandConflict`.

**Modify `tests/test_event_append.py`** — all new tests. The module already has
`make_new_event`, `append`, `append_directly`, the `owned_library` fixture from
`tests/conftest.py`, and a two-thread harness at
`test_concurrent_appends_serialize_into_one_contiguous_range`.

**Nothing else is touched.** `idempotency.py`, `dispatch.py`, `retry.py`,
`replay.py`, and `games/models.py` are all unchanged; `is_retryable` needs no new
case.

---

## Task 1: The primitive

**Files:**
- Modify: `games/events/append.py`
- Modify: `tests/test_event_append.py`

**Interfaces:**
- Produces: `StreamSequenceMismatch(CommandConflict)` with keyword-only
  `expected: int` / `actual: int` constructor arguments, exposed as attributes of
  the same names; and `LockedStream.require_sequence(self, expected: int) -> None`.

**Steps:**

- [ ] Write `StreamSequenceMismatch`, formatting a message that names both
      numbers and tells the caller to read the stream again. Follow
      `RetryBudgetExhausted` for shape: format in `__init__`, `super().__init__`
      the message, then assign the attributes.
- [ ] Write `require_sequence` resolving in this order: `expected < 0` raises
      `ValueError` before any query; then read the row's `current_sequence`;
      then `expected > actual` raises `ValueError`; then `expected < actual`
      raises `StreamSequenceMismatch`; otherwise return.
- [ ] The read is
      `LibraryEventStreamHead.objects.values_list("current_sequence", flat=True).get(pk=self._head.pk)`.
      Not `FOR UPDATE` — this transaction already holds the lock. Do not write
      the result back to `self._head`.
- [ ] Write the tests below, run them, confirm green.
- [ ] **Prove the staleness tests bite.** Temporarily replace the query with
      `self._head.current_sequence`, run
      `make test ARGS="tests/test_event_append.py -k stale -x" PYTEST_WORKERS=0`,
      and confirm both fail. Restore the query. This is the red phase; without it
      the two tests pass for free and prove nothing.
- [ ] Commit.

**Tests:**

- [ ] `expected == current_sequence` returns `None`
- [ ] `expected < current_sequence` raises `StreamSequenceMismatch`, and the
      raised value's `expected` and `actual` are both correct
- [ ] `expected > current_sequence` raises `ValueError`, not the mismatch
- [ ] `require_sequence(-1)` against a head at 5 raises `ValueError` — asserts the
      negative branch wins over the `< current_sequence` branch it also satisfies
- [ ] `require_sequence(0)` against a freshly provisioned head returns `None`
- [ ] **stale by double lock**: in one `atomic()`, take `first = lock_stream(...)`,
      take `second = lock_stream(...)`, append through `second`, then
      `first.require_sequence(<the new head value>)` returns `None`
- [ ] **stale by savepoint rollback**: in one `atomic()`, take the stream, append
      inside a nested `atomic()` that raises and is caught, then
      `require_sequence(0)` returns `None`

**Gotchas:**

- The two staleness tests assert the *correct* outcome against the *stale*
  object, so they read as trivial. They are the whole reason the method queries.
  Do not simplify either into a direct comparison.
- The savepoint test needs the append's own exception raised *after* the append,
  inside the nested block, and caught outside it. `append` itself will not fail.
- `require_sequence` is not a property and returns `None`. A version returning
  `bool` invites `if stream.require_sequence(n):`, which reads as the opposite of
  what it does.
- `PositiveBigIntegerField` does not stop Python passing a negative; the database
  never sees it, which is why the negative branch precedes the query.

---

## Task 2: The contention test

**Files:**
- Modify: `tests/test_event_append.py`

**Interfaces:**
- Consumes: `require_sequence`, `StreamSequenceMismatch` from Task 1.

**Steps:**

- [ ] Copy `test_concurrent_appends_serialize_into_one_contiguous_range` as the
      harness: the committed seed append, the two `threading.Event`s, the
      `errors` list, `close_old_connections` at both ends of each thread, and the
      `execute_wrapper` that fires on `"games_libraryeventstreamhead" in sql and
      "FOR UPDATE" in sql`.
- [ ] The waiter forms its expectation with a **plain non-locking read** —
      `LibraryEventStreamHead.objects.get(library=owned_library).current_sequence`
      — *before* it enters `atomic()` and calls `lock_stream`.
- [ ] The waiter catches `StreamSequenceMismatch` inside its own thread and
      records it in a results dict. It must not propagate.
- [ ] Mark `@pytest.mark.django_db(transaction=True)`.
- [ ] Assert: `not errors`, both threads finished, the recorded mismatch's
      `expected` is the pre-append value and its `actual` is the post-append one,
      and the holder's events are the only rows.
- [ ] Run with `PYTEST_WORKERS=0`, ten times, and confirm ten passes.
- [ ] Commit.

**Gotchas:**

- **The inversion trap.** If the waiter reads its expectation through
  `lock_stream(...).current_sequence`, that call's own `FOR UPDATE` trips the
  `execute_wrapper`, releases the holder, blocks, and then returns the
  *advanced* head. The waiter forms an expectation that passes, the test goes
  green, and it proves nothing. The non-locking read is load-bearing.
- The module-level `pytestmark` is the non-transactional mark. Every thread test
  in this file overrides it; forgetting to means the threads see no committed
  data.
- The harness ends with `assert not errors`, and `except BaseException` collects
  everything. A mismatch that escapes the waiter thread fails the test on the
  exact exception it is asserting.
- The seed append before the threads start is required for the same reason the
  original test documents: an uncommitted head is invisible to the waiter, whose
  `SELECT ... FOR UPDATE` then matches zero rows and never waits.
- This test discriminates a pre-lock read from a post-lock one. It does **not**
  discriminate a cached field from a re-read — Task 1's two staleness tests are
  what cover that, and they need no threads.

---

## Task 3: The append parameter

**Files:**
- Modify: `games/events/append.py`
- Modify: `tests/test_event_append.py`

**Interfaces:**
- Consumes: `require_sequence` from Task 1.
- Produces: `LockedStream.append(..., expected_sequence: int | None = None)`.
  `None` performs no check.

**Steps:**

- [ ] Add the keyword-only parameter, defaulting to `None`, after the existing
      optional ones.
- [ ] Call `require_sequence` immediately after the empty-events guard and before
      `canonical_json`. Not before the guard.
- [ ] Write the tests below, run them, confirm green.
- [ ] Commit.

**Tests:**

- [ ] `append(expected_sequence=<current>)` appends normally, and its
      `AppendResult` range is what it would be without the parameter
- [ ] `append(expected_sequence=<stale>)` raises `StreamSequenceMismatch`, writes
      no `LibraryEvent` row, and leaves `current_sequence` unmoved
- [ ] `append([], expected_sequence=<stale>)` raises `ValueError`, not the
      mismatch — the empty-events guard still wins
- [ ] a caller owning its own `atomic()` that catches the mismatch **inside** the
      block can still commit that transaction, and unrelated work written in it
      before the refusal is present afterwards
- [ ] the same mismatch raised under `run_in_transaction` is not retried — assert
      the operation ran exactly once — and the transaction rolls back
- [ ] two `append` calls on one locked stream with the same `expected_sequence`:
      the first passes, the second raises `StreamSequenceMismatch`
- [ ] `append()` with no `expected_sequence` is unchanged — covered by the
      existing suite; add nothing

**Gotchas:**

- The two transaction tests are different callers, not two views of one property.
  The spec's "a caller may still commit" is true only for the one owning its
  `atomic()` and catching inside it; `run_in_transaction` catches only
  `IntegrityError` and `OperationalError`, so the mismatch escapes its `atomic()`
  and rolls back. Assert each separately or the pair proves neither.
- `require_sequence` runs a successful `SELECT` and then raises a plain Python
  exception, so Django does not mark the transaction for rollback. That is what
  makes the still-committable case work; a version that raised from inside a
  failed query would not.
- Do not add a "no projector ran" assertion. This module wires
  `EventWiring(event_types=EVENT_TYPES)` over the empty default projector
  registry and has none of the recording apparatus from
  `tests/test_event_projectors.py`. `require_sequence` runs first and
  `projectors.apply` runs last, so the zero is structural; the no-rows and
  head-unmoved assertions are the load-bearing ones.
- `is_retryable` must not gain a case. If a test needs it to, the exception is
  inheriting from the wrong base.

---

## Task 4: Close the loop

**Files:**
- Modify: `docs/superpowers/specs/2026-08-23-issue-664-command-dispatch-design.md`
- Modify: `docs/superpowers/plans/2026-08-23-issue-664-command-dispatch.md`

**Steps:**

- [ ] Run the full `make check` — including `e2e/` — and confirm green. A
      hand-picked subset is not the gate.
- [ ] Amend the #664 spec: "#901's `expected_sequence` is checked by the
      dispatcher against the head" → checked by `LockedStream`, under the head
      lock. Keep the surrounding argument intact — that sentence exists to
      justify withholding the stream from `CommandContext` (*the dispatcher, not
      `build`*), and that justification is unaffected.
- [ ] Amend the #664 plan's matching sentence, "#901 checks `expected_sequence`
      at the dispatcher", the same way.
- [ ] Edit #901's body: its Outcome names `games.events.append_events()`, deleted
      by #662. Point it at `LockedStream.append` and `require_sequence`.
- [ ] Comment on #667 with the swap-time recipe it now has: replay outside any
      transaction, then `atomic()` → `lock_stream` → `require_sequence(folded_through)`
      → swap, raising `StreamSequenceMismatch` if anything landed meanwhile.
- [ ] Comment on #901 linking the spec and this plan.
- [ ] Commit the doc amendments.

---

## Self-review notes

- **The re-read is the one decision a reviewer will push back on**, because the
  first draft of the spec argued the opposite: that the head lock made a query
  redundant. It does not. `lock_stream` builds a fresh instance per call and
  `append` advances only its own, so two `LockedStream`s in one transaction
  diverge — and `test_lock_stream_returns_the_same_head_for_a_provisioned_library`
  shows the suite already taking two. The failure is silent and in the dangerous
  direction: a cached value behind the row passes a check that should raise.
- **Nothing repairs the stale `LockedStream` itself.** `require_sequence` reads
  without writing back, so a stale stream that passes the check and then appends
  collides on `unique_library_event_stream_sequence` and is retried. Loud beats
  silent, and whether `lock_stream` should be idempotent per transaction is a
  question this issue does not own.
- **The `ValueError` branch cannot see the misuse it most needs to.**
  `LockedStream` exposes no library identity, so comparing one library's number
  against another's stream raises `ValueError` only if the other is ahead, looks
  like a retryable race if it is behind, and passes silently if they are equal.
  The exception message must not guess "off by one" for that reason.
- **Task 2 is the only test that justifies the feature, and the easiest to write
  backwards.** Its inversion trap produces a green test that asserts nothing.
