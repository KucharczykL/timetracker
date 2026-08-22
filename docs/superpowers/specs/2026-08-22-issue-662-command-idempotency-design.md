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
`MIN(sequence)`/`MAX(sequence)` grouped by `(library_id, idempotency_key)` looks
like it reproduces the range without a new table. It does not, for three
independent reasons, each sufficient:

- The request fingerprint has nowhere to live, so a key reused with different
  input cannot be told from an honest retry, and the charter's second rule
  becomes unimplementable.
- `LockedStream.append` is public and, per #661, may be called more than once on
  one locked stream. Two appends sharing a key with a differently-keyed append
  between them make `MIN..MAX` span another command's events. Nothing in the
  schema forbids this — `idempotency_key` carries only a not-empty check.
- Events written through the raw primitives — #666's replay, #671's backfill,
  and every event appended between #661 and this work — carry keys but claim
  nothing. A derivation would invent records for them and block keys that were
  never claimed.

The last two are also why the derivation cannot be used to justify anything
else, including migration reversibility. It is a false friend, and it is
recorded here so it is not re-proposed.

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

Two requests carrying one key race. The loser blocks inside `lock_stream`; when
the winner commits, the loser's record `SELECT` is a fresh statement taking a
fresh READ COMMITTED snapshot, so it sees the committed record and returns the
original range. A pre-lock read would let both proceed to `build` and rely on
the record's unique constraint to break the tie *after* both had done the work,
aborting the loser's transaction rather than answering it.

**Where the loser blocks depends on whether the library has a head yet, and the
first command takes a different path.** With a committed head, the loser waits
on `SELECT … FOR UPDATE`. With no head — a library's very first command — the
winner's head `INSERT` is invisible to the loser's snapshot, so its
`SELECT … FOR UPDATE` matches zero rows and returns immediately; the loser then
blocks on the `OneToOneField` unique index inside `get_or_create`, recovers
through Django's savepoint, re-selects the now-committed head under the lock,
and reaches the record `SELECT` with everything committed. Same outcome, a
different serialization point. This matters because a test that leaves the head
uncommitted exercises the second path while appearing to test the first — see
the note on #661's contention test below.

Blocking is the desirable behaviour: the wait means the original command is
still in flight, and waiting for it produces the original result instead of a
race. The cost is that a *mismatch* also waits — a conflict response can be
delayed behind an unrelated in-flight command on the same library. #663 owns
whether that is worth surfacing differently.

### The record is written after the append, in the same transaction

Order inside the caller's transaction:

1. `lock_stream(library)`;
2. `SELECT` the record for `(library, idempotency_key)`;
3. found, comparable, and the fingerprint matches → return `ReplayedAppend`,
   **`build` never runs**;
4. found, comparable, fingerprint differs → raise `IdempotencyKeyMismatch`;
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

### `build` is a callback, and the input is hashed here, not by the caller

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
write is not something a caller can omit.

The same reasoning applies one level down, and is why `idempotent_append` takes
`command_input: dict[str, Any]` rather than a precomputed fingerprint. A
`request_fingerprint: str` parameter is a transparent alias — mypy accepts any
string, so a #664 author passing a constant would silently disable mismatch
rejection, and no test in that command's suite would notice. That is the exact
failure the callback exists to prevent; accepting a hash from the caller would
reintroduce it one argument to the right. #664 still decides *what* the
canonical input contains; this module decides that it is hashed and how.

The cost of the callback is that a `build` needing to return something besides
events must close over a variable.

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
the rows of a replayed command has the stream and the range.

### The fingerprint is a versioned hash

`request_fingerprint` is a sha256 hex digest in a `CharField(max_length=64)`,
beside a `fingerprint_version` smallint. The alternative — storing the
canonicalized input as JSONB — buys an operator the ability to see exactly which
field changed, at the price of an unbounded column holding a second copy of user
data outside the event payload, with its own retention and privacy surface. The
hash answers the only question the rule asks: same input, or not.

