# Command idempotency records

A command that a user submits twice — a double-clicked button, a retried
request, a replayed import — must record its events once. The
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
states the rule twice over: repeating a completed `(library, idempotency_key)`
returns the original command result and its assigned sequence range, and reusing
a key with different canonical command input is rejected.

[#661](https://github.com/KucharczykL/timetracker/issues/661) delivered the
append half of the command transaction and deliberately left both behaviours
undone: today a repeated key appends a second time. This adds the record that
makes the first append the only one.

## What it is

A table mapping `(library, idempotency_key)` to the sequence range that key
already produced, a hash of the input that produced it, and one function that
consults the table under the stream-head lock before letting a command build its
events.

## Why a separate table

#660 gave `games_libraryevent` an `idempotency_key` column and explicitly did
not make it unique, noting that adding the constraint is "cheap while the tables
are empty and expensive afterwards". #661 is what ended the empty window, and it
ended it against that constraint: one append writes N rows carrying the same
key, so `UNIQUE (library_id, idempotency_key)` on the events table is
unsatisfiable for every multi-event append. The events table stays unconstrained
on that column.

**Deriving the range from the events instead was considered and rejected.**
`MIN(sequence)`/`MAX(sequence)` grouped by `(library_id, idempotency_key)`
reproduces the range without a new table — the record is, in that narrow sense,
a denormalization. It fails on the charter's second rule: the request
fingerprint has nowhere to live, so a key reused with different input cannot be
distinguished from an honest retry, and rejection becomes impossible. It also
puts an indexed lookup over a 255-character column on the path of every command.

The derivation is still worth knowing, because it is what makes this migration
reversible (see below).

## Ownership boundary

| Not here | Owner |
| --- | --- |
| Retrying and classifying `IdempotencyKeyMismatch` into a visible conflict | #663 |
| Deciding what a command's canonical input *is* | #664 |
| Command objects, authentication, authorization | #664 |
| Projectors, and skipping them on a replay | #665 |
| Reading the stream, replay, rebuild | #666 |
| Optional `expected_sequence` optimistic-concurrency check | #901 |

This issue owns the record, the comparison, the exception, and the one
canonicalizer that turns a command input into a fingerprint.

## Preconditions

Everything #661 established still holds and is not restated: READ COMMITTED, a
caller-owned open transaction, the head lock held until the caller commits.

## Design

### The check runs under the head lock

`lock_stream` is taken first, and the record is read after it — not before, and
without a `select_for_update` of its own.

This is what makes concurrent duplicates correct with no extra machinery. Two
requests carrying one key race; the loser blocks on the head lock the winner
holds; when the winner commits, the loser's `SELECT` sees the committed record
and returns the original range. A pre-lock read would let both proceed to
`build` and rely on the record's unique constraint to break the tie *after* both
had done the work, aborting the loser's transaction rather than answering it.

Blocking is the desirable behaviour here: the wait means the original command is
still in flight, and waiting for it produces the original result instead of a
race.

### The record is written after the append, in the same transaction

Order inside the caller's transaction:

1. `lock_stream(library)`;
2. `SELECT` the record for `(library, idempotency_key)`;
3. found and the fingerprint matches → return `ReplayedAppend`, **`build` never
   runs**;
4. found and the fingerprint differs → raise `IdempotencyKeyMismatch`;
5. not found → `build(locked_stream)`, then `stream.append(...)`, then `INSERT`
   the record with the returned range.

The record cannot be written before the append, because the sequence range does
not exist until then. Nothing is lost by that: the record commits with the
events it describes, so "completed" means "committed" and a rolled-back command
leaves neither. No pending/completed state machine, no lease, no expiry — a
crashed command simply never happened.

Short-circuiting before `build` means a duplicate does no validation work and
touches no projection. It also means `build` is the natural home for the
command's validation, which is the reason #661 separated locking from appending
in the first place.

### `build` is a callback, and that is what keeps the record honest

The charter's common case validates mutable projections *between* the lock and
the append. A `lock → append` wrapper cannot express that, so idempotency has to
survive a step in the middle. The alternative shapes both hand the caller
several calls to sequence correctly:

- `claim()` then `append()` then `record()` — forgetting the third call
  silently disables idempotency for that command, and no test in that command's
  own suite would notice.
- `claim()` returning a handle with `complete(result)` — removes the chance of
  the two calls disagreeing about the key, but not the chance of never making
  the second one.

Passing `build` inverts it: the function owns the whole sequence, so the record
write is not something a caller can omit. The cost is that a `build` needing to
return something besides events must close over a variable.

### The replay returns a different type

`idempotent_append` returns `AppendResult | ReplayedAppend`. `ReplayedAppend`
carries `stream_id`, `first_sequence`, and `last_sequence` — no `events`.

The mistake worth preventing is re-running projections against a replay, and
that mistake is reachable exactly through `.events`. mypy permits attribute
access on a union when every member declares the attribute, so `stream_id` and
both sequence bounds read without narrowing; only reaching `.events` forces an
`isinstance`, which is the projection-dispatch site. A `replayed: bool` flag on
one type would put the same check one comment away from being skipped.

The union does not propagate past the command boundary: #664's commands have
their own result type, and if #664 builds a runner rather than hand-written
command functions, the branch exists once. If #665 ends up dispatching
projectors inside `games/events/` — #661's foreclosure note says it must, since
`bulk_create` emits no signals — the replay skip becomes internal and the union
can collapse into a flag mechanically. Collapsing later is easy; retrofitting
type safety after N commands exist is not.

`ReplayedAppend` deliberately does not re-query the events. A caller that wants
the rows of a replayed command knows the stream and the range.

### The fingerprint is a hash, and this module owns the hashing

`request_fingerprint` is a sha256 hex digest in a `CharField(max_length=64)`.
The alternative — storing the canonicalized input as JSONB — buys an operator
the ability to see exactly which field changed, at the price of an unbounded
column holding a second copy of user data outside the event payload, with its
own retention and privacy surface. The hash answers the only question the rule
asks: same input, or not.

#664 decides *what* a command's canonical input is. This module ships
`fingerprint_command_input`, the single canonicalizer, so #664 cannot grow a
per-command variant that drifts: sorted keys, no whitespace, and an encoder for
the three types a command input actually contains beyond JSON's own —
`uuid.UUID`, `datetime`, `Decimal`. Anything else raises `TypeError`, on
purpose: a fallback to `repr()` would silently admit values whose text
representation is not stable across processes, and an unstable hash rejects
honest retries.

### Mismatch is the one error this module raises, and it spares the transaction

`IdempotencyKeyMismatch` derives from `ValueError`: the caller passed a key that
does not belong to this input. It is raised from a `SELECT`, before any write,
so the caller's transaction remains usable and can roll back cleanly. That is
the opposite of every failure in #661, all of which abort the transaction —
worth stating because #663 is the consumer, and a conflict it can answer without
retrying the whole transaction is a different case from a serialization failure
it must.

Everything else stays untranslated, per #661. In particular an `IntegrityError`
on the record `INSERT` means the head lock failed to serialize two commands with
one key — a bug or an out-of-band writer — and the constraint names that better
than a wrapper would.

### `append_events` is deleted

#661 shipped `append_events(library, events, ...)` as a convenience for commands
with nothing to validate. `idempotent_append(..., build=lambda _: events)` now
covers that case, and leaving a non-idempotent convenience in the package gives
a command author in #664 an easy way to write a command that silently cannot
deduplicate.

Deleting it does not remove the ability to append without a record: `lock_stream`
and `LockedStream.append` remain the primitives, and #666's replay and #671's
backfill are expected to use them. It removes the *convenient* way, which is
what a footgun is. There are no callers outside `tests/test_event_append.py`.

## Schema

`LibraryIdempotencyRecord`, migration `0024`.

| Field | Type | Note |
| --- | --- | --- |
| `id` | `UUIDv7Field(primary_key=True)` | |
| `library` | `ForeignKey(UserLibrary, CASCADE)` | `related_name="idempotency_records"` |
| `idempotency_key` | `CharField(max_length=255)` | same width as the event column |
| `request_fingerprint` | `CharField(max_length=64)` | sha256 hex |
| `first_sequence` | `PositiveBigIntegerField` | |
| `last_sequence` | `PositiveBigIntegerField` | |
| `created_at` | `DateTimeField(default=timezone.now, editable=False)` | |

| Constraint | Kind |
| --- | --- |
| `unique_library_idempotency_key` on `(library, idempotency_key)` | unique |
| `library_idempotency_first_sequence_positive` | check `first_sequence >= 1` |
| `library_idempotency_range_ordered` | check `last_sequence >= first_sequence` |
| `library_idempotency_key_not_empty` | check |
| `library_idempotency_request_fingerprint_not_empty` | check |

Manager is `LibraryOwnedQuerySet.as_manager()`, matching `LibraryEvent`.

**No stream foreign key.** `claim` runs under the lock and already holds
`LockedStream.stream_id`; a column would be a third copy of a fact the head and
the events both carry.

**No `identity_audit.py` registration.** The table's UUID order source is
`created_at`, which is `DEFAULT_ORDER_SOURCE`, and its only relation column is
`library_id`, already a `uuid_v7`. `make audit-uuid-identity` should pass
untouched.

**The migration is reversible, and must not copy #660's rollback guard.**
Migration `0023` refuses reversal because dropping the event tables destroys the
only copy of that history. This table is not that: as shown above, the key→range
map is reconstructible from `games_libraryevent` by grouping. Reversing loses
the fingerprints, which weakens mismatch rejection for pre-existing keys and
nothing else. Adding `0023`'s guard here would be cargo cult — it is the obvious
wrong move, so it is named.

## API contract

```python
type IdempotencyKey = str  # "session-create-01J8Z3K4M5N6P7Q8R9S0T1U2V3"
type RequestFingerprint = str  # "9f86d081884c7d65…" (sha256 hex)


class IdempotencyKeyMismatch(ValueError): ...


@dataclass(frozen=True, slots=True)
class ReplayedAppend:
    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int


def fingerprint_command_input(
    command_input: Mapping[str, Any],
) -> RequestFingerprint: ...


def idempotent_append(
    library: UserLibrary,
    *,
    idempotency_key: IdempotencyKey,
    request_fingerprint: RequestFingerprint,
    build: Callable[[LockedStream], Sequence[NewEvent]],
    actor: User | None,
    correlation_id: uuid.UUID,
    source_metadata: SourceMetadata | None = None,
    recorded_at: datetime | None = None,
) -> AppendResult | ReplayedAppend: ...
```

`games/events/idempotency.py`, a sibling of `append.py` — #661 made
`games/events/` a package so #662–#666 each add one.

A `build` returning no events raises `ValueError` from `append`, and no record
is written, so the key stays usable. A command that records nothing must not
claim a key.

## Where the behaviour is pinned

`tests/test_event_idempotency.py`, plus edits to `tests/test_event_append.py`
for the deleted convenience.

Ordinary `django_db` tests: a fresh append writes exactly one record carrying
the returned range · a repeat with the same key and fingerprint returns
`ReplayedAppend`, appends nothing, and leaves `current_sequence` unchanged · the
repeat does not call `build` (a callback that records whether it ran) · a repeat
with a different fingerprint raises `IdempotencyKeyMismatch`, writes nothing,
and leaves the transaction usable for a subsequent successful append · one key
in two libraries is two independent records · a rolled-back command leaves
neither events nor record, and the key works afterwards · a multi-event command
writes N events and one record whose range spans them · `build` returning `[]`
raises `ValueError` and writes no record · a directly-inserted duplicate record
raises `IntegrityError`, proving the constraint is the backstop and not the
mechanism.

`fingerprint_command_input`: stable across key order · differs when any value
differs · accepts `UUID`, `datetime`, `Decimal` · raises `TypeError` for
anything else, including an object whose only serialization would be its
`repr()`.

One `django_db(transaction=True)` test — **concurrent duplicate**: two threads
issue the same key against one library, forced to overlap with the
`connection.execute_wrapper` harness #661's tests already use
(`tests/test_event_append.py`, itself following
`tests/test_library_conversion.py:819`). Assert the library holds N events, not
2N, one record, and that both callers received the same sequence range. Every
wait carries a timeout and every thread calls `close_old_connections()` in a
`finally`, for the reasons #661 recorded: an unbounded barrier hangs the suite
instead of failing it, and a leaked open transaction blocks
`TransactionTestCase` truncation.

One more `django_db(transaction=True)` test pins the **reversible** migration,
using the `MigrationExecutor` harness `tests/test_event_schema_migration.py`
already established: with a record present, reversing `0024` succeeds. That is
the behavioural difference from `0023`, which refuses, and it is the assertion
that stops a future reader from adding the guard.

`tests/test_event_append.py` loses `test_convenience_function_matches_the_primitive`
and its local `append` helper switches to `lock_stream(library).append(...)`.

## What this shape forecloses

- **Idempotency without a record.** Every deduplicated command writes a row that
  lives as long as its events. The table grows one row per command, forever;
  pruning is not offered, because a pruned key becomes executable a second time.
- **Cross-library keys.** A key is scoped to one library by the unique
  constraint. Two libraries may use the same string, and no command can
  deduplicate across libraries.
- **Deduplicating a command that appends nothing.** No events, no record, no
  protection. A command whose only effect is on a projection is outside the
  event boundary and outside this mechanism.
- **Answering a duplicate without waiting.** A duplicate arriving while the
  original is in flight blocks on the head lock rather than failing fast.
- **Explaining a mismatch.** The record stores a hash, so a rejection can say
  the input differs but never which field.
- **A non-idempotent convenience.** `append_events` is gone; a caller that wants
  it composes `lock_stream` and `append` explicitly.

## Verification

`make check` — the full gate including `e2e/`. `make audit-uuid-identity`
separately, to confirm the new table needs no registry entry.
