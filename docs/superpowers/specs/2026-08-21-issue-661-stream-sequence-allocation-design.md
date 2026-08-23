# Atomic library-stream sequence allocation

`games/events/` is the first and only writer of the tables
[#660](https://github.com/KucharczykL/timetracker/issues/660) created. It
implements the append half of the command transaction described in the
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md):
lock the library's stream head, allocate a contiguous sequence range, write the
events, advance the head — all inside the caller's transaction.

## What it is

A lock primitive, an append operation on the locked stream, and a convenience
function that combines them. A caller describes the events of one human action;
the module assigns their position in the library's total order and persists
them.

Sequence allocation has no observable behaviour on its own. A number handed out
without a row written against it cannot collide, cannot be replayed, and cannot
be tested against the `(stream, sequence)` unique constraint. Allocation and
append are therefore one operation.

## Ownership boundary

Everything below is out of scope, and each has a named owner:

| Not here | Owner |
| --- | --- |
| Idempotency: repeating a key currently appends again | #662 |
| Classifying and retrying serialization failures, deadlocks, collisions | #663 |
| Authentication, authorization, command objects | #664 |
| Projectors reacting to appended events | #665 |
| Reading the stream, replay, deterministic empty-state rebuild | #666 |
| Event-type registry and payload validation | #900 |
| Optional `expected_sequence` optimistic-concurrency check | #901 |

No schema changes. No migration, no backfill, no data reconciliation, and
therefore no rollback surface: reverting this work is deleting a package.

## Preconditions

**READ COMMITTED.** `timetracker/database.py` builds `OPTIONS` from
`DATABASE_URL` and sets no `isolation_level`, so the server default applies.
The design is correct only at READ COMMITTED, and every load-bearing step
changes under REPEATABLE READ: `select_for_update` against a row a concurrent
transaction just committed raises a serialization failure rather than returning
the fresh `current_sequence`, and the losing `get_or_create` fails with
`OperationalError` instead of `IntegrityError`, so Django's `except
IntegrityError` fallback never runs. This is a documented precondition, not a
runtime assertion — a project-wide isolation change would break more than this
module and belongs in [the database contract](../../database.md).

**An open transaction**, owned by the caller. See below.

## Design

### The lock is a separate step from the append

The charter's ordering is: lock the head, *then* read and validate mutable
projections, *then* append. That order is the whole point of the head lock — a
command that reads projections before locking has validated against state that
can move underneath it.

An API where locking happens inside the append call cannot express that order.
So the primitive is `lock_stream(library) -> LockedStream`, and appending is a
method on the returned object:

```python
with transaction.atomic():
    stream = lock_stream(library)
    ...  # read and validate projections; they cannot move now
    result = stream.append(events, ...)
```

`append_events(library, events, ...)` remains as a convenience for commands with
nothing to validate. It is two lines over the primitive, and both paths share
one implementation so they cannot drift.

> **Superseded by [#662](https://github.com/KucharczykL/timetracker/issues/662).**
> `append_events` was deleted. Once a command's key must be recorded,
> `idempotent_append(..., build=lambda _: events)` covers the same case, and
> leaving a non-idempotent convenience beside it gives a command author an easy
> way to write a command that silently cannot deduplicate. `lock_stream` and
> `LockedStream.append` remain, so appending without a record is still
> reachable — just no longer the convenient path.

`lock_stream` is a plain function rather than a context manager. The lock is
held until the caller's transaction commits, not until a block exits; a `with`
statement would advertise a release that does not happen there.

`LockedStream` exposes `stream_id` and `current_sequence` — which is what #901
compares an `expected_sequence` against, under the lock, before deciding whether
to append at all. `append` may be called more than once on one locked stream;
sequences continue from where the previous call left off.

### The caller owns the transaction

`lock_stream` requires an open transaction on the write alias
(`transaction.get_connection(router.db_for_write(LibraryEvent))`) and raises
`TransactionRequired` when there is none.

The head lock must be held until the caller's projection writes commit — the
charter's rule that events and their synchronous projections land in one
transaction. A function that opened and closed its own `atomic()` block would
release the lock at return, leaving the caller's later writes in a separate
transaction with a torn write possible.

`select_for_update()` would itself raise `TransactionManagementError` outside a
transaction, so the explicit check is not what makes the lock safe. It is what
prevents the *provisioning* path from acting first: in autocommit,
`get_or_create` would commit a head row before anything noticed the mistake.
Opening a transaction only when none exists would remove the error without
removing the hazard — a caller who forgot the outer transaction would silently
get the torn-write behaviour. The project sets no `ATOMIC_REQUESTS`, so views
run in autocommit and the check fires on real misuse.

> **Amended by [#663](https://github.com/KucharczykL/timetracker/issues/663).**
> The caller this section leaves unnamed now exists: `run_in_transaction` in
> `games/events/retry.py` opens the transaction, and re-runs the whole of it when
> PostgreSQL kills it for a recoverable reason. It raises the mirror of
> `TransactionRequired` — `NestedTransactionNotSupported` — when a transaction is
> already open on the same alias, because rolling back to a savepoint could not
> undo what an enclosing transaction had already done, and its retries would be
> weaker than they look. The two checks resolve the same
> `router.db_for_write(LibraryEvent)` alias with opposite polarity, so between
> them they bracket the one valid state: exactly one transaction, opened by the
> runner.

### The head is provisioned lazily

#660 created no head rows. The hot path is one query:

```python
try:
    head = LibraryEventStreamHead.objects.select_for_update().get(library=library)
