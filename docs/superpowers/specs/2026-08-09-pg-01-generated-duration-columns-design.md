# PG-01: PostgreSQL-compatible generated duration columns

Date: 2026-08-09

Related issue: https://github.com/KucharczykL/timetracker/issues/603

## Outcome

Make the current `Session` generated duration columns valid PostgreSQL generated
columns without changing their public names or their calculated values.

## Dependencies and scope

This is the first PostgreSQL-compatibility input in Phase 1 (#600). It follows
the overhaul charter's current-schema portability contract.

This issue changes only `Session.duration_total`. It does not add a PostgreSQL
runtime, create a new migration baseline, transfer SQLite data, or change
filters, saved presets, statistics, APIs, ownership, or user isolation. Those
surfaces keep using the same persisted `duration_total` column and therefore
need no owning-issue change.

## Design

`Session.duration_calculated` remains a persisted `GeneratedField` with its
existing elapsed-time expression:

```python
Coalesce(F("timestamp_end") - F("timestamp_start"), 0)
```

`Session.duration_total` remains a persisted `GeneratedField`, but its
expression no longer references `duration_calculated`. It uses a small,
serializable database-aware expression that repeats the elapsed-time expression
and adds the manual duration:

```python
Coalesce(F("timestamp_end") - F("timestamp_start"), 0) + F("duration_manual")
```

PostgreSQL compiles that expression as interval addition. SQLite emits the
timestamp difference as integer microseconds, and its generic duration-addition
helper returns a text duration, so the expression's SQLite compiler directly
adds the two integer source values instead. PostgreSQL prohibits a generated
column from depending on another generated column; both compiler paths use only
source columns and retain every existing consumer.

The SQLite compiler branch is temporary. PG-26 (remove SQLite runtime
configuration and transaction behavior) owns its deletion after PostgreSQL is
the sole supported runtime and the legacy migration baseline has been retired.

## Migration and reversibility

Create a Django migration that removes `Session.duration_total` and adds it
back with the new generated expression. Django 6 does not support `AlterField`
for a changed `GeneratedField`; remove-and-add is its required schema pattern.
The database recalculates the replacement stored generated column from each
row's existing source columns, so no data migration, backfill, or
reconciliation report is required.

The ordered operations reverse automatically: Django removes the replacement
field and restores the preceding field definition. That reverse remains
suitable only for the current SQLite-compatible state; once a later issue
establishes a PostgreSQL baseline, this issue's forward migration is the
supported direction.

## Verification

Focused database tests must create and refresh these Sessions, then assert the
two generated columns retain their established values:

1. An ended timed Session has elapsed `duration_calculated` and the same
   `duration_total` when its manual duration is zero.
2. A running/manual-only Session has zero `duration_calculated` and its manual
   duration as `duration_total`.
3. An ended Session with a manual addition has elapsed duration as
   `duration_calculated` and their sum as `duration_total`.

A schema-focused test must inspect `Session._meta` and assert that
`duration_total` is persisted, retains a `DurationField` output, and its
expression is built from timestamp and manual-duration source fields rather
than `duration_calculated`. The migration file must carry the same expression.

The implementation must finish with a green `make check` gate. A later
PostgreSQL runtime issue owns the PostgreSQL 17 execution environment and its
cross-backend migration evidence.

## Acceptance mapping

- PostgreSQL-compatible generated duration columns: the `duration_total`
  expression has no generated-column dependency.
- No behavioral regression: the three focused cases preserve current values.
- Reversibility: Django reverses the remove-and-add operations to restore the
  preceding field definition.
- Full project quality gate: `make check` passes.
