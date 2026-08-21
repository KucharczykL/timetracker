# Atomic library-stream sequence allocation

`games/events.append_events()` is the first and only writer of the tables
[#660](https://github.com/KucharczykL/timetracker/issues/660) created. It
implements the append half of the command transaction described in the
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md):
lock the library's stream head, allocate a contiguous sequence range, write the
events, advance the head — all inside the caller's transaction.

## What it is

One function, plus the two value types it reads and returns. A caller describes
the events of one human action; the function assigns their position in the
library's total order and persists them.

Sequence allocation has no observable behaviour on its own. A number handed out
without a row written against it cannot collide, cannot be replayed, and cannot
be tested against the `(stream, sequence)` unique constraint. Allocation and
append are therefore one operation, not two.

## Ownership boundary

Everything below is out of scope, and each has a named owner:

| Not here | Owner |
| --- | --- |
| Idempotency: repeating a key currently appends again | #662 |
| Classifying and retrying serialization failures, deadlocks, collisions | #663 |
| Authentication, authorization, command objects | #664 |
| Projectors reacting to appended events | #665 |
| Reading the stream, replay, deterministic empty-state rebuild | #666 |
| Event-type registry and payload validation | new kernel issue, before #671 |
| Optional `expected_sequence` optimistic-concurrency check | new kernel issue, before #667 |

No schema changes. No migration, no backfill, no data reconciliation, and
therefore no rollback surface: reverting this work is deleting a package.

## Design

### The caller owns the transaction

`append_events` requires an open transaction and raises `TransactionRequired`
when there is none. It does not open its own.

The head lock must be held until the caller's projection writes commit —
that is the charter's rule that events and their synchronous projections land in
one transaction. A function that opened and closed its own `atomic()` block
would release the lock at return, leaving the caller's subsequent writes in a
separate transaction and a torn write possible.

Opening a transaction only when none exists would remove the error without
removing the hazard: the dangerous case — a caller who forgot the outer
transaction — would get exactly the torn-write behaviour, silently. The project
sets no `ATOMIC_REQUESTS`, so views run in autocommit and the check fires on
real misuse rather than being trivially satisfied.

### The head is provisioned lazily

#660 created no head rows. The first append for a library creates its head via
`get_or_create`, then re-selects it `FOR UPDATE`.

Django's `get_or_create` already wraps its `create()` in `transaction.atomic()`
and falls back to `get()` on `IntegrityError`, so nesting it inside the caller's
transaction is savepoint-safe and needs no hand-rolled retry. Two concurrent
first-appends resolve at the `OneToOneField` unique constraint: the loser blocks
on the winner's uncommitted row, then takes the `get()` path.

The alternative — provisioning at every `UserLibrary` creation site plus a
backfill migration — creates a permanent invariant that a future creation path
can silently break, with no recovery except another migration. Lazy provisioning
is self-healing and costs one savepoint per library, once.

### Sequences come from the locked head, not a database sequence

A PostgreSQL `SEQUENCE` allocates outside transaction control: a rolled-back
append burns its numbers, leaving permanent gaps. Replay tolerates gaps, but
"the stream is dense" is a cheap, checkable invariant worth keeping, and a
per-library sequence would need dynamic DDL per library anyway.

More decisively, the head lock is not incidental to allocation — it is the
serialization point the charter's commands are built on. A command locks the
head *before* reading mutable projections, so the projections it validates
against cannot move underneath it. A bare sequence generator hands out numbers
without providing that.

### One call allocates a contiguous range

All events of one human action are appended in one call and receive consecutive
sequences. Contiguity is what lets the Journal render a compound action as one
entry while Audit History expands it, and it is why a compound command never
needs two head locks — there is only ever one lock per library, so no lock order
exists to get wrong and no cross-library deadlock is reachable.

### Envelope fields split by scope

Per-call fields describe the action: `library`, `actor`, `correlation_id`,
`idempotency_key`, `source_metadata`, `recorded_at`. Per-event fields describe
the individual fact: `event_type`, `aggregate_type`, `aggregate_id`, `payload`,
`payload_schema_version`, `effective_time`, `causation_id`.

`correlation_id` is per-call because the charter's Journal rule depends on one
action sharing one correlation. `causation_id` is per-event because within an
action one event may be caused by another.

