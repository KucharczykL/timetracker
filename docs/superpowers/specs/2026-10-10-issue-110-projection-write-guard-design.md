# Only named writers write a projection

Gitea lukas/timetracker#110 (GitHub #737), with the bypass audit of #111
(GitHub #738). Part of lukas/timetracker#109.

## Rule

A statement that writes a guarded table runs only inside a door. The door
names a permitted writer, and the writer's kinds must cover the table. The
guard refuses every other such statement before it reaches the database.

Guarded tables are every `projection_models()` table (kind `projection`)
and `PurchaseValuation` (kind `valuation`).

## The guard

`refuse_unpermitted_writes` in `games/projection_writers.py` is a Django
execute wrapper. `GamesConfig.ready()` puts it at index 0 of
`connection.execute_wrappers` on every connection, once. Index 0 matters:
`execute_wrapper()` removes the last entry on exit.

The guard reads the tables a statement writes with `write_targets()` in
`games/sql_writes.py`. A write it cannot read is a write to every guarded
table. `TRUNCATE` names every listed table; `TRUNCATE … CASCADE` is
unreadable. Names compare in lower case.

A wrapper sees Django's delete cascade, raw cursors and `_base_manager`. A
manager or `save()` override sees none of them.

The guard does not see `DO` blocks, `EXPLAIN ANALYZE`, a writing function
behind `SELECT`, a second statement in one string, psycopg `cursor.copy()`,
or a cursor from `connection.connection`.

A refusal raises `ProjectionWriteRefused`, a defect. `answered()` does not
map it.

## Doors

`projection_writes(ProjectionWriter.X)` opens a door for a block. Doors
nest; the innermost door decides. `PERMITTED_WRITERS` names each writer's
module and kinds:

| Writer | Module | Kinds |
|---|---|---|
| `PROJECTOR` | `games/events/projection.py` | projection |
| `REBUILD_SWAP` | `games/events/rebuild.py` | projection |
| `LIBRARY_PURGE` | `games/retention.py` | both |
| `SAMPLE_ANONYMIZER` | `anonymize_sample` | both |
| `VALUATION_PUBLISHER` | `games/valuations.py` | valuation |
| `MIGRATE` | `games/apps.py` | both |
| `TEST_SEEDING` | `tests/projection_doors.py` | both |

`purging_library()` opens `LIBRARY_PURGE`. `MIGRATE` is open from
`pre_migrate` to `post_migrate`, because the schema editor can write rows.

## Tests

A test seeds projection rows directly. `tests/projection_doors.py` puts a
wrapper before the guard. When no door is open, it finds the nearest frame
in a source tree. `tests/` or `e2e/` opens `TEST_SEEDING`. An application
tree keeps the door shut. No source frame is Django's `flush`, which opens
it. The `projection_guard_strict` fixture shuts it.

`tests/test_projection_writers_registry.py` walks the syntax tree. Each
door names a `ProjectionWriter` member, only in its registered module, and
every member opens somewhere.

## Cost

About 0.5 µs a statement. A long read-only CTE costs more, so a substring
check skips the scan when no write keyword occurs.
