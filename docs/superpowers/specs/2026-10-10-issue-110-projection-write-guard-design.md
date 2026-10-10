# Only named writers write a projection

Gitea lukas/timetracker#110 (GitHub #737), absorbing #111 (GitHub #738, the
bypass audit). Part of lukas/timetracker#109.

## Rule

A statement that writes a guarded table runs only inside a door that names
a permitted writer whose kinds cover that table. Every other such statement
is refused before it reaches the database.

Guarded tables are every `ProjectionModel` table (`projection_models()`,
kind `projection`) and `PurchaseValuation` (kind `valuation`). The charter
says a conventional read model "has its own named writers"; the registry is
where they are named, so the valuation joins it at the cost of one entry.

## Runtime, not static

The guard is a Django execute wrapper on every connection. It reads a
statement's write targets with `write_targets()`, which moves from
`games/events/rebuild.py` to `games/sql_writes.py`; the rebuild guard,
`games/events/benchmark.py` and `tests/test_projection_rebuild.py` import it
from there.

- A manager, `save()` or `delete()` override misses Django's own cascade
  (`Collector` issues `DELETE` through `sql.DeleteQuery`), raw cursors and
  `_base_manager`. A repro on this branch saw a user delete cascade into all
  nine projection tables and the valuation table, each one a statement the
  wrapper received.
- A static walker misses a spelling it was not taught.
- A PostgreSQL trigger would also see `psql`, but its door must reach SQL
  (`set_config` inside a transaction per write scope), and it cannot tell a
  test's seed from the application code that test runs inside the same
  transaction. A person at `psql` owns the tables and can disable a trigger.

`write_targets()` answers `""` for a write statement it cannot read; the
guard treats that as a write to every guarded table. Names compare
in lower case, as PostgreSQL lowers an unquoted name.

`write_targets()` learns to read a whole `TRUNCATE` list: Django's `flush`
between transactional tests is one `TRUNCATE "t1", "t2", …` over every
table, in set order, so reading the first name alone would see a guarded
table on some processes and not others. `TRUNCATE … CASCADE` answers `""`,
since it empties tables it does not name.

What the guard does not see, named so nobody reads it as complete: `DO`
blocks, `EXPLAIN ANALYZE`, a writing function behind `SELECT`, and a second
statement in one string (only the first keyword counts); psycopg
`cursor.copy()` and cursors from `connection.connection`, which bypass
execute wrappers. No code uses any of them today.

## The door and the registry

`games/projection_writers.py` holds the registry:

- `ProjectionWriter`, a `StrEnum`, one member per permitted writer.
- `PERMITTED_WRITERS: Mapping[ProjectionWriter, PermittedWriter]`.
  `PermittedWriter` names the module that opens the door and the kinds it
  may write.
- `projection_writes(writer)`, a context manager setting a `ContextVar`.
  Doors nest; the innermost decides.
- `ProjectionWriteRefused(RuntimeError)`, a defect. `answered()` does not
  map it: a request fails with its traceback, and a bulk chunk stores its
  batch `failed` through the defect path. The message names the table, the
  open writer or none, and the statement's first 200 characters.

The members, from the audit:

| Writer | Opened in | Kinds |
|---|---|---|
| `PROJECTOR` | `games/events/projection.py`, `ProjectorRegistry.apply` around the handlers | projection |
| `REBUILD_SWAP` | `games/events/rebuild.py`, `swap_in` | projection |
| `LIBRARY_PURGE` | `games/retention.py`, `purging_library()` | projection, valuation |
| `SAMPLE_ANONYMIZER` | `anonymize_sample`, inside `_prune_other_libraries`, `_anonymize` and `_reassign_uuids` | projection, valuation |
| `VALUATION_PUBLISHER` | `games/valuations.py`, `publish_valuations` | valuation |
| `MIGRATE` | `games/apps.py`, `pre_migrate` to `post_migrate` | projection, valuation |
| `TEST_SEEDING` | `tests/projection_doors.py` | projection, valuation |

