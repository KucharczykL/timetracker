# External PostgreSQL deployment

Timetracker connects to an operator-managed PostgreSQL 18.x database. The
database must use UTF8 encoding, the `builtin` locale provider, and `C.UTF-8`.
Timetracker does not provide or manage a PostgreSQL service, storage, roles,
initialization, lifecycle, networking, or upgrades.

The application receives one complete connection URL through
`DATABASE_URL__FILE`. A dedicated role and database are recommended but not
required. The hostname in these examples, `postgres`, is an example network
alias; use the hostname or managed-service address appropriate for your setup.

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

The Compose files mount the file at
`/run/secrets/timetracker_database_url` and set
`DATABASE_URL__FILE=/run/secrets/timetracker_database_url`. They intentionally
declare no PostgreSQL service, volume, initialization, or server credentials.

The image runs as uid 1000. Ensure the file-backed secret remains readable by
that user in the container; Compose `mode: 0400` does not change the host file
owner for a file-backed secret.

## Rootless Podman Quadlet

Attach the application to the operator-managed backend network and mount the
same URL secret read-only. With rootless `keep-id`, `%U:%G` maps the host user's
uid and gid into the container, so a secret owned and readable by that host user
is readable by the image's uid 1000 process.

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

This is an application-only unit. The independently managed PostgreSQL
container may expose `postgres` as its `backend.network` alias, but that alias
is not a Timetracker requirement. Keep PostgreSQL image selection, server
configuration, storage, roles, and lifecycle in the operator's database unit.

## Manual backup

Use a PostgreSQL-18-compatible `pg_dump` client and provide the database URL
through your existing operator secret mechanism. A custom-format dump is
database-only: `--no-owner` and `--no-privileges` prevent restore from changing
cluster role ownership or grants.

```bash
pg_dump "$DATABASE_URL" --format=custom --no-owner --no-privileges \
  --file=/path/to/protected/timetracker-$(date +%F).dump
```

Store the dump in protected, operator-selected storage and maintain an off-host
copy appropriate to your recovery requirements. Scheduling, retention,
monitoring, alerting, and off-host transport automation remain [#597](https://github.com/KucharczykL/timetracker/issues/597).

## Isolated restore verification

Verify a selected dump only in a deliberately named empty database. Use an
administrator-capable operator connection; the Timetracker application role
does not need permission to create or drop databases. Substitute your own
protected URLs and dump path below:

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

Run `dropdb` only after every preceding command succeeds. If the dump, restore,
or migration check fails, leave `timetracker_restore_verify` intact for
inspection. Never drop, recreate, or restore into the live Timetracker
database; production disaster recovery is a separate deliberate procedure.
