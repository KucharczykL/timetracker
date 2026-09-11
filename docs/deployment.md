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

A dump written before the temporal functions carried their own `search_path`
needs more than this one `pg_restore`; see [Dumps whose functions carry no
search_path](#dumps-whose-functions-carry-no-search_path).

### From a checkout

`make fetch-dump`, `make restore-dump`, and `make verify-dump` run the same
round trip from a development machine, filling the blanks above from `.env`
(`PROD_SSH_HOST`, `PROD_DB_CONTAINER`; see
[Configuration](configuration.md#dump-tooling-variables)). `fetch-dump` runs
`pg_dump` inside the database container over ssh and writes
`.dumps/timetracker-<today>.dump`; `restore-dump` loads the newest dump into a
scratch database created from `template0` under the
[database contract](database.md) and prints its URL; `verify-dump` restores,
migrates the copy, and drops it only if the migration succeeded (`KEEP=1` keeps
it). A restore refuses to name the development database or a maintenance one.
Both targets load the dump in three sections and give its functions their
`search_path` between the first two, so a dump of any age needs no special
handling.

The one difference from the commands above: `verify-dump` **applies** the
migrations rather than running `migrate --check`, because a checkout is usually
ahead of the deployment. That answers the stronger question — whether this
revision can migrate that dump — and is the pre-deploy rehearsal.

Run `dropdb` only after every preceding command succeeds. On failure, leave the
verification database for inspection. Never restore into the live database.

### Dumps whose functions carry no search_path

`make restore-dump` and `make verify-dump` handle this without being asked. The
commands below are for an operator holding only a shell.

A dump opens every session with an empty `search_path`, which the
`timetracker_temporal_*` functions did not carry a setting of their own against
for one stretch of this schema's history. Those functions call each other by
bare name, so during a load of such a dump the calls reach nothing, and
`timetracker_temporal_is_valid` reports the lookup failure as a verdict on the
value:

```text
value for domain public.temporal_value violates check constraint "temporal_value_valid"
```

A dump carries the function bodies as they were, so migrating the source does
not make an existing dump loadable. Load it in three parts instead, and give the
functions their reach between the first two:

```bash
pg_restore --exit-on-error --no-owner --no-privileges --section=pre-data \
  --dbname="$SCRATCH_URL" /path/to/timetracker.dump

psql -X --set=ON_ERROR_STOP=1 --dbname="$SCRATCH_URL" --command="
DO \$\$
DECLARE
    function_row record;
BEGIN
    FOR function_row IN
        SELECT candidate.oid::regprocedure AS signature
        FROM pg_proc AS candidate
        JOIN pg_namespace AS schema_entry ON schema_entry.oid = candidate.pronamespace
        WHERE schema_entry.nspname = 'public'
          AND candidate.prokind = 'f'
          AND candidate.proconfig IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend
              WHERE objid = candidate.oid
                AND classid = 'pg_proc'::regclass
                AND deptype = 'e')
    LOOP
        EXECUTE format(
            'ALTER FUNCTION %s SET search_path = pg_catalog, public',
            function_row.signature);
    END LOOP;
END
\$\$;"

pg_restore --exit-on-error --no-owner --no-privileges --section=data \
  --dbname="$SCRATCH_URL" /path/to/timetracker.dump
pg_restore --exit-on-error --no-owner --no-privileges --section=post-data \
  --dbname="$SCRATCH_URL" /path/to/timetracker.dump
```

Every function needs the setting, not only `timetracker_temporal_is_valid`. A
domain check routes through that one function, but a generated column calls
`timetracker_temporal_lower` directly, so naming `is_valid` alone loads the
plain columns and then stops on the first generated one.

`--set=ON_ERROR_STOP=1` is what makes a refused repair stop the sequence: `psql`
otherwise answers a failed script with 0, and the next `pg_restore` would report
the original domain error with nothing saying the repair never ran.

`ALTER FUNCTION` changes reach and no function body, so this is safe on a dump
of any age. Migrating the copy afterwards makes the setting permanent. A dump
written once the functions carried their own setting loads in one command.

## Replacing the migration history

The `games` app has one migration, `0001_initial`, and it states the schema the
deployment already reached rather than building up to it. Every migration
before it had run in full on every database that exists, so they were replaced
by their own result; see [Database contract](database.md#schema-and-migrations)
for what the file carries that no model declares.

A deployment that applied the old history has to be carried over once. Two
commands do the whole of it:

```bash
make verify-baseline
```

Restores the newest dump, runs the cutover on the copy, builds a second
database from `0001_initial` alone, and compares the two catalogs — columns,
constraints, indexes, routines, domains, sequences, recorded history. **A
differing row is a stop**: it means a migration generated after this point
would be written against a baseline the deployment does not have. `KEEP=1`
keeps both databases to look at.

```bash
make cutover-sql
```

Prints the statements to run against the deployment, which are the same ones
the rehearsal above applied to the copy: it drops the two legacy play-history
tables and the content types and permissions naming them, renames six NOT NULL
constraints still named after a column called `uuid`, and clears the `games`
rows out of `django_migrations`. Every statement is safe to run twice.

Then record the new history, which writes one row and touches no schema:

```bash
DATABASE_URL='postgresql://<app-role>@<host>/timetracker' \
  python manage.py migrate --fake games 0001_initial
```

Run it with the application stopped, and take a backup first — this is the one
procedure here that writes to the live database.

**A deploy that skips the cutover reports success.** The deployment's history
holds 84 rows, and the first is named `0001_initial` — the app's original
initial migration, from before an earlier squash renamed the file. The baseline
carries that same name, so `migrate` reads it as applied and prints `No
migrations to apply`. Nothing fails and nothing is repaired: the two legacy
tables stay, and 84 rows go on naming migrations that no longer exist. Read
that message as "the cutover has not run yet", never as "it has".

## UUIDv7

Identity columns use the `uuid_v7` domain over PostgreSQL's `uuid` type. Tools
that report it as `USER-DEFINED` can use `identifier::uuid`.

Python defaults use the application host clock; database defaults use the
PostgreSQL host clock. Timetracker warns on new connections when database time
falls more than one second outside the latency-adjusted application interval.
The warning does not affect `/health` or `/health/ready`; keep both hosts
time-synchronized.
