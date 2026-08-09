# PG-05: PostgreSQL collation contract

Date: 2026-08-09

Related issue: https://github.com/KucharczykL/timetracker/issues/607

## Outcome

Define one portable PostgreSQL database-collation contract and provide the
reusable validation unit that later runtime and provisioning issues invoke.

## Dependencies and scope

This is a Phase 1 PostgreSQL-compatibility input. It follows PG-01 through
PG-04 and supplies a narrow dependency to PG-11 (`DATABASE_URL` configuration
and startup validation), PG-12 (development provisioning), PG-16
(backup/restore verification), and PG-17 (Compose deployment).

The contract is deliberately separate from the startup wiring: this issue
defines and tests the validation unit, while PG-11 obtains a live connection
from `DATABASE_URL` and invokes it during application startup. It does not add
the PostgreSQL driver, alter Django `DATABASES`, provision a server, create a
database, transfer SQLite data, modify migrations, or change application query
semantics.

## Contract

Every supported PostgreSQL database must satisfy all of the following:

- PostgreSQL major version is 17.
- Database encoding is UTF8.
- Database locale provider is PostgreSQL's platform-independent `builtin`
  provider.
- The builtin locale is exactly `C.UTF-8`.

An operating-system `libc` locale is incompatible even when its displayed name
is `C.UTF-8`. ICU is also incompatible. This gives list ordering, comparisons,
and unique-index behavior one deployment-independent baseline. Application
queries must not depend on an operator's host locale.

The validation must read the server major from `server_version_num` and the
current database's encoding, provider, and builtin locale from PostgreSQL
catalog functions/columns. It must query the actual connected database rather
than trust a database name supplied by configuration. The validator returns
normally only when every value matches; otherwise it raises one project-owned,
actionable exception naming the observed and required value.

## Design

Add a small, Django-independent module under `timetracker/` with a typed
snapshot of the observed PostgreSQL contract and a single validation entry
point. Its sole dependency is a DB-API-compatible connection/cursor protocol,
so unit tests can use a recording fake cursor and no PostgreSQL service or
`psycopg` package is needed in this issue.

The entry point will execute one catalog query, map its one returned row into
the snapshot, and compare exact values against named constants. It will reject
missing rows, unexpected row widths/types, unparseable server-version values,
and all mismatch cases as contract violations rather than allowing an obscure
tuple/index error to escape. It will neither commit, modify database state, nor
attempt to repair an incompatible database.

PG-11 will import this entry point after connecting through `DATABASE_URL` and
turn its failure into a startup-blocking configuration error. PG-12 and PG-17
must create databases with these values and may call the same entry point for
post-create proof. PG-16 must verify a restored database with it. No caller is
introduced by this issue.

## Reversibility

The implementation is read-only. Reverting it removes the reusable validation
unit but cannot change existing databases or data. An incompatible database is
never silently converted: an operator must create or restore a conforming
PostgreSQL 17 `builtin`/`C.UTF-8` database through the owning provisioning or
transfer workflow.

## Verification

Focused tests use a fake connection/cursor to prove:

- the validator issues the catalog query and reads the one row returned for the
  connected database;
- the exact PostgreSQL 17, UTF8, `builtin`, `C.UTF-8` tuple passes;
- each independently wrong property (major version, encoding, provider,
  locale) fails with an actionable required-versus-observed message;
- `libc` with locale `C.UTF-8`, ICU, malformed version values, no row, and a
  malformed row all fail deterministically;
- validation is read-only: it calls neither commit nor any mutation query.

The full `make check` gate passes. PostgreSQL integration/startup coverage is
owned by PG-11 and provisioning/Compose validation by PG-12 and PG-17.

## Acceptance mapping

- The exact provider and locale are a documented deployment contract.
- The contract has an independently testable, reusable enforcement unit.
- No OS locale with a matching spelling is accepted.
- Runtime startup, database creation, backup/restore, and transfer remain in
  their separately tracked owning issues.
- No migration, data operation, filters, presets, statistics, APIs, or user
  isolation changes are introduced here.