`purging_library()` already is the purge's door: it lets the retention
guard pass a referenced row's delete. It now opens `LIBRARY_PURGE` too, so
one context names one act. `purge_user_library` and the tests that delete a
user or a referenced `Device` under it keep working unchanged; without it,
`ReferencedRow.delete()` in `games/models.py` would be the nearest frame and
the seeding door would stay shut.

The anonymizer opens its door per method, not in `handle()`, because
`tests/test_anonymize_sample.py` calls `_reassign_uuids()` directly.
`_reassign_stream_head`, which tests also call, writes only the stream head
and needs none.

`MIGRATE` exists because Django's schema editor writes rows: an `AlterField`
from null to not null with a default runs `UPDATE … WHERE col IS NULL`. No
current migration does, but one would be refused at container start. The
`games` app's `pre_migrate` receiver enters the door on a module
`ExitStack`, and `post_migrate` closes it; both connect with `sender=self`,
as `schedule_tasks` does, so each fires once per `migrate`. Both run in one
context, so the `ContextVar` token resets cleanly. `flush` also sends
`post_migrate`; closing an empty stack does nothing. `migrate --plan`,
`--check` and `--prune` return before either signal. A failed `migrate`
leaves the door open only in a process that then exits. A `RunPython` that
writes a projection directly passes under it; data migrations go through
dispatch by convention, as #700 did.

`load_sample_data` gets no member. It writes no guarded table itself:
`LOADABLE_MODELS` holds no projection, and the rows arrive through the
rebuild it runs, which opens `REBUILD_SWAP`. The shadow tables are
unmanaged `__shadow` twins outside `projection_models()`; the replay into
them runs under `PROJECTOR` and `only_shadow_writes()`.

## Installation

`GamesConfig.ready()` connects a `connection_created` receiver that inserts
the guard at index 0 of `connection.execute_wrappers` unless the list
already holds it. The check matters: `connect()` sends the signal on every
reconnect, and with `CONN_MAX_AGE=0` that is every request. Index 0, not
append: `execute_wrapper()` pops the last
entry on exit, so a guard appended while a connection opens inside such a
block would be popped in its place (`tests/test_event_idempotency.py` opens
one that way).

## Tests

About 115 test files write projection rows directly. Seeding them through
commands rewrites the suite for no gain in what the guard proves, so the
suite gets a door.

`tests/projection_doors.py` connects its own `connection_created` receiver,
which inserts a seeding wrapper directly before the guard, so it runs
outermost (Django applies `execute_wrappers` first entry outermost). Every
thread's connection gets one. For a statement that writes a guarded table
while no door is open, it walks the stack (`sys._getframe`, no source
reads) to the nearest frame under the repository root whose top directory
is a source tree. The rule names source trees, not "the repository",
because a worktree may hold its own `.venv`. Three outcomes:

- `tests/` or `e2e/`: `TEST_SEEDING` opens for that statement.
- `games/`, `common/`, `timetracker/`, `contrib/` or `scripts/`: the door
  stays shut, and the guard refuses.
- No source frame at all: `TEST_SEEDING` opens. This is Django's `flush`
  between transactional tests, run from pytest-django with no project
  frame on the stack. A test seeds
freely; application code a test runs is guarded as in production. The
`projection_guard_strict` fixture shuts the seeding door. Both conftests
install the module.

Proof:

- For each guarded model, under strict mode: an `UPDATE`, a `bulk_create`
  and a raw `DELETE` are refused, and nothing changes.
- A door whose kinds do not cover the table is refused
  (`VALUATION_PUBLISHER` writing a projection).
- The guard survives a connection opened inside `execute_wrapper()`.
- Each production writer's path runs green in the existing suites.
- Completeness: an AST walk over `games/`, `common/`, `timetracker/`,
  `contrib/`, `scripts/` and `tests/projection_doors.py` finds every
  `projection_writes(...)` call. Its argument must be `ProjectionWriter.X`;
  each member is opened only in its registered module; every member is
  opened. Other test files are not walked: they may open any door, since
  test code is not a production writer.

## Cost

The wrapper runs on every statement, reads included. The keyword check is a
prefix regex match, not a `split`, so a large statement costs no copy. The
bench's amplification pass no longer has the gated reads to itself: the
guard runs inside them. `make bench` runs before and after; the PR reports
both.

## Follow-up issues to file

None.
