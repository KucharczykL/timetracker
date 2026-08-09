# PG-04: Deterministic NULL ordering across lists

Date: 2026-08-09

Related issue: https://github.com/KucharczykL/timetracker/issues/606

## Outcome

Define and enforce one deterministic ordering contract for nullable list sort
values on SQLite and PostgreSQL.

## Dependencies and scope

This Phase 1 PostgreSQL-compatibility input follows the overhaul charter's
current-schema portability contract. It changes query ordering only; it does
not add a PostgreSQL runtime, change schemas, create migrations, transfer data,
or alter filters, presets, APIs, statistics, ownership, or user isolation
beyond ordering their existing output where this issue owns it.

## Design

The common `games.sorting.apply_sort()` path serves all six paginated list
views and the sessions API. It will replace signed string order fields with
Django `F()` order expressions:

```python
F(spec.expression).desc(nulls_last=True)
# or
F(spec.expression).asc(nulls_last=True)
```

Thus a nullable value always appears after non-null values in both directions.
After the requested terms, the query appends ascending `pk` as a stable
tiebreaker. The public sort string and header state remain unchanged; the
tiebreaker is internal query behavior.

Audit remaining user-facing manual list orderings. Existing selectors already
using explicit `nulls_last=True` retain that policy. Any nullable value sorted
in a detail or statistics list receives the same explicit NULL-last policy and
a deterministic relevant key. Form choice querysets and non-null text sorts
need no change.

This is a permanent product contract, not SQLite compatibility machinery:
PostgreSQL defaults differ by direction and do not stabilize ties.

## Verification

Focused tests must prove that direct nullable fields and nullable aggregates
sort non-null values before NULL values in both directions, and that equal
values are ordered by primary key. Tests also cover the affected manual
orderings identified by the audit. The full `make check` gate passes.

## Acceptance mapping

- PostgreSQL portability: nullable list sorting uses explicit `NULLS LAST`.
- Determinism: list queries append a primary-key tiebreaker.
- No public-sort regression: existing sort keys, defaults, headers, filters,
  APIs, and presets continue using their current contracts.
- No data change: no migration, backfill, reconciliation, or rollback action
  is required; reverting the code restores prior ordering behavior.
