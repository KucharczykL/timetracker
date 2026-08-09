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
expression no longer references `duration_calculated`. It instead repeats the
elapsed-time expression and adds the manual duration:

```python
Coalesce(F("timestamp_end") - F("timestamp_start"), 0) + F("duration_manual")
```

PostgreSQL prohibits a generated column from depending on another generated
column. Inlining the equivalent source-column expression satisfies that rule
while retaining both compatibility columns and every existing consumer.

## Migration and reversibility

Create a normal Django `AlterField` migration for `Session.duration_total`.
The database recomputes the stored generated value from each row's existing
source columns; no data migration, backfill, or reconciliation report is
required.

The migration is reversible through Django's reverse `AlterField`: it restores
the preceding generated expression. That reverse remains suitable only for the
current SQLite-compatible state; once a later issue establishes a PostgreSQL
baseline, this issue's forward migration is the supported direction.

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
- Reversibility: the migration is an `AlterField` with Django's reverse path.
- Full project quality gate: `make check` passes.
