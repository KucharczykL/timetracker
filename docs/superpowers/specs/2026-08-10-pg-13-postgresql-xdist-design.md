# PG-13 PostgreSQL pytest-xdist topology design

**Issue:** #615 — Run pytest-xdist safely against PostgreSQL

## Outcome

Developers can run concurrent ordinary parallel pytest topologies against the
local PostgreSQL 17 server provisioned by `make ensure-postgres`. Each xdist
worker uses a Django-created disposable test database; no worker can run
against the development database, share a test database with another worker in
the same run, or collide with a concurrent run.

## Scope and boundaries

PG-13 owns the local pytest topology only.  It does not change the application
database configuration, provisioning contract, schema, Compose deployment,
backup procedure, or CI database service.

GitHub Actions remains serial (`PYTEST_WORKERS=0`).  Its runner has four vCPUs,
where xdist contention is not a useful trade-off.  PG-14 (#616) owns moving
that serial CI verification to PostgreSQL 17 after the re-verification work is
complete.

PG-13 follows the PostgreSQL migration baseline (#609).  PG-13 supplies the
permanent topology required by #811, which re-executes the PG-01 through PG-06
acceptance criteria against a real server.  #811 has its own specification,
plan, commit, and review boundary.

## Design

The implementation uses Django and pytest-django's native test-database
handling. `DATABASE_URL` remains the connection source established by PG-11
and the ignored loopback PostgreSQL cluster remains the developer server
established by PG-12. Django creates, migrates, and tears down the worker
databases rather than addressing the development database itself.

Pytest-xdist supplies a run-wide `testrun_uid` and a `worker_id` fixture to
every worker. Pytest-django exposes `django_db_modify_db_settings_xdist_suffix`
as its supported customization point for xdist database settings. The project
defines that fixture in the importable `timetracker.pytest_topology` plugin and
loads the plugin from pytest's repository configuration in `pyproject.toml`;
it therefore applies to both `tests/` and `e2e/`. The test probe loads that
same plugin rather than copying or evaluating its source.

The fixture explicitly depends on pytest-django's tox suffix fixture before it
constructs the bounded name, so tox-parallel naming cannot be appended after
the PostgreSQL length check. It confirms actual xdist-worker context with
`request.config.workerinput`, then sets each worker's `TEST["NAME"]` from a
bounded ASCII representation of the configured base test name, the shared run
UID, and the worker ID. The resulting names are conceptually:

```
test_<base-name-hash>_<128-bit-run-hash>_<worker-id-hash>
```

Hashing the base test name as well as the run UID prevents two long or
multibyte PostgreSQL names from being truncated into the same identifier. The
128-bit run token makes accidental collision between independent xdist runs
negligible. The override uses only the framework's public fixture and settings
APIs. It introduces no launcher, Makefile-generated identifier, schema router,
service, migration, or Compose change.

The Makefile keeps its existing local worker-count policy, including the
Windows-specific default.  `make test`, `make test-fast`, and `make test-e2e`
continue to invoke pytest with `-n $(PYTEST_WORKERS)`.  The issue may adjust
test configuration only where needed to make the native PostgreSQL worker
topology explicit and reliable.

## Verification

Focused regression coverage must prove all of the following against a real
PostgreSQL server:

- the configured test connection is PostgreSQL, not SQLite;
- a parallel xdist invocation gives every worker a distinct test database;
- workers in one invocation share one xdist run UID, while distinct run UIDs
  generate distinct bounded ASCII database names;
- the global plugin applies to both `tests/` and `e2e/` collection trees;
- worker databases are derived test databases and are never the configured
  development database;
- the existing live-server concurrency coverage continues to run safely with
  the normal local worker default.

The complete `make check` gate runs with the Makefile-selected worker count.
On Windows, verification uses the managed hidden-process procedure and never
forces `PYTEST_WORKERS=0` except for an explicit debugging run.

## Reversibility

The topology has no production data migration or persistent application-data
change.  Reverting the code and test configuration restores the earlier test
runner behavior.  Django-created test databases are disposable and are cleaned
up by the test lifecycle; a failed interrupted run may leave only disposable
test databases, which can be removed with normal PostgreSQL administration.

## Implementation evidence

`timetracker.pytest_topology` is loaded from `pyproject.toml`, so the same
fixture applies to `tests/` and `e2e/`. It uses xdist's `testrun_uid` and
`worker_id` fixtures, with explicit tox-suffix ordering, to construct a bounded
ASCII PostgreSQL test database name. The two-worker child probe loads the
actual plugin and records separate PostgreSQL database names for `gw0` and
`gw1` under one supplied run UID. The existing live-server concurrency
regression also passes with the normal local worker policy. CI remains serial
because `CI` selects `PYTEST_WORKERS=0`; #616 owns its PostgreSQL migration.

## Non-goals

- Switching CI to PostgreSQL or enabling CI xdist (#616).
- Re-validating the PG-01 through PG-06 compatibility outcomes (#811).
- Compose deployment (#617), backup/restore (#618), or performance work
  (#619–#620).
