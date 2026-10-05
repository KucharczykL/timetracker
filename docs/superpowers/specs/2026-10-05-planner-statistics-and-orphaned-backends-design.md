# Planner statistics after a load, and orphaned backends

## Planner statistics

The planner reads statistics that `ANALYZE` writes. Autovacuum analyzes a
table late, and after a small write never. Before that, the planner often
estimates one row at each join. Then the six-table read of
`library_purchases` runs for more than 30 s, against 1.6 ms analyzed.

A command that fills or replaces many rows calls `analyze_tables` in
`games/planner_statistics.py`. The function names its tables. It never runs
a bare `ANALYZE`, because `DATABASE_URL` can name a real database. An empty
list analyzes nothing.

| Writer | Tables |
|---|---|
| `load_sample_data` | `loaded_tables()`, in its transaction, before the commit queues the conversion task |
| `loadplatforms` | `Platform` |
| `rebuild_projections` | every projection table, after a rebuild only, also when a library fails |
| `publish_valuations` | `PurchaseValuation` |
| bench seed, reclassification parity | the tables they write |

`scripts/db_dump.py restore` runs a bare `ANALYZE` on the scratch copy,
which holds the dump only. `pg_dump` 18 writes no statistics by default.
`verify-dump` calls `restore`.

An `EXISTS` form misplans the same way, so the query keeps its joins.

## Orphaned backends

PostgreSQL finds a closed client only when it writes to that client. Thus a
query whose client died runs to its end. Three limits stop it.

**Client check.** `required_database_settings` adds
`-c client_connection_check_interval=<n>s` to libpq `options`, after the
`options` of the URL. `DATABASE_CLIENT_CONNECTION_CHECK_INTERVAL` sets `n`:
10, or 0 when Django runs on Windows, because a Windows server refuses a
nonzero value. `0` sends no option.

**Process limit.** `_ProcessStatements` holds one limit per process. A
`connection_created` receiver sets `statement_timeout` to it on each new
connection, so a failure occurs inside the error handling of a task or
request.

**Worker tasks.** A `post_spawn` receiver in `games/signals.py` sets the
limit to `Conf.TIMEOUT` when a worker starts. The cluster kills a task at
that limit.

**Requests.** Under `UvicornWorker`, Django runs a sync view in a thread,
so Gunicorn's `--timeout` does not stop a slow query. `timetracker.asgi`
and `timetracker.wsgi` call `limit_request_statements()` before Django
opens a connection, which sets the limit to `REQUEST_STATEMENT_TIMEOUT`
(30 s, `0` off). `runserver` imports `timetracker.wsgi`, so its request
threads have the same limit. `answered()` answers a statement timeout with
503 and `TIMED_OUT`, not as a refusal.

Both settings take whole seconds, 0 or more. Any other value stops boot
with an error that names the setting.

Commands and migrations have no limit. The container migrates at start,
and a migration over a limit stops the deployment.

## Tests

- Each loader, and a restored dump, leaves `reltuples` equal to `count(*)`.
- A rebuild and `publish_valuations` call `analyze_tables`; a check does not.
- The settings send the interval after the URL's `options`, none at 0, and
  refuse a bad value by name. The test connection reads it.
- A worker spawn sets `Conf.TIMEOUT`. A fresh connection reads `30s` in a
  marked process and `0` in an unmarked one. Each entry point marks.
- A statement timeout answers 503 and `TIMED_OUT`.
