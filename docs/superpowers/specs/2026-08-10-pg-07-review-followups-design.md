# PG-07 review follow-ups

**Date:** 2026-08-10

**Status:** Approved

## Outcome

Resolve the actionable findings from PR #812's review without changing PG-07's
migration baseline or widening its runtime scope. The repository, pull-request
description, and issue trackers must agree on the supported upgrade states, the
actual baseline filename, and the dependency-safe order of the remaining
PostgreSQL work. The migration portability guard must discover generated-column
names rather than rely on a hand-maintained list.

## Phase ordering

After PG-07, Phase 1 will proceed in this order:

1. PG-11 (#613): add `DATABASE_URL` configuration and startup validation.
2. PG-12 (#614): add the developer PostgreSQL harness.
3. PG-08 through PG-10 (#610, #611, #612): implement and migrate the regex
   behavior while a real developer PostgreSQL server is available.
4. PG-13 (#615): make the full pytest-xdist topology safe on PostgreSQL after
   the known regex incompatibilities are resolved.
5. #811: re-verify PG-01 through PG-06 immediately after the permanent test
   topology exists.
6. PG-14 (#616) and the remaining runtime work (#617 onward).

This order gives regex work executable PostgreSQL verification without moving
the full test suite or CI to PostgreSQL before the regex compatibility issues
land. Issue #600 will encode the order, and issue #599's Plan adjustments will
record why it changed.

## Migration lifecycle documentation

PG-07 supports the two database states that exist in this project:

- a fresh database with none of the replaced `games` migrations applied; and
- the sole production database at main commit `a62da2c`, with all 36 replaced
  migrations applied.

Django can substitute the squashed migration in both states. A partially
applied 0001-0036 history is not supported after the originals are deleted:
Django rejects the replacement when only some replaced migrations are recorded.
The PG-07 design and PR #812 description will state this precondition explicitly
instead of presenting the zero-action upgrade as unconditional.

Follow-up issue #809 will name the committed baseline file,
`games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py`, in
its outcome, context, and boundary. Its timing after the PostgreSQL cutover is
unchanged.

## Portability guard

`tests/test_migration_portability.py` will no longer maintain a constant naming
the four current generated columns. The migration-operation walker will expose
each generated field's declared field name. The generated-on-generated check
will derive the complete generated-field name set from the loaded `games`
migrations, exclude the field currently being checked, and compare the
expression's referenced columns against that derived set.

A focused synthetic regression test will construct a migration containing two
previously unknown generated-field names, with one reading the other. It must
fail under the old hard-coded implementation and pass once name discovery is
dynamic. Existing tests continue to prove the committed baseline has no
offenders. Documentation will stop listing `Q` lookup keys as a blind spot,
because `referenced_column_names()` already handles them explicitly; nested
`RunSQL` inside `SeparateDatabaseAndState` remains the documented limitation.

## Scope and verification

No migration operations, models, runtime database configuration, or application
behavior change. Repository edits are limited to the portability test and PG-07
documentation; external edits are limited to issues #599, #600, #809 and PR
#812's description.

Verification consists of the focused portability test, migration drift check,
`git diff --check`, and the full `make check` gate. The GitHub bodies will be
read back after editing to confirm their final content and ordering.