except LibraryEventStreamHead.DoesNotExist:
    LibraryEventStreamHead.objects.get_or_create(library=library)
    head = LibraryEventStreamHead.objects.select_for_update().get(library=library)
```

Django's `get_or_create` already wraps its `create()` in `transaction.atomic()`
and falls back to `get()` on `IntegrityError`, so nesting it inside the caller's
transaction is savepoint-safe and needs no hand-rolled retry. Two concurrent
first-appends resolve at the `OneToOneField` unique constraint: the loser blocks
on the winner's uncommitted row, then takes the `get()` path. The re-select is
unconditional so the row is locked whichever branch produced it.

Locking first and provisioning only on `DoesNotExist` keeps the common case to a
single round trip, and avoids a window in which a concurrent `UserLibrary`
delete (CASCADE to the head) turns a follow-up lookup into an unhandled
`DoesNotExist`.

The alternative — provisioning at every `UserLibrary` creation site plus a
backfill migration — creates a permanent invariant that a future creation path
can silently break, with no recovery except another migration. Lazy provisioning
is self-healing and costs one extra round trip per library, once.

### Sequences come from the locked head, not a database sequence

A PostgreSQL `SEQUENCE` allocates outside transaction control: a rolled-back
append burns its numbers, leaving permanent gaps. Replay tolerates gaps, but
"the stream is dense" is a cheap, checkable invariant, and a per-library
sequence would need dynamic DDL per library anyway.

More decisively, a bare sequence generator hands out numbers without providing
the serialization point the charter's commands are built on.

### One append call allocates a contiguous range

All events of one human action are appended in one call and receive consecutive
sequences. Contiguity is what lets the Journal render a compound action as one
entry while Audit History expands it, and it is why a compound command never
needs a second head lock — there is one lock per library, so no lock order
exists to get wrong and no deadlock **between stream heads** is reachable.
Deadlocks involving non-stream rows remain possible, since a command transaction
also writes shared-catalog rows; the charter budgets #663's retries for exactly
that.

`select_for_update()` takes `FOR UPDATE`. Every event insert takes `FOR KEY
SHARE` on the head through both the `stream` foreign key and #660's raw
composite FK; `FOR UPDATE` conflicts with that, so an out-of-band event insert
blocks while an append holds the lock. `no_key=True` would serialize appends
equally well while permitting those inserts, which is not a property worth
having — nothing should be inserting events outside this module.

### Envelope fields split by scope

Per-call fields describe the action: `actor`, `correlation_id`,
`idempotency_key`, `source_metadata`, `recorded_at`. Per-event fields describe
the individual fact: `event_type`, `aggregate_type`, `aggregate_id`, `payload`,
`payload_schema_version`, `effective_time`, `causation_id`.

`correlation_id` is per-call because the charter's Journal rule depends on one
action sharing one correlation. `causation_id` is per-event because within an
action one event may be caused by another.

`recorded_at` is computed once per call and written to every row of that call.
#660 gave the column a per-row `default=timezone.now`, so this is a convention
this writer imposes, not a property of the schema: events of one action are one
act of recording. It also means #660's registration of `recorded_at` as
`IDENTITY_ORDER_SOURCE` for `games_libraryevent` is flat across an action, which
is correct — `sequence` is the only order, and `recorded_at` was never an
alternative to it.

`source_metadata` defaults to `None` in the signature and is stored as `{}`; the
column is NOT NULL with `default=dict`.

`stream`, `sequence`, and `library` on the event are never caller-settable.
A caller cannot assign a sequence or name another library's stream because the
API has no way to express either, which is stronger than the composite foreign
key that also forbids it.

### Errors propagate unclassified, and abort the transaction

The only exception this module raises is `TransactionRequired`, its own violated
precondition. Everything else reaches the caller untranslated — `IntegrityError`
(constraint violations), `OperationalError` (serialization failures, deadlocks,
lock timeouts), `DataError` (a `CharField` overflow: 255/100/255 on
`event_type`/`aggregate_type`/`idempotency_key`), and `ValidationError` (a
non-v7 UUID, raised by `UUIDv7Field.to_python`). #663 owns classifying these and
would otherwise have to unwrap a translation this layer invented.

**Any of them leaves the caller's transaction unusable.** `bulk_create` uses
`nullcontext()` rather than a savepoint when every object already carries a
primary key, which is always true here, so a failing INSERT aborts the
PostgreSQL transaction with nothing to roll back to. Retry therefore belongs at
the transaction boundary *above* this module: #663 restarts the whole
transaction, which re-takes the lock and re-reads the head. This module adds no
savepoint of its own, because a savepoint would offer a rollback target inside a
transaction whose projection reads are already invalid.

A `(stream, sequence)` collision is unreachable *through this module* while the
lock is held. It is not a database-level guarantee: nothing ties
`current_sequence` to `MAX(sequence)`, and code that inserts events directly —
`tests/test_event_models.py`'s `make_event` does exactly this — leaves the head
behind the real maximum, so the next append collides. That is the correct
outcome, and the raw constraint error names the cause better than a wrapper
would.

### Rows are written with `bulk_create`

One statement per append regardless of event count. Primary keys are minted in
the application process, not the database: `UUIDv7Field.__init__` sets
`default=uuid.uuid7`, so every instance carries a pk before insertion and
`bulk_create` takes its `objs_with_pk` path. #660's `db_default` of
`uuidv7()` is never exercised by this writer.

`bulk_create` skips `save()`, `full_clean()`, and `pre_save`/`post_save`
signals. `LibraryEvent` defines none of them and no signal is registered on it,
so nothing this design relies on is bypassed — but see the foreclosure list for
what it means for #665.

## API contract

```python
type SourceMetadata = dict[str, Any]  # {"origin": "manual"}


