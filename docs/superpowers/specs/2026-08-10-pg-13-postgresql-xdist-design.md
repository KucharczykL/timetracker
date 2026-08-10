# PG-13 PostgreSQL pytest-xdist topology design

**Issue:** #615 — Run pytest-xdist safely against PostgreSQL

## Outcome

Developers can run the ordinary parallel pytest topology against the local
PostgreSQL 17 server provisioned by `make ensure-postgres`.  Each xdist worker
uses a Django-created disposable test database; no worker can run against the
development database or share a test database with another worker.

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
handling.  `DATABASE_URL` remains the connection source established by PG-11
and the ignored loopback PostgreSQL cluster remains the developer server
established by PG-12.  Pytest-xdist derives a distinct test database identity
for every worker from Django's configured default database; Django creates,
migrates, and tears down those databases rather than addressing the development
database itself.

No application-owned database naming hook, schema router, or external
per-worker service is introduced.  Such a layer would duplicate the test
framework's lifecycle and add cleanup and collision rules with no additional
guarantee.

The Makefile keeps its existing local worker-count policy, including the
Windows-specific default.  `make test`, `make test-fast`, and `make test-e2e`
continue to invoke pytest with `-n $(PYTEST_WORKERS)`.  The issue may adjust
test configuration only where needed to make the native PostgreSQL worker
topology explicit and reliable.

## Verification

Focused regression coverage must prove all of the following against a real
PostgreSQL server:

- the configured test connection is PostgreSQL, not SQLite;
- a parallel xdist invocation creates distinct worker test databases;
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

## Non-goals

- Switching CI to PostgreSQL or enabling CI xdist (#616).
- Re-validating the PG-01 through PG-06 compatibility outcomes (#811).
- Compose deployment (#617), backup/restore (#618), or performance work
  (#619–#620).
