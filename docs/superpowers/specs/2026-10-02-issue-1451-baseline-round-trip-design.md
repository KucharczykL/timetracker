# Both copies take the round trip

Issue [#1451](https://github.com/KucharczykL/timetracker/issues/1451).

## The finding

`make verify-baseline ARGS="--migrate"` on the 2026-10-01 dump reported
seven CHECK constraints as drift. The meaning was the same. Only the text
was different:

- copy: `ANY ((ARRAY['main'::character varying, …])::text[])`
- fresh: `ANY (ARRAY[('main'::character varying)::text, …])`

## The cause

The catalog text of a CHECK on a `varchar` column changes once under
`pg_dump` and `pg_restore`. After that one trip, it does not change. This
was tested on PostgreSQL 18: a constraint
`CHECK (kind IN ('a', 'b'))` on `varchar(20)` gave the first spelling
when added, and the second spelling after one dump and restore. A second
trip gave the second spelling again.

`verify_baseline.py` sends the fresh build through the trip. It does not
send the copy. A plain copy is a restore, so it has taken the trip
already. `--migrate`, `--normalize` and `--record` write to the copy
after the restore. A constraint that `--migrate` adds has not taken the
trip, so its text differs from the fresh build.

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
that `--migrate` built is gone, and `--keep` has nothing to show. The
dump file in the temporary directory is named after the database.

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
