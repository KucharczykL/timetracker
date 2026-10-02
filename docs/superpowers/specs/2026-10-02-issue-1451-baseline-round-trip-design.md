# Both copies take the round trip

Issue [#1451](https://github.com/KucharczykL/timetracker/issues/1451).

## The cause

`pg_dump` and `pg_restore` change the catalog text of a CHECK on a
`varchar` column once:

- before: `ANY ((ARRAY['main'::character varying, …])::text[])`
- after: `ANY (ARRAY[('main'::character varying)::text, …])`

A second trip gives the same text. A restored copy has taken the trip.
A constraint that `--migrate`, `--normalize` or `--record` adds after
the restore has not, and it compares as drift with the same meaning.

## The rule

The tool sends each database through one dump and restore after the
last write to it, and only then reads the catalogs. Thus both sides
show the same spelling, and a difference is a difference in schema.

The copy takes the trip on every run, not only after a write. The trip
is a fixed point, so a second trip changes nothing. One rule for both
sides is simpler than a rule that names the options that write. A new
option that writes cannot forget the trip. The cost is one more dump and
restore of the copy, which takes about one minute, on a command that an
operator runs by hand.

The trip has a second effect. `db_dump.restore` sets `search_path` on
each public function that has none. A function that `--migrate` or
`--normalize` creates after the restore does not get it. The trip gives
it to the copy as it gives it to the fresh build.

The restore in the trip drops the database first. If it fails, the copy
that `--migrate` built is gone, and `--keep` has nothing to show. A
comment at the call says so.

The trip is a full dump, not `--schema-only`. The history catalog reads
the rows of `django_migrations`, which a schema-only dump leaves out.

## Rejected

- **Compare CHECK constraints by meaning.** This needs a parser for
  PostgreSQL expressions, or a normalizer that knows each spelling. The
  round trip removes the difference at its cause with tools that the
  script uses already.
- **Change the migrations.** The text depends on the path through
  `pg_dump`, not on the migration. A fresh `migrate` and the deployment
  create the constraint with the same statement.

## Tests

`tests/test_verify_baseline.py` replaces the database steps with
recorders. It checks that `verify` sends each database through
`round_trip` once, the copy after `migrate`, and that `compare` gets the
URLs that `round_trip` returns.

## Docs

The "Round-trip the fresh build before comparing" lesson in
`docs/migration-squash.md` becomes "Round-trip both builds". Its line
"A catalog text is not a fixed point" goes: the text changes once, then
stays. The module docstring of `verify_baseline.py` names the trip.
