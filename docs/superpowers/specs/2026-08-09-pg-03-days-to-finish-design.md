# PG-03: PostgreSQL-compatible days-to-finish calculation

Date: 2026-08-09

Related issue: https://github.com/KucharczykL/timetracker/issues/605

## Outcome

Make the persisted `PlayEvent.days_to_finish` generated column valid on
PostgreSQL without changing its public name, integer type, or established
calculated values.

## Dependencies and scope

This is an independent PostgreSQL-compatibility input in Phase 1 (#600). It
depends on the current schema remaining portable and must land before the fresh
PostgreSQL migration baseline (PG-07), transfer work, and the PostgreSQL-only
runtime cutover.

This issue changes only the `days_to_finish` generated expression. It does not
add PostgreSQL configuration, change PlayEvent write paths, add a migration
baseline or SQLite transfer, or alter filters, saved presets, statistics, APIs,
ownership, or user isolation. Those surfaces continue consuming the same
persisted integer column and remain owned by their respective issues.

## Design

`PlayEvent.days_to_finish` remains a stored `GeneratedField` with `IntegerField`
output. Replace its SQLite-only `RawSQL` expression, which uses `date()` and
`julianday()`, with typed Django expressions and a serializable
`DatabaseDateDifference` helper in `games.expressions`.

The outer expression keeps the established behavior:

```python
Coalesce(
    Case(
        When(ended=F("started"), then=Value(1)),
        default=DatabaseDateDifference(F("ended"), F("started")),
        output_field=models.IntegerField(),
    ),
    Value(0),
)
```

For PostgreSQL, `DatabaseDateDifference` compiles as native typed date
subtraction (`ended - started`), which yields an integer day count. For SQLite,
it compiles as `CAST(julianday(ended) - julianday(started) AS integer)`;
`DateField` values have midnight precision, so the cast preserves their whole
day difference. The helper resolves through the generic expression path to
avoid Django converting date subtraction into a duration expression.

This preserves all existing semantics: either missing endpoint produces `0`, an
event that starts and ends on the same date produces `1`, and distinct dates
produce their signed day difference. The expression uses only `started` and
`ended` source columns—no SQLite-only raw SQL in the model and no application
maintained duplicate are introduced.

The SQLite compiler branch is temporary. PG-26 owns its removal after
PostgreSQL becomes the sole supported runtime and the legacy migration baseline
is retired.

## Migration and reversibility

Create a Django migration that removes `PlayEvent.days_to_finish` and adds it
back with the portable expression. Django 6 does not support `AlterField` for a
changed `GeneratedField`; remove-and-add is the required schema pattern. The
database recalculates the replacement stored value from each row's existing
`started` and `ended` values, so no data migration, manual backfill, or
reconciliation report is required.

Django reverses the ordered operations automatically, restoring the prior
SQLite-specific field definition. That reverse is appropriate only while the
application supports the current SQLite-compatible schema. Once a later issue
establishes the PostgreSQL baseline, this issue's forward migration is the
supported direction.

## Verification

Focused database tests must create and refresh PlayEvents for these cases:

1. Both dates missing, only `started` missing, and only `ended` missing each
   store `0`.
2. Equal start and end dates store `1`.
3. A multi-day event from 2026-01-01 to 2026-01-04 stores `3`.
4. A reverse-dated event from 2026-01-04 to 2026-01-01 stores `-3`, retaining
   the existing signed-difference behavior.

A schema-focused test must assert that the field is persisted, has
`IntegerField` output, and its expression is built from exactly `started` and
`ended`. On SQLite, generated SQL must retain the local `julianday` compiler
path; the expression object itself must not be `RawSQL`.

Generate the migration through `make makemigrations`, replace any generated
`AlterField` with remove-and-add operations, and inspect that it depends on
`games.0035_alter_purchase_price_per_game`, has no data operation, and embeds
the database-aware expression. Run the focused test through `make test`, then
the full `make check` gate. A later PostgreSQL runtime issue owns PostgreSQL 17
execution and cross-backend migration evidence.

## Acceptance mapping

- PostgreSQL-compatible generated days-to-finish: no SQLite-only `RawSQL`,
  `date()`, or `julianday()` appears in the model expression.
- No behavioral regression: missing-date, same-day, multi-day, and signed
  reverse-date cases preserve existing values.
- Reversibility: Django reverses the remove-and-add operations to restore the
  preceding field definition.
- Full project quality gate: `make check` passes.
