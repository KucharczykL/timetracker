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
  retry it. `require_sequence(0)` is legal; only a negative expectation raises.
- `lock_stream` provisions the head row through `get_or_create` when a library
  has never appended (`games/events/append.py:214`). It is a writer; `replay`
  deliberately is not.
- `EventWiring` (#664) carries `projectors`, `event_types` and `retry_policy`,
  and `replay` already accepts `wiring=`, which is the seam this issue uses.
- `RetryPolicy.delay_for` (#663) is full jitter over a doubling bound, with
  `sleep` and `random` as fields so a test asserts on real delays.
- `games/projectors/` is empty. Every family and table below is declared by a
  test module, as #665, #666 and #914 each established.

### Measured, not assumed

Probed against this project's PostgreSQL 18 and its installed Django, because
most of this design rests on what `LIKE` copies, what a temp table accepts, and
what Django's model machinery does when a model class is manufactured at runtime.

| Question | Answer |
| --- | --- |
| Does `LIKE ... INCLUDING ALL` copy foreign keys? | **No.** Primary key, `NOT NULL` constraints and indexes only |
| Does a generated column stay generated? | Yes -- `attgenerated = 's'` on the shadow -- and `INSERT ... SELECT` **refuses to carry it**: `cannot insert a non-DEFAULT value into column "doubled"`. Omitting it recomputes the same value |
| Does it copy an identity column's sequence? | It gives the shadow **its own**, starting at 1: three live rows at ids 48--50 came back from the shadow as 1--3 |
| Does it copy a `db_default`? | Yes, and PostgreSQL applies it -- a `uuidv7()` column default produced a fresh value in the shadow |
| Does the shadow accept a dangling foreign-key value? | Yes; nothing enforces a reference until the swap inserts into live |
| Is a temp table found ahead of a public one? | Yes -- `current_schemas(true)` is `['pg_temp_61', 'pg_catalog', 'public']`, and it stays visible inside nested `atomic` blocks |
| Does the ORM work against a temp table? | Yes, through a `managed = False` model whose `db_table` names it: insert, select and update all work, including a UUID primary key and a foreign key to a live table |
| Are Django's foreign keys deferrable? | Every one the schema editor emits: **38 of 39**. The exception is hand-written -- `library_event_stream_matches_library`, added by `RunSQL` in migration `0023` |
| What is `ON DELETE` in the schema? | `NO ACTION`, on every constraint. Django's `on_delete` is Python-side, so raw DML does not cascade |
| Does setting `related_name = "+"` on a copied field hide the reverse accessor? | **No.** `ForeignObjectRel.hidden` is a `cached_property` (`reverse_related.py:64`) and `__deepcopy__` carries the cached `False` across, producing `fields.E304` **on the live model too** |
| Do `pre_save` receivers see every write? | **No.** `create()` fires; `bulk_create`, `QuerySet.update`, `bulk_update` and raw SQL do not |
| Is `ROW(a, b) <> ROW(c, d)` null-safe? | **No** -- it returns NULL, and a `WHERE` drops the row. Whole-row `(live.*) IS DISTINCT FROM (shadow.*)` is null-safe |
| Does `apps.get_models()` see an `isolate_apps` model? | **No** -- `isolate_apps` patches `Options.default_apps`, leaving the global registry untouched |
| Does `apps.get_models()` include `managed = False` models? | Yes |

Every one of these changed something below. The design that ignores them is a
rebuild whose diff is never empty, whose guard does not guard, and whose test
suite passes vacuously.

## Design

### `rebuild_projections(library, *, mode, wiring, apps)`

```python
def rebuild_projections(
    library: UserLibrary,
    *,
    mode: RebuildMode = RebuildMode.CHECK,
    wiring: EventWiring = DEFAULT_WIRING,
    apps: Apps = global_apps,
) -> RebuildReport
```

In `games/events/rebuild.py`. One attempt is five phases:

1. create an empty shadow table for every projection table;
2. replay the stream into a registry pointed at those tables, in one transaction,
   with the write guard armed;
3. diff shadow against live, for this library;
4. in `REBUILD` mode, swap under the stream lock;
5. drop the shadow, on every path.

`CHECK` is the default, so the destructive mode is the one an operator types out.
Both modes run phases 1--3, which is what makes the diff worth reading: the
answer `check` gives is produced by the same code that would have swapped.

The `wiring=` parameter defaults exactly as `dispatch` and `replay` already
default theirs. The `apps=` parameter is the model registry discovery reads, and
it exists for a reason the test section makes concrete: `isolate_apps` -- the
pattern this repo uses for test-local models -- patches `Options.default_apps`
and leaves the global registry alone, so a rebuild hard-wired to
`django.apps.apps` would discover **zero** tables under it and every parity
assertion would pass vacuously.

### `ProjectionModel`: what a rebuild owns

An abstract model in `games/models.py`:

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
`ProjectionModel.__subclasses__()`: the registry is complete after startup, while
`__subclasses__` sees only what has been imported and would make a rebuild's
scope depend on import order. `managed = False` models are included by
`get_models`, which matters because the shadow classes are `managed = False` and
must **not** be discovered as projection tables in their own right -- they are
excluded by name, not by hope.

Three rules follow, all of them constraints on #671:

**Every projection table carries its own `library` column.** A projection scoped
to a library only through a parent projection row is not supported; a child table
denormalises. This is what makes the swap one statement per table with no join
and no recursion.

**A projection row's primary key is explicit and event-derived.** No implicit
`AutoField`. `LIKE` gives the shadow its own identity sequence starting at 1, so
an auto-increment key makes three unchanged rows diff as three deletions and
three insertions, forever. The system check below refuses it.

**Nothing outside the projections may reference a projection row by foreign
key.** The swap deletes and reinserts every one of this library's projection
rows; an inbound foreign key from a conventional table would abort the swap at
`COMMIT` -- and since every constraint in this schema is `NO ACTION`, it would
abort rather than cascade. Conventional tables reference events (aggregate
UUIDs), never projections.

Abstract, so **this issue adds no migration and changes no schema.**

### A projection row is a pure function of the events

The diff compares every column of every row, which is only meaningful if
replaying the same events twice produces the same rows. The contract is stated
here and enforced by a Django system check over every `ProjectionModel` subclass,
which refuses:

- `auto_now` and `auto_now_add` -- wall-clock at projection time;
- an implicit or explicit `AutoField`/`BigAutoField` primary key -- see above;
- any `db_default` -- PostgreSQL evaluates it in the shadow independently, and
  this repo's `UUIDv7Field` sets `db_default=PostgreSQLUUIDv7()`
  (`timetracker/uuidv7.py:132`), so the trap is one field declaration away;
- a `default` drawn from the `uuid` module -- a fresh identity per rebuild.

A family needing a timestamp takes it from the event (`recorded_at`,
`effective_time`); a family needing an identity takes it from event data.

The available identity is narrower than it first appears, and #671 should know it
now. This repo's `UUIDv7Field` is unusable as a projection key on three counts:
it defaults to `uuid.uuid7`, it sets a database-side `uuidv7()` default, and
`parse_uuidv7` **rejects** a `uuid5` value outright (`timetracker/uuidv7.py:98`).
A projection key is therefore a plain `UUIDField` carrying an event-derived value
-- the event's `aggregate_id` or `correlation_id`, or a `uuid5` over them -- and
not the repo's UUIDv7 identity type. Whether such a table belongs in
`games/identity_audit.py`'s uuid_v7 audit is #671's question, not this one's; a
plain `UUIDField` is outside its `check_ordering` assertion by construction.

The check makes the declarative half of the rule mechanical. It cannot see the
other half: a handler calling `timezone.now()` or `random`, or a `GeneratedField`
over a volatile expression. Those are caught by the diff -- rebuild twice, get
two answers -- which is a worse error message and a real backstop. Claiming more
would be claiming the check is a purity analysis.

One thing that does come out well: a check reading `model._meta.local_fields`
sees `auto_now` on fields inherited from an abstract base, because abstract
inheritance copies fields into the concrete model.

### Redirection: a family writes through its target

```python
class ProjectionTarget(Protocol):
    def model[M: ProjectionModel](self, model: type[M]) -> type[M]: ...
```

`LIVE_TARGET.model(X)` returns `X`. `ShadowTarget.model(X)` returns a manufactured
class with the same fields, `managed = False`, and `db_table = "<table>__shadow"`,
cached one per live model per process.

A family holds one: `Projector.__init__` takes `target: ProjectionTarget =
LIVE_TARGET` and stores it, and `ProjectorRegistry.for_target(target)` returns a
sibling registry whose families are rebuilt against it. A family therefore never
imports its projection model; it writes
`self.target.model(PlayerGameState).objects...`, and the rebuild replays through
`replace(wiring, projectors=wiring.projectors.for_target(shadow))`.

`ProjectionTarget` and `LIVE_TARGET` live in a new `games/events/targets.py`, not
in `projection.py`. `projection.py` states as its design that it "holds no ORM
reference ... a registry of families over a value" -- the shape #914 delivered --
and importing `ProjectionModel` for a protocol bound would contradict it.
`targets.py` imports the model under `TYPE_CHECKING` only.

Two implementation facts must reach the plan rather than be discovered inside it.

**`register()` grows the target.** `ProjectorRegistry.register` instantiates with
no arguments today, and says so twice -- `projection.py:112` ("a family takes no
arguments and does no work in `__init__`") and the `Projector` docstring at
`projection.py:171`. A `for_target` that re-registered the kept classes would call
`projector_class()` again and produce **live-pointed families inside the shadow
registry**, which is a rebuild that silently writes production. Registration takes
the target, and both comments are updated with it.

**A copied field must be rebuilt from its `deconstruct()`, not deep-copied and
mutated.** Setting `related_name = "+"` on a deep-copied field does not hide the
reverse accessor: `ForeignObjectRel.hidden` is a `cached_property` and
`Field.__deepcopy__` shallow-copies `remote_field`, carrying the cached `False`
across. The result is `fields.E304` -- raised against the **live** model as well
as the shadow -- and because the shadow class is cached for the process, one
rebuild permanently reds `run_checks()`, including this issue's own new check.
Passing `related_name="+"` as a constructor keyword through `deconstruct()`
produces `hidden: True` and a clean `check()` on both models. Subclassing the live
model is not an option either: a concrete subclass is multi-table inheritance,
which adds a parent link and writes two tables.

The signature says `type[M]` and the returned class is not an `M`. That is a
deliberate cast, stated so nobody removes it as a mistake: the class carries the
same fields under the same names, which is what every caller uses it for, and a
protocol describing "a model with these fields" cannot be written for fields known
only at runtime.

Two contract terms fall out, both for #671:

- **A family reads only the library it is projecting.** Its shadow holds that
  library and nothing else, so a cross-library read that works live returns
  nothing during a rebuild.
- **A family reads its own projections through the target too**, not only writes.
  The journal and statistics families read current-state rows written earlier in
  the same fold; during a rebuild those rows are in the shadow.

The rejected alternatives were a second connection whose `search_path` selects a
shadow schema, and a contextvar the model manager consults. The `search_path`
route needs no cooperation from families and makes a live write physically
impossible; it pays with cross-connection visibility that forces every test to
`transaction=True`, a router keyed on a contextvar anyway, and schema-cloning DDL.
The guard below closes most of the gap that rejection opens.

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
physical fact rather than a precondition someone must remember to establish. #666
stated that it empties nothing and that its only planned caller would bring a real
empty state. This is that caller.

`INCLUDING ALL` brings the defaults, the check constraints, the generated-column
expressions and the indexes, and leaves the foreign keys behind. The indexes
matter because a family reads back rows it just wrote, at whatever selectivity the
live table was designed for. The absent foreign keys matter because a shadow with
references to live catalog rows would otherwise have to be built in dependency
order, and because the reference that must hold is the one in the live table after
the swap, which is checked there.

It also brings two things that are traps rather than features, both handled by the
projection-model rules above: an identity column gets a fresh sequence from 1, and
a `db_default` is copied and evaluated independently.

A durable `UNLOGGED <table>__shadow` per table would let an operator inspect a
failed rebuild's staged rows, and costs a permanent twin of every projection table
that migrations must keep in step, plus an advisory lock to keep two rebuilds
apart. Per-run named tables buy the same inspection and add orphan cleanup. The
diagnostics an operator needs are in the report, and the report survives the
connection.

Two environment caveats, neither live today: temp tables do not survive a
connection-pooler's session boundary -- the hazard class #917 records for
`WITH HOLD` cursors -- and a persistent connection (`CONN_MAX_AGE`, unset in this
project) outlives one rebuild, which is why phase 5 drops the tables rather than
trusting the disconnect.

### The replay is #666's replay, inside one transaction

`replay(library, wiring=shadow_wiring)` -- no second fold loop. The head it read
bounds it, an event landing above that bound belongs to a later replay, and
`folded_through` comes back as the expectation the swap will assert.

Phase 2 wraps it in `transaction.atomic()`. #666 takes no transaction and is right
not to, but a caller may wrap it, and this one should: in autocommit every shadow
row is its own transaction, and the shadow is private and dropped on every path,
so the wrap costs nothing a rollback would not have discarded anyway. It also
turns the replay's cursor from `WITH HOLD` into an ordinary one. The per-row commit
overhead this avoids is structural rather than a tuning knob, and #670 would
otherwise be handed it as the rebuild's headline number.

Everything #666 refuses, this inherits: `StreamNotContiguous` on a hole,
`PayloadVersionUnsupported` on an unreadable payload, and a family's exception
propagating with its own type and its `add_note` naming the family, the event type
and the sequence.

### The write guard

For the duration of phase 2, on the rebuild's connection, a
`connection.execute_wrapper` refuses any statement that writes anything other than
a shadow table.

Signals were the obvious mechanism and they do not work. A `pre_save` receiver
sees `save()` and `create()` and misses `bulk_create`, `QuerySet.update`,
`bulk_update` and raw SQL -- which is to say it misses precisely how a
rebuild-oriented family will write rows. Those writes would land in production
tables during a rebuild that is supposed to be invisible. `execute_wrapper` is
Django's documented hook around every statement executed on a connection
(`db/backends/base/base.py:772`), so it sees all of them, in their final SQL, and
this design already has the rebuild pinned to one connection.

The rule is an allowlist, not a blocklist: a write statement may name a
`__shadow` table and nothing else. That makes **"`check` writes nothing" true by
construction** rather than by a contract term asking families not to. It also
catches the side effect nobody would have listed -- a family incrementing a
counter row, writing a cache table, or recording an audit row outside its target,
which in check mode and on every discarded attempt would otherwise commit and
stay.

Residual, stated rather than papered over: a family reaching a second connection
or a psycopg handle of its own is not covered, and the wrapper matches quoted
table names in the statement text rather than parsing SQL. Both are worse than the
`search_path` route's physical impossibility; neither is reachable by a family
written the way #671's will be.

Outside a rebuild the wrapper is not installed. Making it always-on would give
#737's outcome nearly free and would decide #737's real question -- what the
escape hatch is for data repair, imports and the admin -- with no caller to test
it against. The guard is process-local and phase-local, which is correct: another
process serving a command for another library must keep writing live projections
throughout.

### The diff

Per projection table, the library's live rows against the shadow's: one query,
a `FULL OUTER JOIN` on the primary key, comparing rows with **whole-row
`IS DISTINCT FROM`** -- `(live.*) IS DISTINCT FROM (shadow.*)`.

The spelling is load-bearing. The row-constructor form
`ROW(live.a, ...) <> ROW(shadow.a, ...)` returns NULL when either side holds a
NULL, and a `WHERE` drops the row -- so a column that drifted to or from NULL
would be reported as matching. The whole-row form is composite comparison and is
null-safe. Equally: the per-library scope belongs in the `ON` clause or in a
subquery on each side; in `WHERE` it degrades the outer join and hides the
rebuilt-only rows.

`TableDiff` carries both row counts, how many rows are only live, how many only
rebuilt, how many differ, and a bounded sample of keys -- enough to act on,
bounded so a wholly-drifted table cannot produce a report nobody can read.
Generated columns are compared and agree by construction.

`check` mode stops here, and re-reads the stream head before reporting. It never
takes the lock, so an append landing between the replay's head read and the diff
would otherwise show up as drift that does not exist. The report carries the head
at diff time beside `folded_through`; when they differ, the diff is advisory and
says so. `rebuild` mode needs no such note, because `require_sequence` turns the
same race into a redo.

`rebuild` mode reports the diff and then swaps regardless: drift is the reason a
rebuild is being run, so refusing on mismatch would refuse precisely the case the
tool exists for, and an override flag that every real invocation carries has
stopped meaning anything.

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
block only for the duration of the statements above. `require_sequence` runs
before any statement that writes, so a conflict costs a rollback of nothing.

Raw DML per table, not `QuerySet.delete()`: the ORM's delete collects objects,
walks cascades and fires per-object signals, all of which are wrong here -- and
in this schema `on_delete` is Python-side anyway, since every constraint is
`NO ACTION`.

`cols` is every concrete column except the generated ones, which PostgreSQL
refuses to be handed and recomputes identically from the columns that are carried.

Ordering across tables does not affect correctness, because every foreign key
Django's schema editor emits is `DEFERRABLE INITIALLY DEFERRED` and the checks
run at `COMMIT`; self-referencing and mutually-referencing projection tables work
for the same reason. The qualifier is exact: this schema holds one hand-written
non-deferrable constraint, `library_event_stream_matches_library` from migration
`0023`, which is on the event table rather than a projection. A hand-written
constraint on a projection table would break the claim, which is why the rule
above says conventional tables do not reference projections at all.

A genuine violation raises at `COMMIT` naming the constraint rather than the row,
and rolls the swap back whole.

One asymmetry with `replay` is deliberate: `lock_stream` provisions the head row
when a library has never appended, so a `rebuild` of such a library creates it.
#666 refused to, because a read that provisions rows is a read nobody can run
safely. A rebuild is a writer, and `require_sequence(0)` is #901's first-class
assertion that the library is still empty -- so the swap empties this library's
projection tables and inserts nothing, which is the correct projection of an
empty stream. `check` never locks and creates nothing.

### A conflict redoes the attempt

`StreamSequenceMismatch` means an event landed while the rebuild worked, so the
shadow is a projection of a prefix and the expectation is the one number known to
be wrong. The whole attempt redoes: fresh shadow, fresh replay, fresh expectation,
after `wiring.retry_policy.delay_for(attempt)`. Up to `retry_policy.retries`
attempts, then the report comes back with `swapped=False` and the conflict
recorded, live rows untouched.

`run_in_transaction` cannot be reused. It classifies on
`IntegrityError`/`OperationalError` and their SQLSTATE and would decline a
`StreamSequenceMismatch` -- correctly, because what needs redoing is the replay
outside the transaction, not the transaction.

The alternatives are visible in the report either way. Reporting the conflict and
leaving the retry to the operator makes a person the loop on exactly the libraries
busy enough to need one. Holding the stream lock across the whole rebuild removes
the conflict by blocking every write to the library for the length of the rebuild,
which is the online property the charter, #666 and #901 were each built to
preserve.

### The report, and the command

`RebuildReport` is what an operator reads and what every test asserts on: the
library id, the stream id, the mode, whether it swapped, `folded_through`, the
head at diff time, the per-table `TableDiff`s, and one `RebuildAttempt` per
attempt carrying its `folded_through`, its phase timings and its conflict if it
had one.

`stream_id` is `uuid.UUID | None`, because `replay` returns `None` for a library
that never appended and `lock_stream` then provisions a real one in `rebuild`
mode. The report says which it is rather than presenting two different sources as
one field.

`manage.py rebuild_projections <library-uuid> [--check]` prints it, in the style
of `audit_uuid_identity` and `delete_user_library`, and exits non-zero when a
`rebuild` did not swap. One library per invocation, matching `replay` and the
swap; an operator sweeping several writes the loop. #666 drew that line for
reasons that have not changed -- ordering, failure handling and parallelism across
libraries have no defensible answer until a real family makes one of them
expensive.

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


# games/events/targets.py  (new)

class ProjectionTarget(Protocol):
    def model[M: ProjectionModel](self, model: type[M]) -> type[M]: ...

LIVE_TARGET: ProjectionTarget

class ShadowTarget:
    """Manufactured managed=False twins, one per live model, per process."""


# games/events/projection.py  (changed)

class Projector(ABC):
    def __init__(self, target: ProjectionTarget = LIVE_TARGET) -> None: ...

class ProjectorRegistry:
    def register(
        self, projector_class: type[Projector],
        *, target: ProjectionTarget = LIVE_TARGET,
    ) -> None: ...
    def for_target(self, target: ProjectionTarget) -> ProjectorRegistry: ...


# games/events/rebuild.py  (new)

class RebuildMode(StrEnum):
    CHECK = "check"
    REBUILD = "rebuild"

class LiveWriteRefused(RuntimeError):
    """A statement in phase 2 wrote something other than a shadow table."""

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
    apps: Apps = global_apps,
) -> RebuildReport: ...
```

Also changed: `games/checks.py` (new) registers the projection-model system check
and `GamesConfig` imports it; the two comments in `projection.py` that promise
zero-argument family instantiation. No existing behaviour changes.

## Where the behaviour is pinned

`tests/test_projection_rebuild.py`, new. Projection models are declared under
`@isolate_apps("games")` and created by `schema_editor`, the pattern
`tests/test_uuidv7.py:125` and `tests/test_temporal_field.py:146` establish;
families are declared against a registry the module owns, as
`tests/test_event_projectors.py` established. The rebuild is called with
`apps=<model>._meta.apps`, which is the isolated registry.

Isolation is not optional here, and the reason is worth recording: an
un-isolated `app_label = "games"` model leaks into
`games/identity_audit.py`'s `relation_columns()`, and
`tests/test_uuid_identity_audit.py:76` asserts **set equality** against a pinned
list. Both the test models and the process-cached shadow twins would break it, and
`test_projection_rebuild.py` sorts before it in the same process under CI's
`PYTEST_WORKERS=0`. A test that pins this -- the audit's expected set is unchanged
after a rebuild test runs -- belongs in the new module.

The models include a parent and a child projection table with a foreign key
between them, a nullable column, and a generated column.

Parity, which is the acceptance criterion:

- **a live-built projection rebuilds to itself**: dispatch commands, run `check`,
  every `TableDiff` is empty
- **drift is found and repaired**: corrupt a live row, `check` reports it and
  changes nothing, `rebuild` reports it and the live rows afterwards equal the
  rebuilt ones
- **a missing live row and an extra live row** are each reported on the right side
  of the diff, and repaired
- **a column drifting to NULL, and from NULL, is reported** -- the null-safety of
  the comparison, pinned rather than assumed
- rebuilding twice in a row is a no-op the second time

Isolation:

- a second library's projection rows are untouched by the swap, and its stream is
  never read
- `check` writes nothing: live rows unchanged, no shadow table survives
- a shadow table is dropped on success, on a family's exception, and on a
  contiguity failure

Concurrency:

- an append that lands between replay and swap produces a conflict, the attempt
  redoes, the second attempt folds the new event and swaps; the report carries two
  attempts and the delays come from the injected policy
- an exhausted budget returns `swapped=False` with the conflict recorded and the
  live rows exactly as they were
- `check` re-reads the head, and reports a head that moved during the diff
- a library that never appended: `rebuild` empties its projections, swaps nothing
  in, and creates the head row `lock_stream` provisions; `check` creates nothing

The contract:

- a family writing its live model during phase 2 raises `LiveWriteRefused`, and
  the live rows are unchanged -- pinned for `save()`, `bulk_create`,
  `QuerySet.update` and raw SQL, the paths a signal-based guard would have missed
- a family writing a non-projection table during phase 2 is refused the same way
- outside a rebuild, writing a projection model directly is allowed (pinned, so
  #737's later change is a visible one)
- the system check fires on `auto_now`, on `auto_now_add`, on an implicit
  `AutoField` primary key, on a `db_default`, and on a `uuid`-module default, and
  passes an event-derived model
- `run_checks()` is clean after a rebuild has manufactured and cached its shadow
  classes -- the `fields.E304` regression, pinned where it would otherwise be
  found by an unrelated test going red
- a projection table with a generated column rebuilds, and the generated values
  agree

The engine:

- the swap issues one delete and one insert per table regardless of row count
  (`django_assert_num_queries`), pinned at two library sizes
- the report's counts, head-at-diff and per-attempt timings are populated
- the management command prints the report and exits non-zero when a `rebuild`
  did not swap

## What this shape forecloses

**Catch-up from a sequence.** A rebuild is always from empty. #666 named the
reason and it stands: folding events 5,000 onward is only correct against a target
holding the first 4,999, which nothing can check without a stored per-projection
position. Nothing here stores one.

**Rebuilding every library.** One library per call. The sweep's decisions --
ordering, stop-or-continue, parallelism -- still have no consumer to answer them.

**A projection referenced by a conventional table.** Inbound foreign keys are
ruled out, because the swap deletes and reinserts every row.

**A projection scoped indirectly.** Every projection table carries its own
`library` column; a child table denormalises.

**An auto-increment or UUIDv7 projection key.** Both are non-reproducible. Keys
come from event data, which also means #671 cannot reuse this repo's standard
identity field on a projection table.

**A family with side effects outside its target.** The phase-2 allowlist refuses
them. A family that genuinely needs one has to make it an event.

**Inspecting a failed rebuild's staged rows.** Temp tables are gone with the
connection. The report carries the diff and the failure; the rows do not survive.

**Progress and cancellation.** A rebuild is one call returning a report. When real
families make it long enough to want a callback, #670's measurements will say what
it should report.

**Two concurrent rebuilds of the same library.** Both are allowed and neither
corrupts the other -- the shadows are private and each swap asserts its own
expectation -- but the second swap overwrites the first with identical rows, which
the pure-function contract makes harmless and which nothing prevents.

## Verification

Full `make check`: lint, format-check, mypy, ts-check, vitest and the entire
pytest suite including `e2e/`.

No migration, no schema change, no data change, no new dependency.
`ProjectionModel` is abstract and has no table; the shadow tables are created and
dropped inside one call. Reversibility is `git revert`, and the only thing lost is
the new modules, the abstract base, the system check and the added parameters.

The charter's 60-second/100k-event budget is deliberately not verified here.
Measuring a rebuild that projects nothing measures #666's replay, which #666
already measured at 1.74 s for 100k events. #670 owns the number, against #671's
families.

## Follow-up issues

None to file. Every deferral above is owned by an issue already in #601's tracker:
#671 for families and tables, #668 for reference resolution, #670 for the budget,
#737 for general write blocking, #917 for the pooler caveat.
