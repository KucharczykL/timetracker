# PG-02: PostgreSQL-compatible generated purchase-price columns

Date: 2026-08-09

Related issue: https://github.com/KucharczykL/timetracker/issues/604

## Outcome

Make the persisted `Purchase.price_per_game` generated column valid on
PostgreSQL without changing its public name or the value it exposes once a
Purchase has linked games.

## Dependencies and scope

This is an independent PostgreSQL-compatibility input in Phase 1 (#600), after
the same current-schema portability contract applied by PG-01. It must land
before the fresh PostgreSQL migration baseline (PG-07), transfer work, and the
PostgreSQL-only runtime cutover.

The issue changes only the zero-denominator behavior of
`Purchase.price_per_game`. It does not add PostgreSQL configuration, change the
Purchase write paths, change the `num_purchases` signal, alter price conversion,
or add a migration baseline or SQLite transfer. Filters, saved presets,
statistics, APIs, ownership, and user isolation retain the same persisted
column and are owned by their respective issues.

## Design

`Purchase.price_per_game` remains a stored `GeneratedField` with `FloatField`
output. Its numerator remains the existing converted-price preference:

```python
Coalesce(F("converted_price"), F("price"), 0)
```

Its denominator changes from `F("num_purchases")` to:

```python
NullIf(F("num_purchases"), 0)
```

The complete expression is therefore:

```python
Coalesce(F("converted_price"), F("price"), 0) / NullIf(F("num_purchases"), 0)
```

`Purchase` rows are first saved with the default `num_purchases=0`; the
`Purchase.games` M2M signal then counts the links and saves the real value.
SQLite evaluates the original zero division as `NULL`, while PostgreSQL rejects
it during the initial insert. `NULLIF` makes the initial generated value `NULL`
on both backends, then the database recalculates the stored value when the
signal updates `num_purchases`. This retains the current post-link calculation
and covers direct ORM creation, imports, and future callers without relying on
their write ordering.

The expression references only ordinary source columns. No generated-column
dependency, application-maintained duplicate, trigger, or write-path ordering
change is introduced.

## Migration and reversibility

Create a Django migration that removes `Purchase.price_per_game` and adds it
back with the `NULLIF` denominator. Django 6 does not support `AlterField` for
a changed `GeneratedField`; remove-and-add is the required schema pattern. The
database recalculates the stored generated values from each row's existing
`converted_price`, `price`, and `num_purchases`, so no data migration, manual
backfill, or reconciliation report is needed.

Django reverses the ordered operations automatically, restoring the previous
field definition. That reverse is appropriate only while the application still
supports the current SQLite-compatible schema. Once a later issue establishes
the PostgreSQL baseline, this issue's forward migration is the supported
direction.

## Verification

Focused database tests must cover these cases after `refresh_from_db()`:

1. Creating a Purchase with no game links succeeds and stores `NULL` for
   `price_per_game`, rather than raising a zero-division database error.
2. Adding two games updates `num_purchases` to two and recalculates an original
   price of 12 to a per-game price of 6.
3. With a converted price of 15, an original price of 12, and two linked games,
   the persisted per-game price is 7.5, proving converted-price precedence is
   unchanged.
4. A schema test asserts that the field is persisted, has `FloatField` output,
   references exactly `converted_price`, `price`, and `num_purchases`, and
   compiles the zero guard as `NULLIF`.

Generate the migration through `make makemigrations`, replace any generated
`AlterField` with remove-and-add operations, and inspect that it depends on
`games.0034_alter_session_duration_total`, has no data operation, and embeds
the guarded expression. Run the focused test through `make test`, then the full
`make check` gate. The later PostgreSQL runtime issue owns execution against a
PostgreSQL 17 environment and cross-backend migration evidence.

## Acceptance mapping

- PostgreSQL-compatible generated purchase prices: the expression divides by
  `NULLIF(num_purchases, 0)`.
- No behavioral regression: converted-price preference and linked-game division
  retain their current results.
- Insert safety: an unlinked Purchase has a persisted `NULL` per-game price.
- Reversibility: Django reverses the remove-and-add operations to restore the
  preceding field definition.
- Full project quality gate: `make check` passes.
