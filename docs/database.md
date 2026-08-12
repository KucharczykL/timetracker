# Database contract

Timetracker uses PostgreSQL as its only database. Development commands can
provision a disposable local server; deployed installations connect to an
operator-managed server. See [Deployment](deployment.md) for deployment and
backup examples and [Configuration](configuration.md) for connection settings.

## Supported database

Every connection must use:

- PostgreSQL major version 18;
- UTF8 database encoding;
- PostgreSQL's `builtin` locale provider;
- the `C.UTF-8` builtin locale.

The application validates this contract when it opens the default connection
and refuses to start against an incompatible database. A `libc` or ICU database
does not satisfy the contract, even if its displayed locale has a similar name.
This keeps comparisons, ordering, and unique constraints independent of the
database host's operating-system locale.

Development uses `make ensure-postgres`, normally through `make init`, to
create an ignored loopback-only cluster under `.cache/`. Set `DATABASE_URL` to
use an existing server instead. Deployments should provide the URL through
`DATABASE_URL__FILE` so credentials need not appear in the environment or the
Compose configuration.

## Schema and migrations

Fresh databases are built from the migration files in `games/migrations/`.
The existing initial migration is the permanent baseline. Future schema
changes add normal Django migrations; do not rewrite an applied migration.

Run `make makemigrations` when changing models and `make check-migrations` to
verify that model state and migration state agree. Deployment startup applies
pending migrations before starting the application processes.

## Generated columns

PostgreSQL stores several values calculated from other columns:

- `Purchase.price_per_game` divides the converted price, or the original price
  when no converted price exists, by the number of linked games. A zero game
  count produces `NULL` rather than a division error.
- `Session.duration_calculated` is the elapsed time between the end and start
  timestamps, or zero for an unfinished session.
- `Session.duration_total` adds the manual duration to the calculated duration.
- `PlayEvent.days_to_finish` is the date difference, counts a same-day event as
  one day, and is zero when the required dates are absent.

These are Django `GeneratedField` values. Application code must not write them
directly and must refresh an instance from the database when it needs a newly
calculated value immediately after a write.

The model expressions and migration expressions must remain equivalent. The
behavioral generated-column tests and `make check-migrations` are the normal
regression gates.

## Ordering

Nullable values in user-facing lists sort after non-null values in both
ascending and descending order. The shared sorting path also appends the
primary key as a stable tiebreaker. Queries outside that path must specify an
explicit null-ordering policy and a deterministic tiebreaker where result order
is observable.

## Tests

Tests use PostgreSQL databases created by Django from `DATABASE_URL`.
Pytest-xdist assigns every worker a distinct bounded database name that also
includes the test-run identity, so workers and concurrent runs cannot share a
test database. Django creates, migrates, and removes these disposable databases.

The Makefile chooses the normal worker count for the host. Set
`PYTEST_WORKERS=0` only for CI, focused debugging, or an explicit serial run.