`recorded_at` is a single timestamp computed once per call, not a per-row
default. Events of one action are one act of recording; letting rows drift by
microseconds would invite treating `recorded_at` as an ordering signal, which it
is not — sequence is the only order.

`stream`, `sequence`, and `library` on the event are never caller-settable.
A caller cannot assign a sequence or name another library's stream because the
API has no way to express either, which is stronger than the composite foreign
key that also forbids it.

### Database errors propagate unclassified

The only exception this module raises is `TransactionRequired`, its own violated
precondition. `IntegrityError` and `OperationalError` reach the caller
untranslated, because #663 owns classifying retryable PostgreSQL failures and
would otherwise have to unwrap a translation this layer invented.

Under the head lock a `(stream, sequence)` collision is unreachable. If one
occurs it means something wrote events bypassing this function, and the raw
constraint error names that more precisely than any wrapper would.

### Rows are written with `bulk_create`

One statement per append regardless of event count. Verified against the
`db_default` UUIDv7 primary key: `bulk_create` returns the generated primary
keys on PostgreSQL, so `AppendResult` can carry persisted rows without a
re-query.

## API contract

```python
@dataclass(frozen=True, slots=True)
class NewEvent:
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload: dict[str, Any]
    payload_schema_version: int = 1
    effective_time: TemporalValue | None = None
    causation_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AppendResult:
    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int
    events: tuple[LibraryEvent, ...]


def append_events(
    library: UserLibrary,
    events: Sequence[NewEvent],
    *,
    actor: User | None,
    correlation_id: uuid.UUID,
    idempotency_key: str,
    source_metadata: SourceMetadata | None = None,
    recorded_at: datetime | None = None,
) -> AppendResult: ...
```

`AppendResult` is a named type rather than a list of rows because the charter's
idempotency rule — "repeating a completed `(library, idempotency_key)` returns
the original command result and its assigned sequence range" — makes the range a
value #662 must persist and replay. It exists here so #662 stores a shape that
already has a name.

An empty `events` sequence raises `ValueError`. A command that records nothing
must not take the lock.

### Module layout

`games/events/` is a package from the start. `append.py` holds this work;
#662–#666 each add a sibling rather than growing one module, following the
`games/views/` precedent. `__init__.py` re-exports the public names.

## Where the behaviour is pinned

`tests/test_event_append.py`.

Ordinary transactional tests cover: first append provisions a head and starts at
sequence 1; a second append continues without a gap; a multi-event append is
contiguous and shares one `correlation_id` and one `recorded_at`; calling
outside a transaction raises and writes nothing; a rolled-back append leaves
both the events table and `current_sequence` untouched; an empty event sequence
is rejected; two libraries advance independently; `AppendResult` matches the
persisted rows; `actor=None` is accepted.

Two tests need `django_db(transaction=True)`:

- a **lock probe** asserts that while an append transaction is open, a second
  connection's `select_for_update(nowait=True)` on that head raises. This proves
  the lock is taken, with no timing dependency.
- a **contention test** runs two appends of two events each on separate
  connections, released together by a barrier, and asserts the union of assigned
  sequences is exactly 1…4 with no duplicates and one shared stream. This proves
  the outcome under a real race, which the lock probe alone does not.

## What this shape forecloses

- **Appending without writing.** There is no way to reserve numbers for later
  use. Anything wanting that would need a different allocator, since density is
  guaranteed only because allocation and insertion share a transaction.
- **Concurrent appends within one library.** Appends to a library are fully
  serialized by its head lock; throughput per library is one append transaction
  at a time. Different libraries stay independent. This is the charter's trade
  and is acceptable while a library has one human writer.
- **Atomic appends spanning two libraries.** Deliberate: it would require
  holding two head locks and therefore a lock order.
- **Deduplication.** Until #662, repeating an `idempotency_key` appends a second
  time. The field is stored, not enforced, exactly as #660 left it.
- **Payload shape.** `payload` is unvalidated JSONB and `event_type` is any
  non-empty string until the registry issue lands.

## Verification

`direnv exec . make check` — the full gate including `e2e/`. `make
audit-uuid-identity` is unaffected: no new tables, no new relation columns.