@dataclass(frozen=True, slots=True)
class NewEvent:
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID  # a v7 UUID; the column is the uuid_v7 domain
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


class LockedStream:
    stream_id: uuid.UUID
    current_sequence: int

    def append(
        self,
        events: Sequence[NewEvent],
        *,
        actor: User | None,
        correlation_id: uuid.UUID,
        idempotency_key: str,
        source_metadata: SourceMetadata | None = None,
        recorded_at: datetime | None = None,
    ) -> AppendResult: ...


def lock_stream(library: UserLibrary) -> LockedStream: ...


#: Deleted by #662; see the note above.
def append_events(
    library: UserLibrary, events: Sequence[NewEvent], **kwargs
) -> AppendResult: ...


class TransactionRequired(RuntimeError): ...
```

`AppendResult` is a named type rather than a list of rows because the charter's
idempotency rule — "repeating a completed `(library, idempotency_key)` returns
the original command result and its assigned sequence range" — makes the range a
value #662 must persist and replay. It exists here so #662 stores a shape that
already has a name.

`frozen=True` is identity immutability only. `NewEvent.payload` is a mutable
`dict` handed straight to the model, so a caller that retains and mutates it
after the call is mutating what was persisted.

An empty `events` sequence raises `ValueError`. A command that records nothing
must not take the lock.

### Module layout

`games/events/` is a package from the start: `append.py` holds this work, and
#662–#666 each add a sibling rather than growing one module. Callers import from
the submodule (`from games.events.append import lock_stream`), following
`games/views/`, whose `__init__.py` is empty and which re-exports nothing.

## Where the behaviour is pinned

`tests/test_event_append.py`.

Ordinary `django_db` tests cover: the first append provisions a head and starts
at sequence 1; a second append continues without a gap; a multi-event append is
contiguous and shares one `correlation_id` and one `recorded_at`; two appends on
one `LockedStream` continue the same range; a rolled-back append leaves both the
events table and `current_sequence` untouched; an empty event sequence is
rejected; two libraries advance independently; `AppendResult` matches the
persisted rows; `actor=None` and `source_metadata=None` are accepted, the latter
stored as `{}`; `append_events` and the primitive produce identical rows (that
last test went with `append_events` in #662).

Three tests need `django_db(transaction=True)`, because plain `django_db` builds
a `TestCase` subclass that wraps every test in an atomic block:

- **outside a transaction**: `lock_stream` raises `TransactionRequired` and no
  head row is created. Unreachable under plain `django_db`, where
  `in_atomic_block` is always true.
- **lock probe**: while an append transaction is open, a second connection
  cannot take the head. Django keeps one connection per alias per thread, so
  `connections["default"]` in the test thread *is* the append's connection; the
  probe opens a raw psycopg connection from `connection.get_connection_params()`
  and asserts `SELECT … FOR UPDATE NOWAIT` fails, following
  `tests/test_purchase_uuid_primary_key.py:322`. No thread, no timing
  dependency.
- **contention**: two appends of two events each, on separate connections,
  forced to overlap rather than left to chance — a `connection.execute_wrapper`
  releases the second writer only once the first is inside its transaction with
  the lock held, per `tests/test_library_conversion.py:819`. Asserts the union
  of assigned sequences is exactly 1…4 with no duplicates and one shared stream.
  Every wait carries a timeout and every thread calls `close_old_connections()`
  in a `finally`: an unbounded barrier hangs the suite rather than failing it,
  and a thread leaking an open transaction blocks `TransactionTestCase`'s
  truncation teardown indefinitely.

These are the first tests to commit rows into `games_libraryevent`. #660's
migration `0023` refuses reversal while either table has rows, and several
migration-rewind harnesses in `tests/` rewind past it; `TransactionTestCase`
truncation should clear the rows first, and the implementation verifies this
rather than assuming it.

## What this shape forecloses

- **Appending without writing.** There is no way to reserve numbers for later
  use. Density is guaranteed only because allocation and insertion share a
  transaction.
- **Concurrent appends within one library.** Appends are fully serialized by the
  head lock; throughput per library is one append transaction at a time.
  Different libraries stay independent. Acceptable while a library has one human
  writer.
- **Atomic appends spanning two libraries.** Deliberate: it would require two
  head locks and therefore a lock order.
- **`(library, idempotency_key)` uniqueness, permanently.** #660 recorded that
  adding it is "cheap while the tables are empty and expensive afterwards"; this
  issue is what ends the empty window. The design also makes it unsatisfiable:
  one call writes N rows carrying the same key, so a unique constraint would
  reject every multi-event append. #662 must therefore record command
  idempotency in its own table keyed on `(library, idempotency_key)`, storing
  the returned sequence range, rather than constraining the events table.
- **Signal-driven projectors.** `bulk_create` emits no `post_save`, so #665
  cannot register projectors as signal receivers on `LibraryEvent`; they must be
  invoked by the append path itself. This is the better design anyway —
  projectors must run in a defined order inside the same transaction — but it is
  a consequence of this choice, not a free one.
- **Deduplication.** Until #662, repeating an `idempotency_key` appends again.
- **Payload shape.** `payload` is unvalidated JSONB and `event_type` is any
  non-empty string until #900.

## Verification

`make check` — the full gate including `e2e/`. `make audit-uuid-identity` is
unaffected: no new tables, no new relation columns.
