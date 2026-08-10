# PG-15/PG-16: External PostgreSQL deployment and backup design

## Purpose

Plan issues #617 and #618 as one deployment boundary: Timetracker consumes an
operator-managed PostgreSQL database, and operators can back that database up
and prove that a backup restores. This intentionally replaces #617's original
"app-plus-PostgreSQL Compose deployment" direction. The application must not
ship, start, configure, or persist a PostgreSQL server.

## Decisions

- PostgreSQL is external to Timetracker's Compose and Quadlet definitions.
  Operators own the server image and version, storage, server lifecycle,
  upgrades, network, roles, database creation, and PostgreSQL-level policy.
- Timetracker's only database interface is `DATABASE_URL`. PostgreSQL majors
  17 and 18 are supported. A later major stays rejected until it has explicit
  compatibility coverage; support is not an unbounded `17+` promise.
- `DATABASE_URL__FILE` is a supported secret-delivery form. It uses the
  existing file-setting precedence: when both variables are supplied, the
  file's trimmed contents win.
- A dedicated application role and database are recommended, but never
  required or detected by the application. Any usable PostgreSQL URL is valid.
- Backups and restore verification are manual operator procedures. Scheduling,
  retention, monitoring, and alerting are deliberately left to #597.

## Deployment contract

### Connection and secret delivery

The database URL is a complete PostgreSQL URL in a read-only secret file, for
example:

```text
postgresql://timetracker:<percent-encoded-password>@postgres/timetracker
```

The example hostname, `postgres`, is the network alias of an independently
managed PostgreSQL container. It is not a hard-coded application requirement;
operators may use a DNS name, another container alias, or a managed service.

The app container receives only:

```text
DATABASE_URL__FILE=/run/secrets/timetracker_database_url
```

and a read-only bind/secret mount at that path. The URL must not be put in a
checked-in `.env` file, a unit environment file, or command-line arguments.

### Compose and Quadlet responsibilities

The existing Compose deployment remains app-only. It gains the database URL
secret mount and setting but no `postgres` service, database volume, init SQL,
network alias, health check, or database credentials.

The rootless Podman Quadlet documentation demonstrates the same app contract:

- attach Timetracker to the already-managed backend network;
- mount `timetracker_database_url` read-only;
- set `DATABASE_URL__FILE` to its in-container location; and
- allow the URL to use the shared PostgreSQL container's `postgres` alias.

The PostgreSQL Quadlet itself is outside the artifact. The guide may explain
the topology and recommend a per-application role/database, but must not
present a Timetracker-owned server unit as a supported deployment mode.

## Backup and restore verification

### Manual backup

The runbook uses `pg_dump` from the PostgreSQL server container (or an equally
version-matched client image) and writes a custom-format dump to an
operator-selected host backup directory. Using matching tools avoids client /
server compatibility drift.

The dump is database-only and includes `--no-owner --no-privileges`. It
captures Timetracker schema and data without attempting to overwrite
cluster-wide role ownership or grants during restore. The document clearly
states that the operator supplies credentials through their existing secret
mechanism and that backups need protected storage and an off-host copy.

### Isolated restore check

Routine verification must never drop or recreate the live database. The
runbook instead:

1. creates a deliberately named, empty verification database using an
   administrator-capable operator connection;
2. restores the selected dump to that database with `pg_restore` fail-fast
   options;
3. runs a read-only Timetracker compatibility check against the restored URL
   (schema/migration-state and basic connection validation); and
4. drops only that exact verification database after success. On failure it
   retains the database for inspection unless the operator explicitly cleans it
   up.

Creating and dropping the verification database requires privileges beyond the
application role; that is an operator responsibility. Replacing a production
database is a separately explicit disaster-recovery operation, not part of
the routine verification recipe.

## Validation and acceptance criteria

- Configuration tests cover a valid `DATABASE_URL__FILE` and confirm it wins
  over `DATABASE_URL`, matching the project-wide file-setting convention.
- Deployment documentation and Compose checks ensure the app deployment has
  no bundled PostgreSQL service or volume.
- The documented deployment secret path is exercised by a container-level
  smoke test or equivalent configuration test.
- The restore procedure is tested with a disposable PostgreSQL database or
  container. It restores a custom-format dump, validates the resulting
  Timetracker database read-only, and never addresses a shared/live instance.
- Runtime and integration tests accept PostgreSQL 17 and 18 while rejecting a
  later unverified major. Documentation names those two supported majors and
  makes the external-PostgreSQL boundary and #597 scheduling exclusion explicit.

## Non-goals

- Bundled PostgreSQL Compose/Quadlet deployment.
- Per-field database host/user/password configuration.
- Application-managed credential, role, database, volume, or server lifecycle.
- Backup schedules, retention, replication, off-site transport, monitoring, or
  alerting.
- An automated destructive production restore command.
