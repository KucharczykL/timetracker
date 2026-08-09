# PG-06: PostgreSQL compatibility audit

Date: 2026-08-09

Related issue: https://github.com/KucharczykL/timetracker/issues/608

## Outcome

Audit the current runtime schema and query surfaces for PostgreSQL compatibility,
repair the defect found in duration filtering, and leave an explicit,
reviewable record of every audited category and its owner.

## Dependencies and scope

This Phase 1 compatibility slice follows PG-01 through PG-05. PG-01, PG-02,
and PG-03 already made generated duration, generated purchase-price, and
generated date-difference expressions portable. PG-04 owns ordering and PG-05
owns the database-collation contract.

This issue audits runtime timestamp/date, duration, JSON, constraint, raw-SQL,
and direct-cursor surfaces. It fixes defects found in those surfaces when the
repair does not require a new PostgreSQL runtime, data movement, a schema
baseline, regex work, or a deployment change.

PG-07 owns replacement of historical migrations with a fresh PostgreSQL
baseline. In particular, migration 0008 contains the retired SQLite
julianday() RawSQL expression; it remains a documented baseline blocker
rather than being edited in place. PG-11 owns DATABASE_URL and live startup
validation, PG-12 development provisioning, PG-13 test topology, and PG-16
backup/restore verification.

## Audit findings and design

### Runtime duration filtering

SessionQuerySet.without_manual() and only_manual() use the case-insensitive
__iexact lookup against duration_calculated, an SQL interval value. On
PostgreSQL, case-insensitive comparison implies a text case-folding operation
and is not defined for intervals. Both methods must use ordinary equality
against timedelta(0) instead. That preserves the existing meaning: a
calculated elapsed duration of zero is manual-only; every other value is not
manual-only.

Focused ORM tests create one elapsed Session and one equal-start/end
manual-duration Session, then prove the methods partition the two rows. They
exercise the real custom QuerySet rather than asserting emitted SQL.

### Timestamp, date, and duration expressions

All runtime timestamp fields are Django DateTimeFields under USE_TZ=True;
stored timestamps are UTC and per-session IANA zone identifiers are
presentation metadata. The remaining runtime date/duration expressions use
Django F, Case, Coalesce, TruncDate, TruncMonth, and the portable expression
helpers introduced in PG-01 through PG-03. Existing focused generated-field
tests prove the current model expressions. This issue adds no alternate
timezone storage or date backfill.

### JSON fields and constraints

FilterPreset, SiteSetting, and UserPreferences use Django JSONField only for
full-value persistence/serialization in the current runtime; no
backend-specific JSON operator, path lookup, or index is present. The
conditional platformless-game uniqueness constraint and the ordinary uniqueness
constraints use Django declarative constraints and retain PostgreSQL's intended
NULL behavior. No JSON rewrite, index, constraint migration, or duplicate-data
reconciliation is needed in this slice.

### Raw SQL and direct cursors

The audit finds no runtime application RawSQL, .raw(), .extra(), or ad-hoc
direct-cursor SQL. timetracker.postgres_contract is the deliberate read-only
PostgreSQL catalog validator from PG-05. Health checking uses a Django
connection cursor but does not contain backend-specific SQL. Historical
migration 0008 is the sole SQLite-specific RawSQL remaining and is assigned
to PG-07 as above.

The audit record is committed alongside the focused repair. It is a permanent
decision record, not a substitute for PG-07's fresh-database PostgreSQL
migration verification.

## Reversibility

The duration repair is a code-only lookup change; reverting it restores the
previous lookup behavior and changes no database row. The audit document and
tests do not mutate schema or data. No backfill, reconciliation report, or
operator rollback action is required.

## Verification

- Focused QuerySet tests prove exact partitioning of calculated-zero and
  non-zero Sessions, including a manual-duration row with equal endpoints.
- Existing PG-01 through PG-03 generated-expression tests remain green.
- Static audit searches prove no runtime RawSQL, .raw(), .extra(), or
  unowned direct-cursor SQL was added.
- The full make check gate passes once the PostgreSQL runtime/test harness
  is supplied by its owning later issues; before that, current SQLite checks
  validate this narrow runtime change.

## Acceptance mapping

- Timestamps, durations, JSON, constraints, and raw SQL have an explicit,
  scoped PostgreSQL compatibility audit.
- The interval __iexact runtime defect is repaired with a type-correct
  timedelta(0) comparison and focused tests.
- Historical SQLite RawSQL is explicitly routed to PG-07 rather than obscured.
- No unrelated migration baseline, runtime configuration, transfer, regex,
  data, filter-preset, statistics, API, or user-isolation work is absorbed.

