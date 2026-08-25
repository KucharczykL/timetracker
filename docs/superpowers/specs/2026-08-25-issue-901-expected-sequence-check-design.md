# The optional expected-sequence concurrency check

A caller that reads the library stream, works on what it read, and then writes,
has a gap between the read and the write. Nothing today lets it say what it read.
This issue adds the sentence: *the head was at N when I looked, and I will not
proceed if it has moved.*

The
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
lists the check as optional on the append path.
[#661](https://github.com/KucharczykL/timetracker/issues/661) already reserved
the place for it: `LockedStream` exposes `current_sequence`, "which is what #901
compares an `expected_sequence` against, under the lock, before deciding whether
to append at all."

The issue's own Outcome names `games.events.append_events()`. That function no
longer exists — [#662](https://github.com/KucharczykL/timetracker/issues/662)
deleted it, and `idempotent_append` covers what it did. The parameter lands on
`LockedStream.append` instead.

## What it is

One comparison on `LockedStream`, reachable two ways: as a method a caller
invokes for its own reasons, and as a parameter of `append`.

```python
class StreamSequenceMismatch(CommandConflict):
    """Another writer advanced the stream."""

    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(
            f"The stream was at {expected} when it was read and is at {actual} "
            "now. Nothing was recorded; read the stream again and retry."
        )
        self.expected = expected
        self.actual = actual


class LockedStream:
    def require_sequence(self, expected: int) -> None: ...

    def append(
        self,
        events: Sequence[NewEvent],
        *,
        ...,
        expected_sequence: int | None = None,
    ) -> AppendResult: ...
```

`StreamSequenceMismatch` lives in `append.py`, importing `CommandConflict` from
`conflicts.py` — the arrangement `conflicts.py` exists for, where the base sits
alone and each raising module owns its leaf.

The message and the two attributes follow `RetryBudgetExhausted` and
`IdempotencyKeyMismatch`. `CommandConflict` is "the one base for command failures
a person can be shown and asked to act on", and a caller deciding whether to
retry needs the distance, not prose it has to parse.

`expected` is a bare `int`, not a PEP 695 alias. `AppendResult.first_sequence`,
`last_sequence`, and `LockedStream.current_sequence` are all bare `int` today; an
alias introduced on this one parameter would be the only annotated sequence in the
package, and applying it to the rest is the sweep this issue's Boundary forbids.

`expected_sequence=None` — the default — performs no check. `append` behaves
exactly as it does today.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| Shadow rebuild and atomic swap, the first caller | #667 |
| Versioned full-library backup and restore | #796 |
| Per-aggregate versioning for edit-form conflicts | #671 |
| A stale `LockedStream` held across a second `lock_stream` | pre-existing; see below |
| Threading a token through `dispatch` | nobody; see below |

No schema change, no data change, no migration. Rollback is `git revert`, and
replay parity is unaffected because nothing here writes an event or reads one.

## The token is library-wide

The value compared is one library's whole stream sequence, so any event anywhere
in that library invalidates it. That is the right guarantee for an operation whose
correctness depends on the whole stream — a shadow rebuild folded events 1…N and
must know that N is still the end — and the wrong one for a per-entity edit form,
where an unrelated write elsewhere in the library would produce a conflict the
user cannot explain.

Per-entity conflict is therefore not covered here, and belongs to the first
form-bearing evented domain (#671) on its own evidence. Event sourcing already
records and attributes every overwrite, so a clobber on an edit form is visible
and recoverable rather than silent.

## Why the method exists beside the parameter

The first caller writes no events. A shadow rebuild replays 1…N outside any
transaction — which is what lets it run long without holding a lock — then opens
a transaction, locks the head, checks that N is still the end, and swaps:

```python
#: Outside any transaction: replay bounds itself on the head it read.
replayed = replay(library)
...  # build the shadow tables, however long that takes

with transaction.atomic():
    stream = lock_stream(library)
    stream.require_sequence(replayed.folded_through)
    ...  # swap the shadow tables into place
```

`lock_stream` refuses to run outside an open transaction, so the `atomic()` block
is not decoration. A parameter of `append` alone would leave this caller writing
the comparison and its refusal a second time, at the one call site this issue
exists to serve.

## The three branches

`require_sequence` resolves in this order:

| `expected` | Outcome |
| --- | --- |
| `< 0` | `ValueError`, before any query |
| `> current_sequence` | `ValueError` |
| `< current_sequence` | `StreamSequenceMismatch(expected, actual)` |
| `== current_sequence` | returns `None` |

The negative case is ordered first so that `require_sequence(-1)` against a head
at 5 has one answer rather than two.

The head only ever advances — `current_sequence` is written in exactly one place,
`append`, and only upward — so an expectation above it names a sequence no history
produced. It is not a race, and no number of retries clears it. `ValueError` is
what this package already raises for a caller bug: `append` for an empty event
sequence, `validate_idempotency_key` for a key the column would reject, and
`idempotency.py` says so outright when it explains why `IdempotencyKeyMismatch` is
*not* a `ValueError`.

`retry.is_retryable` draws the same line for the same reason, refusing to classify
a non-sequence unique violation as retryable because "retrying it four times would
spend the budget to tell the user to retry something that can never work."

The likeliest way to reach it is an off-by-one — passing the sequence the *next*
event should receive rather than the last one recorded. The message must not say
so. See the cross-library case under Forecloses: the same branch catches a caller
comparing one library's number against another library's stream, and a message
that guesses "off by one" would misdirect it.

`current_sequence` is a `PositiveBigIntegerField` defaulting to `0`, where zero
means the stream exists and nothing has been appended. `require_sequence(0)` is
therefore a first-class assertion that a library is still empty, which is what a
rebuild of an empty library and a restore into an empty shell both need.

## The comparison re-reads the head

`require_sequence` issues a `SELECT` for `current_sequence` and compares against
that, not against the value cached on the `LibraryEventStreamHead` instance
`lock_stream` returned.

The cached value is not reliably the row's. `lock_stream` constructs a fresh
instance per call, and `append` advances only `self._head`, so two `LockedStream`s
over one row in one transaction diverge the moment either appends — and
`test_lock_stream_returns_the_same_head_for_a_provisioned_library` shows the suite
already taking two. `append` also assigns `current_sequence` in memory before
`save()`, so a savepoint rollback reverts the row and leaves the object ahead of
it. Both were reproduced against PostgreSQL.

The first of those fails in the dangerous direction: a cached value that is
*behind* the row makes `require_sequence` pass a check that should have raised.
The re-read is one round trip on a path that runs once per whole-library
operation.

The re-read is cheap and consistent because the lock is held: the row cannot move
under it, so the `SELECT` returns a value that stays true for the rest of the
transaction. The lock is what makes the check meaningful; the query is what makes
it true. Outside the lock, a comparison is a statement about a value that may be
stale before it is acted on.

`require_sequence` does not write back to `self._head`. Repairing a stale
`LockedStream` would silently paper over the double-lock hazard above, which
predates this issue and belongs to whoever decides whether `lock_stream` should
be idempotent per transaction. A stale stream that passes the check and then
appends collides on `unique_library_event_stream_sequence` and is retried — loud,
not silent.

## A refusal writes nothing

`append` runs the check immediately after its empty-events guard and before
`canonical_json`, payload validation, the rows, and the head advance.

Not before the empty-events guard. `append([], expected_sequence=…)` must keep
raising the `ValueError` it raises today: `idempotency.py` leans on that exact
`ValueError` as the marker separating a programming error from a conflict, and a
stale expectation must not reclassify an empty append as a race.

The invariant is the one `append` already documents for its payload refusals: the
refusal writes no row and advances no head, so a caller may still commit the
transaction. That last clause holds only for a caller that owns its own
`atomic()` block **and catches the exception inside it** — `require_sequence`
runs a successful `SELECT` and then raises a plain Python exception, so Django
never marks the transaction for rollback.

It does *not* hold for a caller under `run_in_transaction`, which owns the
`atomic()` block itself and catches only `IntegrityError` and `OperationalError`.
A `StreamSequenceMismatch` escapes that block and rolls the transaction back.
Both are correct; they are different callers, and the verification covers each.

## Retrying is the caller's job

`StreamSequenceMismatch` is neither an `IntegrityError` nor an `OperationalError`,
so `run_in_transaction` passes it through untouched and `is_retryable` needs no
new case. `retry.py` already anticipates this in prose: a `CommandConflict`
"leaves by the ordinary route without a case of its own."

That is correct rather than incidental. `run_in_transaction` re-runs the same
callable, and a caller whose expectation went stale must re-read the stream before
it can form a new one. A silent retry would re-run the operation against the
number it already knows is wrong.

## Nothing above `LockedStream` changes

`idempotent_append` and `dispatch` do not gain the parameter.

`dispatch` serves commands, which are per-entity user actions — the case this
token is deliberately wrong for. Offering it there would put a parameter in front
of every command author that produces spurious conflicts when used as it reads.
`idempotent_append` would additionally force an answer now to which wins when a
replayed key meets a stale expectation, with no caller to judge the answer
against.

Two committed documents say otherwise and are amended by this issue:
`2026-08-23-issue-664-command-dispatch-design.md` ("#901's `expected_sequence` is
checked by the dispatcher against the head") and
`2026-08-23-issue-664-command-dispatch.md` ("#901 checks `expected_sequence` at
the dispatcher"). Both sentences exist to justify withholding the stream from
`CommandContext` — *the dispatcher, not `build`* — and that justification survives
untouched. Only the location is wrong: the check is `LockedStream`'s.

## Verification

`tests/test_event_append.py`:

- each of the four resolution cases, through `require_sequence` directly
- `require_sequence(-1)` against a head at 5 raises `ValueError`, not a mismatch
- `require_sequence(0)` against a freshly provisioned head passes
- `StreamSequenceMismatch` carries `expected` and `actual`
- `append([], expected_sequence=<stale>)` still raises `ValueError`
- `append(expected_sequence=…)` refusing writes no `LibraryEvent` row and leaves
  `current_sequence` unmoved
- a caller owning its own `atomic()` and catching the mismatch inside it can still
  commit that transaction
- the same mismatch under `run_in_transaction` is not retried and rolls back
- two `append` calls on one locked stream: the same `expected_sequence` passes the
  first and fails the second
- a `LockedStream` staled by a second `lock_stream` + `append` in one transaction:
  `require_sequence` sees the row, not the cached field
- a `LockedStream` staled by a savepoint rollback: same

There is no "no projector ran" assertion. `test_event_append.py` wires
`EventWiring(event_types=EVENT_TYPES)` over the empty default projector registry
and has none of the recording apparatus that lives in `test_event_projectors.py`.
Importing it to assert a zero that `require_sequence`-runs-first makes structural
would test the ordering of two statements, which the two assertions above already
cover.

### The contention test

Modelled on `test_concurrent_appends_serialize_into_one_contiguous_range`, and
the only test that proves the comparison is worth anything:

1. The waiter forms its expectation with a **plain non-locking read** —
   `LibraryEventStreamHead.objects.get(...).current_sequence` — before it calls
   `lock_stream`. This is load-bearing. If the expectation comes from a
   `LockedStream`, the waiter's own `FOR UPDATE` trips the harness's
   `execute_wrapper`, releases the holder, blocks, and then reads the *advanced*
   head — forming an expectation that passes. The test would go green having
   proved nothing.
2. The holder takes the lock and appends.
3. The waiter calls `lock_stream`, blocks until the holder commits, then
   `require_sequence(<pre-append value>)` must raise.

Requirements the harness imposes: `@pytest.mark.django_db(transaction=True)`,
overriding the module-level mark; and the expected exception must be caught
*inside* the waiter thread, because the harness's `except BaseException` collects
into `errors` and the test asserts `not errors`.

What it proves and what it does not: it discriminates a pre-lock read from a
post-lock one. It does not discriminate a cached field from a re-read — the two
staleness tests above are what cover that, and they need no threads.

## Forecloses

**Cross-library misuse is undetectable.** `LockedStream` exposes `stream_id` and
`current_sequence` and no library identity, so a caller comparing library B's
number against library A's stream is caught only by luck: `ValueError` if B is
ahead, `StreamSequenceMismatch` — read as a race and retried forever — if B is
behind, and silence if they happen to be equal. This is the most likely misuse of
a library-wide token and the check cannot see it.

**An expectation is library-wide** and cannot be narrowed to an aggregate; a
caller wanting that needs #671's answer, not a variant of this parameter.

**`require_sequence` is public**, so a caller can check and then forget to append.
The type system cannot express "checked, therefore must write".

**`expected` is validated by range, not by type.** `bool` is an `int` in Python,
so `require_sequence(True)` compares as `1` against a head at 1 and passes.

**The check is advisory.** `append` without the parameter is unchanged, so no
existing writer gains a guarantee and none loses one.

**The token carries no protection across a lock release.** A caller that reads,
releases, and re-locks is protected only because the comparison happens on the far
side of the second lock — which is why this lives on `LockedStream` and nowhere a
caller could invoke it unlocked.
