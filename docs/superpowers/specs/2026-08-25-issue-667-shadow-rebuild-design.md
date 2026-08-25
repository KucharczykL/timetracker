# Shadow projection rebuild and atomic swap

[#665](https://github.com/KucharczykL/timetracker/issues/665) folds an appended
event through the projector registry.
[#666](https://github.com/KucharczykL/timetracker/issues/666) folds a stream that
already exists, bounded by its head.
[#901](https://github.com/KucharczykL/timetracker/issues/901) lets a locked
stream refuse an expectation the head has passed. Each is a piece of a rebuild;
none of them rebuilds anything, because a fold with nowhere else to write lands
in the live tables the application is serving.

This issue adds the somewhere else. It is the charter's line "Projection rebuild
writes to shadow tables while normal reads continue. Writes for the affected
library are paused only for final validation and the atomic projection swap; a
failed rebuild leaves the old projection active."

## What it is

One function, `rebuild_projections(library, mode=...)`, and one thin management
command over it. Per attempt it creates an empty shadow copy of every projection
table, replays the library's stream into it through #666's `replay`, diffs the
result against the live rows, and -- in rebuild mode -- swaps the diffed rows into
place in a single transaction that first asserts no event landed while it worked.

Nothing here is speculative machinery waiting for a consumer to justify it:
[#671](https://github.com/KucharczykL/timetracker/issues/671) cannot ship its
cutover without an empty-replay parity gate, and this is that gate's tool.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| Real projector families and the projection tables they write | #671 |
| Durable reference snapshots, and validating that references resolve | #668 |
| The 60-second/100k-event rebuild budget, measured | #670 |
| Blocking direct projection writes outside a rebuild | #737 |
| The optional expected-sequence check itself | #901 (delivered) |
| The bounded ordered read and the fold | #666 (delivered) |

This issue owns the shadow tables, the redirection that makes a family write
them, the projection-model contract that makes a rebuilt row comparable to a live
one, the diff, the swap, the conflict redo, and the report.

## Preconditions

- `replay(library, *, wiring)` (#666) folds `1..head.current_sequence` in
  sequence order, takes no transaction, and returns `folded_through`.
- `LockedStream.require_sequence(expected)` (#901) reads the head row under the
  lock and raises `StreamSequenceMismatch` -- a `CommandConflict`, and neither an
  `IntegrityError` nor an `OperationalError`, so `run_in_transaction` will not
  retry it.
- `EventWiring` (#664) carries `projectors`, `event_types` and `retry_policy`,
  and `replay` already accepts `wiring=`, which is the seam this issue uses.
- `RetryPolicy.delay_for` (#663) is full jitter over a doubling bound, with
  `sleep` and `random` as fields so a test asserts on real delays.
- `games/projectors/` is empty. Every family and table below is declared by a
  test module, as #665, #666 and #914 each established.

### Measured, not assumed

Probed against this project's PostgreSQL 18, since the whole design rests on what
`LIKE` copies and what a temp table will accept:

| Question | Answer |
| --- | --- |
| Does `LIKE ... INCLUDING ALL` copy foreign keys? | **No.** The shadow got its primary key, its `NOT NULL` constraints and its indexes, and no `contype = 'f'` row at all |
| Does it copy indexes? | Yes, renamed to the new table (`probe_live__shadow_library_id_idx`) |
| Does a generated column stay generated? | Yes -- `attgenerated = 's'` on the shadow |
| Does the shadow accept a dangling foreign-key value? | Yes; nothing enforces the reference until the swap inserts into live |
| Is a temp table found ahead of a public one of the same name? | Yes -- `current_schemas(true)` is `['pg_temp_40', 'pg_catalog', 'public']` |
| Does the ORM work against a temp table? | Yes, through a `managed = False` model whose `db_table` names it |
| Can `INSERT ... SELECT` carry a generated column? | **No** -- `cannot insert a non-DEFAULT value into column "doubled"`. Omitting it recomputes the same value: 5 in, 10 out, both sides |
| Are Django's foreign keys deferrable? | **Yes**, every one: `condeferrable` and `condeferred` are both true |

Two of these decide details below. Generated columns must be left out of the
swap's column list, and are then correct by recomputation. Deferred foreign keys
mean a delete-then-insert inside one transaction needs no dependency ordering at
all, self-references included -- violations surface at `COMMIT`.

## Design

### `rebuild_projections(library, *, mode, wiring)`

```python
def rebuild_projections(
    library: UserLibrary,
    *,
    mode: RebuildMode = RebuildMode.CHECK,
    wiring: EventWiring = DEFAULT_WIRING,
) -> RebuildReport
```

In `games/events/rebuild.py`. One attempt is five phases:

1. create an empty shadow table for every projection table;
2. replay the stream into a registry pointed at those tables, with the live-write
   guard armed;
3. diff shadow against live, for this library;
4. in `REBUILD` mode, swap under the stream lock;
5. drop the shadow, on every path.

`CHECK` is the default, so the destructive mode is the one an operator types out.
Both modes run phases 1--3, which is what makes the diff trustworthy: the answer
`check` gives is produced by the same code that would have swapped.

The `wiring=` parameter defaults exactly as `dispatch` and `replay` already
default theirs, and is how a test drives its own families, event types and retry
policy.

### `ProjectionModel`: what a rebuild owns

An abstract model in `games/models.py`, carrying the one column a rebuild
requires:

```python
class ProjectionModel(models.Model):
    library = models.ForeignKey(UserLibrary, on_delete=models.CASCADE, ...)

    class Meta:
        abstract = True
```

Being an event-sourced projection is structural rather than declared. The
alternative -- each family listing the models it writes -- puts the declaration
next to the handlers, and drifts: a family that writes a table it forgot to list
leaves that table's old rows in place through the swap, producing a projection
that is part rebuild and part history, with nothing in the rows to say so. A base
class cannot be forgotten by the code that inherits it.

Discovery is `apps.get_models()` filtered on `issubclass`, not
`ProjectionModel.__subclasses__()`: the app registry is complete after startup,
while `__subclasses__` sees only what has been imported and would make a rebuild's
scope depend on import order.

The mandatory `library` foreign key is what makes the swap expressible as
`WHERE library_id = %s` per table. A projection scoped to a library only
indirectly -- through a parent projection row -- is therefore not supported; a
child table carries its own `library` column and denormalises. That is a rule
#671 must design against, and it buys a swap that is one statement per table with
no join and no recursion.

Abstract, so **this issue adds no migration and changes no schema.**

### A projection row is a pure function of the events

The diff below compares every column of every row. That is only meaningful if
replaying the same events twice produces the same rows, so the contract is
stated here and enforced by a Django system check over every `ProjectionModel`
subclass, which refuses:

- `auto_now` and `auto_now_add` -- wall-clock at projection time;
- a field default of `uuid.uuid4` (and `uuid1`) -- a fresh identity per rebuild.

A family needing a timestamp takes it from the event (`recorded_at`,
`effective_time`); a family needing an identity derives it from event data
(`aggregate_id`, `correlation_id`, or `uuid5` over them).

The check is what makes the rule mechanical rather than advisory, and it runs in
`make check` through the test suite. Without it the failure mode is a rebuild
whose diff is never empty for reasons no operator can distinguish from real drift.

The rule has a second consequence worth stating plainly: **a projection row id is
reproducible, so anything outside the projection may reference it.** Under the
rejected alternative -- ignore volatile columns in the diff, carry live ids across
on matching rows -- the swap becomes a merge, every family declares a natural key,
and the guarantee weakens from "a rebuild reproduces the projection" to "up to
some columns".

### Redirection: a family writes through its target

```python
class ProjectionTarget(Protocol):
    def model[M: ProjectionModel](self, model: type[M]) -> type[M]: ...
```

`LIVE_TARGET.model(X)` returns `X`. `ShadowTarget.model(X)` returns a generated
class with the same fields, `managed = False`, and `db_table = "<table>__shadow"`,
cached one per live model per process so repeated rebuilds do not churn the app
registry.

A family holds one: `Projector.__init__` takes `target: ProjectionTarget =
LIVE_TARGET` and stores it, and `ProjectorRegistry.for_target(target)` returns a
sibling registry whose families are re-instantiated against it. `DEFAULT_REGISTRY`
and every existing call are unchanged; the registry keeps the classes it
registered so it can build the sibling.

A family therefore never imports its projection model. It writes
`self.target.model(PlayerGameState).objects...`, and the rebuild replays through
`replace(wiring, projectors=wiring.projectors.for_target(shadow))`.

A shadow class is built by deep-copying each concrete field of the live model
onto a fresh `models.Model` subclass with `managed = False`, `app_label =
"games"` and the shadow `db_table`. Three details are load-bearing and belong in
the plan rather than being discovered during it. A field instance belongs to one
model, so the copies are real copies. Every copied relation gets
`related_name="+"`, or the reverse accessor collides with the live model's on
`UserLibrary` and Django raises a system-check error at import. And subclassing
the live model is not available: a concrete subclass is multi-table inheritance,
which adds a parent link and writes two tables.

The signature says `type[M]` and the returned class is not an `M`. That is a
deliberate cast, stated here so nobody removes it as a mistake: the class carries
the same fields under the same names, which is what every caller uses it for, and
the alternative -- a protocol describing "a model with these fields" -- cannot be
written for a model whose fields are only known at runtime.

This is the seam `projection.py` already documented -- "a rebuild can eventually
assemble a set of families pointed somewhere other than the live tables" -- made
real. The two alternatives were a second database connection whose `search_path`
selects a shadow schema, and a contextvar the model manager consults. The
`search_path` route needs no cooperation from families and makes a live write
physically impossible, but pays for it with cross-connection visibility that
forces every test to `transaction=True`, a router keyed on a contextvar anyway,
and schema-cloning DDL. The contextvar-in-the-manager route is action at a
distance in the one place where being able to read what a handler writes matters
most.

Two contract terms fall out, both for #671:

- **A family reads only the library it is projecting.** Its shadow holds that
  library and nothing else, so a cross-library read that works live returns
  nothing during a rebuild.
- **A family reads its own projections through the target too**, not only writes.
  The journal and statistics families read current-state rows written earlier in
  the same fold; during a rebuild those rows are in the shadow.

### The shadow tables are temp tables

```sql
CREATE TEMP TABLE "<table>__shadow" (LIKE "<table>" INCLUDING ALL)
```

One per projection table, on the rebuild's own connection. Temp tables are
invisible to every other session, so two libraries rebuild concurrently with no
lock, no name collision and no reaper; they vanish when the connection closes, so
a crashed rebuild leaves nothing behind; and they are found ahead of the public
schema by an unqualified name, which is what makes a `managed = False` model with
`db_table = "<table>__shadow"` resolve to them.

They start empty, which is not a detail: "rebuildable and tested against a replay
from an empty state" is the charter property, and here the empty state is a
physical fact rather than a precondition someone must remember to establish.
#666 stated explicitly that it empties nothing and that its only planned caller
would bring a real empty state. This is that caller.

`LIKE ... INCLUDING ALL` brings the defaults, the check constraints, the
generated-column expressions and the indexes, and leaves the foreign keys behind.
Both halves are wanted. The indexes matter because a family reads back rows it
just wrote, at whatever selectivity the live table was designed for. The absent
foreign keys matter because a shadow with references to live catalog rows would
otherwise have to be built in dependency order, and because the reference that
must hold is the one in the live table after the swap, which is checked there.

A durable `UNLOGGED <table>__shadow` per table would let an operator inspect a
failed rebuild's staged rows, and costs a permanent twin of every projection
table that migrations must keep in step, plus an advisory lock to keep two
rebuilds apart. Per-run named tables buy the same inspection and add orphan
cleanup. The diagnostics an operator actually needs are in the report, and the
report survives the connection.

Two environment caveats, neither live today. Temp tables do not survive a
connection-pooler's session boundary, the same class of hazard #917 records for
`WITH HOLD` cursors, and no deployment runs a pooler. And a persistent connection
(`CONN_MAX_AGE`) outlives one rebuild, which is why phase 5 drops the tables
rather than trusting the disconnect.

### The replay is #666's replay

No second fold loop. `replay(library, wiring=shadow_wiring)` runs outside any
transaction, exactly as designed: the head it read bounds it, an event landing
above that bound belongs to a later replay, and `folded_through` comes back as the
expectation the swap will assert.

Everything #666 refuses, this inherits: a stream with a hole raises
`StreamNotContiguous` and the rebuild fails with the shadow discarded; a payload
no schema can read raises `PayloadVersionUnsupported`; a family's exception
propagates with its own type and its `add_note` naming the family, the event type
and the sequence.

### The write guard

`pre_save` and `pre_delete` receivers on every `ProjectionModel` subclass, armed
by a contextvar for the duration of phase 2, in the rebuilding process only.
A family that reaches past its target -- importing its model, or holding a
reference from another family -- raises there, naming the model, instead of
writing production rows during a rebuild that is supposed to be invisible.

Outside a rebuild the receivers are inert. Making them always-on would give
#737's outcome nearly free, and would decide #737's real question -- what the
escape hatch is for data repair, imports and the admin -- with no caller to test
it against.

Concurrency note: the guard is process-local, which is correct. Another process
serving a command for another library must keep writing live projections
throughout; that is the whole point of an online rebuild.

### The diff

Per projection table, the library's live rows against the shadow's, compared on
every column, keyed on primary key. `TableDiff` carries the two row counts,
how many rows are only live, how many only rebuilt, how many differ, and a
bounded sample of keys for each -- enough to act on, bounded so a wholly-drifted
table cannot produce a report nobody can read.

Comparison is done in SQL rather than by pulling both sides into Python: a
`FULL OUTER JOIN` on the primary key with a row-value inequality gives the three
counts and the sample in one query per table, and does not grow with library size
in application memory. Generated columns are included and agree by construction.

`check` mode stops here. `rebuild` mode reports the same diff and then swaps
anyway: drift is the reason a rebuild is being run, so refusing on mismatch would
refuse precisely the case the tool exists for, and an override flag that every
real invocation carries has stopped meaning anything.

### The swap

```python
with transaction.atomic():
    stream = lock_stream(library)
    stream.require_sequence(replayed.folded_through)
    # per table: DELETE FROM "<table>" WHERE library_id = %s
    # per table: INSERT INTO "<table>" (cols) SELECT cols FROM "<table>__shadow"
```

The lock pauses writes for this library and this library alone; every other
library reads and writes throughout, and readers of this library's projections
block only for the duration of the statements above.

Raw DML per table, not `QuerySet.delete()`: the ORM's delete collects objects,
walks cascades and fires per-object signals, all of which are wrong here -- the
cascade is the shadow's job and the signals are the guard's.

`cols` is every concrete column except the generated ones, which PostgreSQL
refuses to be handed and recomputes identically from the columns that are
carried. Order across tables does not affect correctness, because Django creates
every foreign key `DEFERRABLE INITIALLY DEFERRED` and the checks therefore run at
`COMMIT`; self-referencing and mutually-referencing projection tables work for the
same reason. A genuine violation -- a live catalog row deleted mid-rebuild --
raises at commit naming the constraint rather than the row, and rolls the swap
back whole.

`require_sequence` before any statement that writes, so a conflict costs a
rollback of nothing.

One asymmetry with `replay` is deliberate and worth stating: `lock_stream`
provisions the head row when a library has never appended, so a `rebuild` of such
a library creates it. #666 refused to, because a read that provisions rows is a
read nobody can run safely. A rebuild is a writer, and `require_sequence(0)` is
#901's first-class assertion that the library is still empty -- so the swap
empties this library's projection tables and inserts nothing, which is the
correct projection of an empty stream. `check` mode never locks and creates
nothing.

### A conflict redoes the attempt

`StreamSequenceMismatch` means an event landed while the rebuild worked, so the
shadow is a projection of a prefix and the expectation is the one number known to
be wrong. The whole attempt redoes: fresh shadow, fresh replay, fresh
expectation, after `wiring.retry_policy.delay_for(attempt)`. Up to
`retry_policy.retries` attempts, then the report comes back with `swapped=False`
and the conflict recorded, live rows untouched.

`run_in_transaction` cannot be reused for this. It classifies on
`IntegrityError`/`OperationalError` and their SQLSTATE, and would decline a
`StreamSequenceMismatch` -- correctly, because what needs redoing is the replay
outside the transaction, not the transaction.

The two alternatives are visible in the report either way. Reporting the conflict
and leaving the retry to the operator makes a person the loop on exactly the
libraries that are busy enough to need one. Holding the stream lock across the
whole rebuild removes the conflict by blocking every write to the library for the
length of the rebuild, which is the online property the charter, #666 and #901
were each built to preserve.

### The report, and the command

`RebuildReport` is what an operator reads and what every test asserts on: the
library and stream ids, the mode, whether it swapped, `folded_through`, the
per-table `TableDiff`s, and one `RebuildAttempt` per attempt carrying its
`folded_through`, its phase timings and its conflict if it had one.

`manage.py rebuild_projections <library-uuid> [--check]` prints it, in the style
of `audit_uuid_identity` and `delete_user_library`. One library per invocation,
matching `replay` and the swap; an operator sweeping several writes the loop.
#666 drew that line for reasons that have not changed -- ordering, failure
handling and parallelism across libraries have no defensible answer until a real
family exists to make one of them expensive.

Today the command reports zero families and zero tables, because
`games/projectors/` is empty. That is the honest output for the current state and
it exercises every phase; #671 gives it something to say.

## API contract

```python
# games/models.py

class ProjectionModel(models.Model):
    """An event-sourced projection table: rebuilt from events, never authored."""
    library = models.ForeignKey(UserLibrary, on_delete=models.CASCADE, ...)
    class Meta:
        abstract = True


# games/events/projection.py  (additions)

class ProjectionTarget(Protocol):
    def model[M: ProjectionModel](self, model: type[M]) -> type[M]: ...

LIVE_TARGET: ProjectionTarget

class Projector(ABC):
    def __init__(self, target: ProjectionTarget = LIVE_TARGET) -> None: ...

class ProjectorRegistry:
    def for_target(self, target: ProjectionTarget) -> ProjectorRegistry: ...


# games/events/rebuild.py  (new)

class RebuildMode(StrEnum):
    CHECK = "check"
    REBUILD = "rebuild"

class LiveProjectionWriteRefused(RuntimeError): ...

@dataclass(frozen=True, slots=True)
class TableDiff: ...

@dataclass(frozen=True, slots=True)
class RebuildAttempt: ...

@dataclass(frozen=True, slots=True)
class RebuildReport: ...

def rebuild_projections(
    library: UserLibrary,
    *,
    mode: RebuildMode = RebuildMode.CHECK,
    wiring: EventWiring = DEFAULT_WIRING,
) -> RebuildReport: ...
```

Changed elsewhere: `Projector.__init__` gains a defaulted parameter,
`ProjectorRegistry` keeps its registered classes and gains `for_target`,
`games/checks.py` registers the projection-model system check and `GamesConfig`
imports it. No existing behaviour changes.

## Where the behaviour is pinned

`tests/test_projection_rebuild.py`, new. Projection models are declared in the
test module with `app_label = "games"` and created by `schema_editor`, the
pattern `tests/test_uuidv7.py` and `tests/test_temporal_field.py` already
establish; families are declared against a registry the module owns, as
`tests/test_event_projectors.py` established. The models include a parent and a
child projection table with a foreign key between them, so the swap's ordering
claim is exercised rather than asserted.

Parity, which is the acceptance criterion:

- **a live-built projection rebuilds to itself**: dispatch commands, run `check`,
  every `TableDiff` is empty
- **drift is found and repaired**: corrupt a live row, `check` reports it and
  changes nothing, `rebuild` reports it and the live rows afterwards equal the
  rebuilt ones
- **a missing live row and an extra live row** are each reported on the right side
  of the diff, and repaired
- rebuilding twice in a row is a no-op the second time

Isolation:

- a second library's projection rows are untouched by the swap, and its stream is
  never read
- `check` writes nothing: live rows unchanged, and no shadow table survives
- a shadow table is dropped on success, on a family's exception, and on a
  contiguity failure

Concurrency:

- an append that lands between replay and swap produces a conflict, the attempt
  redoes, the second attempt folds the new event and swaps; the report carries two
  attempts and the delays come from the injected policy
- an exhausted budget returns `swapped=False` with the conflict recorded and the
  live rows exactly as they were
- a library that never appended: `rebuild` empties its projections, swaps nothing
  in, and creates the head row `lock_stream` provisions; `check` creates nothing

The contract:

- a family that writes its live model during a replay raises
  `LiveProjectionWriteRefused`, and the live rows are unchanged
- outside a rebuild, writing a projection model directly is allowed (the guard is
  inert -- pinned so that #737's later change is a visible one)
- the system check fires on a projection model with `auto_now`, with
  `auto_now_add`, and with a `uuid4` default, and passes an event-derived model
- a projection table with a generated column rebuilds, and the generated values
  agree

The engine:

- the swap issues one delete and one insert per table regardless of row count
  (`django_assert_num_queries`), pinned at two library sizes
- the report's counts and per-attempt timings are populated
- the management command prints the report and exits non-zero when a `rebuild`
  did not swap

## What this shape forecloses

**Catch-up from a sequence.** A rebuild is always from empty. #666 named the
reason and it stands: folding events 5,000 onward is only correct against a
target holding the first 4,999, which nothing can check without a stored
per-projection position. Nothing here stores one.

**Rebuilding every library.** One library per call. The sweep's decisions --
ordering, stop-or-continue, parallelism -- still have no consumer to answer them.

**A projection scoped indirectly.** Every projection table carries its own
`library` column, so a child table denormalises rather than reaching through its
parent. The swap is one statement per table because of it.

**A projection with a non-reproducible column.** The system check refuses
`auto_now` and generated identity outright. A family that genuinely needs one
would need the diff to grow an exclusion list, which is the design turned down
above.

**Inspecting a failed rebuild's staged rows.** Temp tables are gone with the
connection. The report carries the diff and the failure; the rows do not survive.

**Progress and cancellation.** A rebuild is one call that returns a report. When
real families make a rebuild long enough to want a progress callback, #670's
measurements will say what it should report.

**Two concurrent rebuilds of the same library.** Both are allowed and neither
corrupts the other -- the shadows are private and each swap asserts its own
expectation -- but the second swap overwrites the first with identical rows,
which the pure-function contract makes harmless and which nothing prevents.

## Verification

Full `make check`: lint, format-check, mypy, ts-check, vitest and the entire
pytest suite including `e2e/`.

No migration, no schema change, no data change, no new dependency. `ProjectionModel`
is abstract and has no table; the shadow tables are created and dropped inside
one call. Reversibility is `git revert`, and the only thing lost is the new
module, the abstract base, the system check and the added parameter.

The charter's 60-second/100k-event budget is deliberately not verified here.
Measuring a rebuild that projects nothing measures #666's replay, which #666
already measured at 1.74 s for 100k events. #670 owns the number, against #671's
families.

## Follow-up issues

None to file. Every deferral above is owned by an issue already in #601's
tracker: #671 for families and tables, #668 for reference resolution, #670 for
the budget, #737 for general write blocking, #917 for the pooler caveat.
