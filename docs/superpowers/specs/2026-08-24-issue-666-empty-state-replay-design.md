# Deterministic empty-state replay

[#665](https://github.com/KucharczykL/timetracker/issues/665) runs an appended
event through the projector registry, and
[#914](https://github.com/KucharczykL/timetracker/issues/914) fixed what a family
is handed: a `RecordedEvent`, the envelope by value. Both operate on events the
current transaction just wrote. Nothing can take a stream that already exists and
replay it again.

This issue adds that read. It is the property the
[overhaul architectural charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
states as "Projections are rebuildable and tested against a replay from an empty
state", and the machinery every later rebuild is built on.

## What it is

One function. It reads a library's stream in sequence order, converts each row to
a `RecordedEvent`, and runs it through a registry -- the same value, in the same
order, through the same call as an append. Streaming, so a hundred-thousand-event
stream costs the application under a megabyte rather than 223 MB, and bounded, so
it can say exactly which prefix of the stream it covered.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| Shadow projection tables, the rebuild that fills them, the atomic swap | #667 |
| The check that nothing appended during a rebuild | #901 |
| Event-type registry and payload schema validation | #900 |
| Real projector families and the projection tables they write | #671 |
| Blocking direct writes to event-sourced projections | #737 |
| Rebuild benchmarking against the charter's 60-second budget | #670 |
| A per-append aggregate phase | #913 |

This issue owns the bounded ordered read, the contiguity contract, the replay, and
the result value.

**It empties nothing.** "From an empty state" is the caller's precondition, not
this function's behaviour: the only caller that will ever have a real empty state
to offer is #667's shadow rebuild, and the reset hook that would enforce it has to
be designed against real families and real tables, neither of which exists.
Parity is therefore proven the way #665 and #914 proved theirs -- against families
declared in the test module, registered into a registry the test module owns.

## Preconditions

- `LockedStream.append` (#661) is the single writer, holds the head lock for the
  caller's transaction, and assigns contiguous sequences from
  `LibraryEventStreamHead.current_sequence`.
- `RecordedEvent.from_row` (#914) copies all sixteen concrete fields, carries the
  three relations as ids, and **refuses a deferred row**.
- `ProjectorRegistry.apply` (#665) resolves handlers by event type, runs them in
  `ProjectorFamily` order, and annotates a handler's exception with `add_note`
  rather than wrapping it.
- `canonical_json` (#665) guarantees a stored payload is what PostgreSQL returns,
  which is what makes an append-time and a replay-time value comparable at all.

### Measured, not assumed

A probe built one library a hundred thousand events and replayed them through an
empty registry, on PostgreSQL 18:

| Read | Time | Queries | Peak allocation |
| --- | --- | --- | --- |
| `.iterator(chunk_size=500)` | 1.72 s | 1 | **0.96 MB** |
| `.iterator(chunk_size=2000)` | 1.74 s | 1 | 4.15 MB |
| `.iterator(chunk_size=10000)` | 1.74 s | 1 | 22.0 MB |
| no `.iterator()` at all | 2.01 s | 1 | **223.3 MB** |

Three results decide the design.

**Chunk size buys no time.** A twentyfold change moves the replay by 2%, which is
inside the noise; it moves memory by a factor of twenty-three. The knob is
therefore not a knob.

**The bound is free.** `sequence <= current_sequence` and no bound at all produce
the identical plan -- an index scan on `unique_library_event_stream_sequence`, no
sort, 18 ms of database time for 100k rows -- and the identical replay time. The
snapshot semantics below cost nothing to buy.

**The replay is not where the time goes.** Of 17.4 µs per event, the ORM row
hydration is roughly 15 and `from_row` under 3. A rebuild's budget will be spent
by families, not by this read: 1.74 s of the charter's 60 s, with every projector
still to come.

**`.iterator()` streams the client, not the server.** Django's PostgreSQL backend
declares its server-side cursor `withhold=connection.autocommit`, so replay --
which owns no transaction -- gets a `WITH HOLD` cursor, and PostgreSQL
materializes the whole result at `DECLARE`. Measured over the same 100k events:
52 ms to the first row in autocommit against 3 ms inside `atomic()`, one holdable
cursor visible in `pg_cursors`, and no temp-file spill at that size. The client
memory figures above are real and so is the single query; the server does the
work up front either way. A caller wanting a non-holdable cursor wraps the call
in `atomic()`, which is a choice it already has.

One further measurement, because it overturns the obvious optimisation:
constructing the value from a `.values(...)` mapping instead of a model instance
is **1.45× faster** (12.7 µs against 18.3 µs per event at 20k) and produces
values that compare **equal**. It is rejected below.

## Design

### `replay(library, *, registry)`

```python
def replay(
    library: UserLibrary, *, registry: ProjectorRegistry = DEFAULT_REGISTRY
) -> ReplayResult
```

One function that replays, in `games/events/replay.py` -- the read counterpart of
`append.py`, and the only other place the replay loop is written.

The alternatives both split the read from the replay: a `StreamReplay` object
exposing an iterator beside a `replay`, or a bare generator with the loop left to
callers. They are more flexible and neither is worth it. The replay's shape --
event-major, one `registry.apply` per event, `RecordedEvent.from_row` as the sole
constructor -- **is** the parity property this issue exists to establish. Handing
it out as a two-line idiom for callers to retype is how it drifts. #667, the only
planned caller, wants exactly what this signature returns: replay into a registry,
learn which prefix was covered.

The `registry` parameter defaults the way `policy` and `registry` already default
through `dispatch` → `idempotent_append` → `append`, so a test drives its own
families and #667 will pass a registry pointed at shadow tables.

### The read is bounded by the head, and that is the snapshot

```python
head = LibraryEventStreamHead.objects.filter(library=library).first()
bound = head.current_sequence
events = (
    LibraryEvent.objects.filter(stream_id=head.id, sequence__lte=bound)
    .order_by("sequence")
    .iterator(chunk_size=REPLAY_CHUNK_SIZE)
)
```

Read the head first, replay everything at or below what it said. Events are
immutable and append-only, so that bound is a consistent snapshot without a lock,
without a transaction, and without repeatable-read isolation. A concurrent append
lands above the bound and is simply not this replay's.

The two alternatives each cost more than they return. Demanding the caller's open
transaction -- the rule `lock_stream` enforces -- would buy PostgreSQL's snapshot
instead of an argument about immutability, at the price of holding one
transaction across an entire rebuild, and would *still* need a sequence bound to
report what it covered. Locking the head with `select_for_update` would be the
strongest guarantee and would block every write to the library for the length of
the rebuild, which forecloses the online shadow-and-swap that is the whole point
of #667.

`ReplayResult.replayed_through` carries the bound outward, so a caller can compare
it against the head afterwards. #667's swap and #901's concurrency check are both
that comparison; neither belongs here.

**Replay states no quiescence postcondition.** A projector that appended
mid-replay, or a command running concurrently, is not detected. Re-reading the
head at the end and refusing when it moved would catch both -- and would fire on
precisely the case #667 is specified to support, an online rebuild against a
library still taking writes. Reporting the drift without refusing is the same
information the caller already has from `replayed_through`, plus a field that goes
unchecked.

### Streaming, at a size nobody chooses

```python
#: Chunk size is a memory decision, not a speed one: 500 and 10000 replay 100k
#: events within 2% of each other, at 0.96 MB against 22 MB.
REPLAY_CHUNK_SIZE = 500
```

A module constant rather than a parameter. The measurement says tuning it cannot
help, so a parameter would only let a caller choose worse or let a test pin a
number that means nothing. #667 may change the constant if a real family changes
the arithmetic.

`.iterator()` itself is not optional. Without it the read is 223 MB for 100k
events and grows linearly, which is the difference between a rebuild that runs
beside a live application and one that must not.

`.only()` and `.defer()` are unavailable, not merely unused: `from_row` reads all
sixteen fields and refuses a deferred row, because a deferred attribute is a real
round trip and selecting fewer columns would cost up to fourteen extra queries per
event. `select_related` is unnecessary for the mirror-image reason -- the value
carries relations as ids and nothing downstream can traverse -- so the read needs
no joins at all.

### The replay is the append's run

```python
for row in events:
    event = RecordedEvent.from_row(row)
    ...
    registry.apply(event)
```

Event-major, one `registry.apply` per event, in sequence order. `append` does the
same thing to rows it just wrote. Parity is therefore structural: the two paths
differ in where the row came from and in nothing else, which is what #914's
single-event assertion -- a value built from an appended row equals one built from
the same row re-read -- says about every event in a stream.

This is also why the `.values(...)` construction is rejected despite being 1.45×
faster and demonstrably equal today. `RecordedEvent(**mapping)` is the `**dict`
form #914 already turned down: mypy checks nothing through it, so a column added
to `LibraryEvent` becomes a `TypeError` inside a rebuild rather than a named test
failure, and the deferred-row guard is bypassed entirely. It would also make two
construction paths where the whole design rests on there being one. The saving is
0.6 s against a 60 s budget.

### A gap is an error, named at the gap

Each event's sequence must be the previous plus one, starting at one, and the
last must equal the bound. Anything else raises `StreamNotContiguous`, naming the
sequence that is missing.

The single writer, the head lock, and the unique `(stream, sequence)` constraint
make a gap impossible through the supported path, so this guards a partial
restore, a manual deletion, or a future writer that gets it wrong. That is
exactly when it matters: a stream with a hole rebuilds quietly into projections
that no append path ever produced, and there is nothing in the resulting rows to
tell anyone. The check is one integer comparison per event -- unmeasurable beside
17 µs of row hydration -- and converts a silent wrong rebuild into a failure at
the first missing sequence.

Checking only the final count would catch the same two faults for even less, and
report "expected 40,000, replayed 39,999" without saying where.

`StreamNotContiguous` derives from `Exception` and deliberately not from
`IntegrityError` or `OperationalError`. It would in fact survive
`run_in_transaction`, whose retry decision reads `error.__cause__.sqlstate` and
declines anything without one -- but those two types are the funnel that
classifier catches on, and every other reader of them (`except IntegrityError`
around a command, a log filter) would take a damaged stream for a database
conflict.

Events before the gap have already been applied and stay applied. Replay owns no
transaction, so it cannot offer all-or-nothing; a caller wanting that wraps the
call in `atomic` -- 1.74 s for 100k events -- and #667, which builds into shadow
tables it is about to discard on failure, does not need to.

The read is closed on the way out. The `.iterator()` generator is wrapped in
`contextlib.closing`, so a gap, a raising projector, or any other unwinding leaves
no cursor behind: in autocommit that cursor is `WITH HOLD`, which outlives its
transaction by design and would otherwise sit on the connection until the
generator is finalized -- and a propagating exception keeps the frame that holds
it alive for as long as anything holds the exception.

### A library that never appended replays to nothing

`ReplayResult.stream_id` is `uuid.UUID | None`. No head means the library has
never appended, which is a legitimate empty stream rather than an error: the
result is `(None, 0)` and **no head row is created**. Replay is a read, and a
read that provisions rows is a read nobody can run safely.

A head sitting at sequence zero is the same answer with the stream's id.

### The result carries the bound and nothing derivable from it

There is no `event_count`. The contiguity contract makes the sequences exactly
`1..replayed_through`, each once, so a count would equal `replayed_through` for every
stream that does not raise -- a second field that can only ever agree with the
first, and that a reader would eventually be tempted to check against it.

### Isolation comes from the head

The filter is `stream_id=head.id`, where the head was fetched by library. This is
enforced rather than conventional: migration `0023_library_event_schema` adds a
composite foreign key from `(stream_id, library_id)` to the head's
`(id, library_id)` -- via `RunSQL`, so it is invisible in `models.py` -- and
PostgreSQL refuses an event pairing one library's stream with another's library.
A stream id therefore already implies its library, and filtering on `library_id`
too would restate a constraint the database keeps.

### The read follows the default connection

`replay` reads through the default manager rather than routing explicitly the way
`append` and `retry` reach for `router.db_for_write`. No router exists, so this
is inert today. It is worth stating because the snapshot argument assumes a
primary read: against a replica, `current_sequence` would be a lagged bound, and
`replayed_through` would name a prefix newer than the replica actually holds.

### A projector's exception passes through untouched

`registry.apply` annotates with the family, the event type, and the sequence, then
re-raises. Replay adds nothing -- no wrapping, no second note, no partial-progress
report. A caller sees the same exception, of the same type, with the same
`__cause__`, as it would have seen from the append that first applied that event.

## API contract

```python
# games/events/replay.py

#: Chunk size is a memory decision, not a speed one.
REPLAY_CHUNK_SIZE = 500


class StreamNotContiguous(Exception):
    """A stream missing a sequence, or ending before its head says it does."""


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Which prefix of which stream was replayed."""

    #: None when the library has never appended: an empty stream, not an error.
    stream_id: uuid.UUID | None
    replayed_through: int


def replay(
    library: UserLibrary, *, registry: ProjectorRegistry = DEFAULT_REGISTRY
) -> ReplayResult: ...
```

Nothing existing changes. No new module is imported by `append`, `dispatch`,
`idempotency`, or `projection`; `replay` imports them.

## Where the behaviour is pinned

`tests/test_event_replay.py`, new. Families are declared at module level against
a registry the module owns, as `tests/test_event_projectors.py` established.

Parity and determinism:

- **replay parity**: dispatch a command appending several events, capture the
  `RecordedEvent`s the append run saw, then replay into a fresh recorder and
  assert the two lists are equal -- every field of every event, in order. This is
  the issue's acceptance criterion as one assertion.
- **determinism**: two consecutive replays produce identical recordings
- several families handling one event type all run, in `ProjectorFamily` order,
  event-major across a multi-event stream
- an event type no family handles is replayed and applied to nothing

The read:

- **exactly two queries regardless of event count** (`django_assert_num_queries`):
  the head, and the cursor. Pinned at two stream lengths so an N+1 introduced later
  cannot pass
- `replayed_through` equals the head's sequence at call time; events appended after
  that are not replayed and need a second replay
- a second library's stream is not replayed

Damaged and empty streams:

- deleting a middle event raises `StreamNotContiguous` naming the missing
  sequence, and the families applied everything before it
- deleting the last event raises, naming the sequence the head promised
- a head at sequence zero replays nothing and returns that stream id
- a library with no head returns `(None, 0)` and creates no head row

Errors:

- a handler raising propagates with its type intact and its notes naming the
  family, the event type, and the sequence

## What this shape forecloses

**Catch-up replay from a sequence.** There is no `from_sequence`, so a projection
that fell behind cannot be advanced -- only rebuilt from one. Adding the parameter
is trivial; deciding what it means is not, because "replay events 5,000 onward" is
only correct against a target that already holds the first 4,999, which is a
claim replay cannot check. #667 owns rebuild, and a real catch-up needs a stored
per-projection position first.

**Rebuilding a whole database.** Replay takes one library. A caller wanting all of
them writes the loop, and the loop is where the interesting decisions live --
ordering, failure handling, parallelism -- none of which this issue can answer
without a real rebuild consumer.

**Progress and cancellation.** A hundred-thousand-event replay is 1.74 s of read;
when families make it minutes, #667 will want a callback or a generator, and will
know what it should report.

**Reading events without projecting.** No public iterator, deliberately: the
constructor and the loop stay in one place.

**Quiescence.** Covered above; the bound is the answer, and #901 owns the check.

**All-or-nothing.** Replay owns no transaction. A caller may wrap it; nothing here
promises it.

## Verification

Full `make check` -- lint, format-check, mypy, ts-check, vitest, and the entire
pytest suite including `e2e/`.

No migration, no schema change, no data change, no new dependency. Nothing
existing changes behaviour, so reversibility is `git revert` and the only thing
lost is the new module.

## Follow-up issues

None. Every deferral above already has an owner in #601's tracker.
