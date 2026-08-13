# External PostgreSQL deployment

Timetracker connects to an operator-managed PostgreSQL database that satisfies
the [database contract](database.md). Timetracker does not manage the database
service, storage, roles, networking, or upgrades.

Provide the connection URL through `DATABASE_URL__FILE`. The hostname
`postgres` below is only an example; use the address appropriate for your
network.

## Docker Compose

Create a protected host file containing only the complete URL. Percent-encode
reserved characters in its password:

```text
postgresql://timetracker:<percent-encoded-password>@postgres/timetracker
```

Set `TIMETRACKER_DATABASE_URL_FILE` to that file's absolute host path, then
start the existing app-only Compose deployment:

```bash
export TIMETRACKER_DATABASE_URL_FILE=/absolute/path/to/timetracker_database_url
docker compose up -d
```

Compose mounts the file at `/run/secrets/timetracker_database_url` and sets
`DATABASE_URL__FILE` accordingly. It intentionally declares no PostgreSQL
service, volume, or credentials.

The image runs as uid 1000. The host secret must be readable by that user;
Compose `mode: 0400` does not change a file-backed secret's owner.

## Rootless Podman Quadlet

Attach the application to the database network and mount the URL secret
read-only. With rootless `keep-id`, `%U:%G` maps the host user's uid and gid
into the container, so the uid 1000 process can read a host-owned secret.

`~/.config/containers/systemd/timetracker.container`:

```ini
[Container]
Image=registry.kucharczyk.xyz/timetracker:latest
Network=backend.network
User=%U:%G
UserNS=keep-id:uid=%U,gid=%G
Environment=DATABASE_URL__FILE=/run/secrets/timetracker_database_url
Volume=%h/docker-compose-templates/secrets/timetracker_database_url:/run/secrets/timetracker_database_url:ro

[Install]
WantedBy=default.target
```

This is an application-only unit. Keep database configuration, storage, and
lifecycle in the database unit.

## Manual backup

Use a `pg_dump` client compatible with your server. The flags prevent a restore
from changing cluster role ownership or grants.

```bash
pg_dump "$DATABASE_URL" --format=custom --no-owner --no-privileges \
  --file=/path/to/protected/timetracker-$(date +%F).dump
```

Store dumps in protected storage and keep an off-host copy. Scheduling,
retention, monitoring, and transport are operator responsibilities.

## Isolated restore verification

Verify a dump only in an empty database. Use an administrator connection to
create and drop it:

```bash
createdb --maintenance-db='postgresql://<admin>@<host>/postgres' \
  timetracker_restore_verify
pg_restore --exit-on-error --no-owner --no-privileges \
  --dbname='postgresql://<admin>@<host>/timetracker_restore_verify' \
  /path/to/protected/timetracker.dump
DATABASE_URL='postgresql://<app-role>@<host>/timetracker_restore_verify' \
  python manage.py migrate --check
dropdb --maintenance-db='postgresql://<admin>@<host>/postgres' \
  timetracker_restore_verify
```

Run `dropdb` only after every preceding command succeeds. On failure, leave the
verification database for inspection. Never restore into the live database.

## UUIDv7 storage and clocks

Timetracker identity columns use the PostgreSQL `uuid_v7` domain over the
built-in `uuid` type. Native PostgreSQL backup and restore tools preserve the
domain and its dependencies. A generic schema or analytics client that reports
the column as `USER-DEFINED` can expose it as built-in UUID with
`identifier::uuid`; Timetracker does not customize Django `inspectdb` mappings.

Python-created identifiers use the application host clock and database-default
identifiers use the PostgreSQL host clock. On each new physical application
connection, Timetracker warns when database time falls more than one second
outside the latency-adjusted application interval. The warning does not change
`/health` or `/health/ready`; keep both hosts synchronized through normal NTP
and infrastructure monitoring.