**The version column is the point.** A bare hash makes the canonicalizer
permanently frozen: any later change to it — adding a type, changing a
separator — turns every stored digest into a mismatch and converts honest
retries into rejections. That is precisely the failure this design cites to
refuse a `repr()` fallback, and it would be self-inflicted. So the module
carries `FINGERPRINT_VERSION`, stamped on every record; a record written under a
different version is **not comparable**, and the claim replays it without
checking. Idempotency — the charter's primary rule — is preserved across a
canonicalizer change; only the mismatch guard degrades, and only for keys
predating the change. The column is free now and expensive once the table is
populated, which is the same argument #660 lost.

`fingerprint_command_input` is the single canonicalizer, so #664 cannot grow a
per-command variant that drifts: sorted keys, no whitespace, and an encoder for
the types a command input actually contains beyond JSON's own. That list is
`uuid.UUID`, `datetime`, `date`, `Decimal`, and `TemporalValue` — verified
against the models rather than assumed. `date` is load-bearing and easy to miss:
`datetime` is a *subclass* of `date`, so an `isinstance(value, datetime)` branch
does not catch `Purchase.date_purchased`, and the branches must be ordered
`datetime` before `date`. `TemporalValue` serializes as its `canonical` string.

Anything else raises `TypeError`, on purpose: a fallback to `repr()` would
silently admit values whose text representation is not stable across processes,
and an unstable hash rejects honest retries.

The parameter is typed `dict[str, Any]`, not `Mapping[str, Any]`. `json`'s
encoder dispatches on `isinstance(o, dict)`; any other `Mapping` falls through
to `default=` and raises, so a `Mapping` annotation would promise an input the
implementation rejects.

### `IdempotencyKeyMismatch` is its own exception, and it spares the transaction

It derives from `Exception` directly, not `ValueError`. `LockedStream.append`
already raises `ValueError` for an empty event sequence, and #663 — the
designated consumer — needs to turn a mismatch into a user-visible conflict
while letting an empty-build programming error surface as a bug. One `except
ValueError` cannot do both.

It is raised from a `SELECT`, before any write. On this path `lock_stream`
performs no write either — a record can only exist if some earlier append
already provisioned the head — so the caller's transaction remains usable and
can roll back cleanly. That is the opposite of every failure in #661, all of
which abort the transaction, and it is worth stating because #663 consumes both
and a conflict it can answer without restarting the transaction is a different
case from a serialization failure it must.

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
#661's spec describes the function in three places and is amended to record that
this issue removed it.

## Schema

`LibraryIdempotencyRecord`, migration `0024`.

| Field | Type | Note |
| --- | --- | --- |
| `id` | `UUIDv7Field(primary_key=True, editable=False)` | `editable=False` is not implied by `primary_key`; #660's tables all carry it |
| `library` | `ForeignKey(UserLibrary, CASCADE)` | `related_name="idempotency_records"` |
| `idempotency_key` | `CharField(max_length=255)` | same width as the event column |
| `request_fingerprint` | `CharField(max_length=64)` | sha256 hex |
| `fingerprint_version` | `PositiveSmallIntegerField` | no default; the writer always states it |
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
| `library_idempotency_fingerprint_version_positive` | check `>= 1` |

Manager is `LibraryIdempotencyRecordQuerySet(LibraryOwnedQuerySet)` with no
added methods, matching `LibraryEventQuerySet` — the convention is a named
per-model queryset even when it is empty.

**No stream foreign key.** `claim` runs under the lock and already holds
`LockedStream.stream_id`.

**No `identity_audit.py` registration.** The table's UUID order source is
`created_at`, which is `DEFAULT_ORDER_SOURCE`, and its only relation column is
`library_id`, already a `uuid_v7`. `make audit-uuid-identity` should pass
untouched.

**The migration is reversible, and must not copy #660's rollback guard.**
Migration `0023` refuses reversal because dropping the event tables destroys the
only copy of the user's history. Reversing `0024` destroys something else: a
key→range map that is *not* reconstructible (see above). It is nonetheless the
right call, because these records are operational metadata rather than
player-authored history. The worst consequence of losing them is that a retry
arriving after an operator-initiated schema rollback executes a second time —
which is the state the system is in today, before this work. Losing the events
has no comparable floor.

This is not in tension with refusing to prune. Pruning would be a routine
background process silently re-opening keys during normal operation; reversal is
a deliberate operator act that removes the feature. Adding `0023`'s guard here
would be cargo cult, so it is named.

## API contract

```python
type IdempotencyKey = str  # "session-create-01J8Z3K4M5N6P7Q8R9S0T1U2V3"
type RequestFingerprint = str  # "9f86d081884c7d65…" (sha256 hex)

FINGERPRINT_VERSION = 1


class IdempotencyKeyMismatch(Exception): ...


@dataclass(frozen=True, slots=True)
class ReplayedAppend:
    stream_id: uuid.UUID
    first_sequence: int
    last_sequence: int


def fingerprint_command_input(
    command_input: dict[str, Any],
) -> RequestFingerprint: ...


def idempotent_append(
    library: UserLibrary,
    *,
    idempotency_key: IdempotencyKey,
    command_input: dict[str, Any],
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

`tests/test_event_idempotency.py`, plus edits to `tests/test_event_append.py`.

Ordinary `django_db` tests: a fresh command writes exactly one record carrying
the returned range and `FINGERPRINT_VERSION` · a repeat with the same key and
input returns `ReplayedAppend`, appends nothing, and leaves `current_sequence`
unchanged · the repeat does not call `build` (a callback that records whether it
ran) · a repeat with different input raises `IdempotencyKeyMismatch`, writes
nothing, and leaves the transaction usable for a subsequent successful command ·
a record stamped with a different `fingerprint_version` replays without
comparing · one key in two libraries is two independent records · a rolled-back
command leaves neither events nor record, and the key works afterwards · a
multi-event command writes N events and one record whose range spans them ·
`build` returning `[]` raises `ValueError` and writes no record · a
directly-inserted duplicate record raises `IntegrityError`, proving the
constraint is the backstop and not the mechanism.

`fingerprint_command_input`: stable across key order, including nested dicts ·
list order is significant · differs when any value differs · accepts `UUID`,
`datetime`, `date`, `Decimal`, `TemporalValue` · raises `TypeError` for anything
else, including an object whose only serialization would be its `repr()`.

The reversible migration is pinned by asserting `0024` contains no `RunPython`
operation, not by a migration-rewind test. Reversal here is a `DROP TABLE`; a
rewind test would spend one of the suite's most expensive shapes proving the
absence of an operation that a direct assertion states.

One `django_db(transaction=True)` test — **concurrent duplicate**: two threads
issue the same key against one library and the library holds N events, not 2N,
with one record and one shared range.

**#661's contention harness cannot be copied for it, and is itself defective.**
`tests/test_event_append.py:296` starts its threads with no committed head, so
the holder's head `INSERT` is invisible to the waiter; the waiter's
`SELECT … FOR UPDATE` matches zero rows and returns without waiting, and the
real serialization happens on the unique index inside `get_or_create`. The test
passes for the wrong reason — the sibling lock-probe test at
`tests/test_event_append.py:272-276` documents exactly this hazard and commits
its head first. The new test commits the head before starting threads, and
#661's test is corrected the same way; that correction is in scope here because
this work would otherwise inherit a harness that cannot observe the mechanism it
claims to prove.

## What this shape forecloses

- **Idempotency without a record.** Every deduplicated command writes a row that
  lives as long as its events. The table grows one row per command, forever;
  pruning is not offered, because a pruned key becomes executable a second time.
- **Cross-library keys.** A key is scoped to one library by the unique
  constraint. Two libraries may use the same string, and no command can
  deduplicate across libraries.
- **Deduplicating a command that appends nothing.** No events, no record, no
  protection.
- **Answering a duplicate without waiting.** A duplicate — or a mismatch —
  arriving while another command holds the head blocks rather than failing fast.
- **Explaining a mismatch.** The record stores a hash, so a rejection can say
  the input differs but never which field.
- **Comparing across canonicalizer versions.** A version bump makes older
  records replay-only; their inputs can never be re-checked.
- **More than one stream per library.** `ReplayedAppend` reaches its events only
  via library → head → `stream_id` + range, because the record stores no stream.
  Sound while the head is a `OneToOneField`, wrong the moment it is not.
- **A non-idempotent convenience.** `append_events` is gone; a caller that wants
  it composes `lock_stream` and `append` explicitly.

## Verification

`make check` — the full gate including `e2e/`. `make audit-uuid-identity`
separately, to confirm the new table needs no registry entry.
