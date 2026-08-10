# PG-01 through PG-06 PostgreSQL re-verification design

**Issue:** #811 — Re-verify PG-01 through PG-06 against a real PostgreSQL
server

## Outcome

Execute the acceptance outcomes of PG-01 through PG-06 against the local
PostgreSQL 17 test topology supplied by #615. Preserve the existing focused
unit tests and add one dedicated regression module that makes the real-server
evidence explicit and repeatable.

## Scope and boundaries

#811 verifies six already-merged outcomes; it does not redesign them or repeat
their static/unit coverage. It owns an expression-level repair found during
this execution. A defect requiring a migration-baseline, runtime-topology,
deployment, data-transfer, API, or ownership change is filed and routed to its
own issue.

#615 is a prerequisite and #616 remains separate: CI stays serial and is not
changed here. The findings, including a clean result, are recorded in #599's
Plan adjustments section.

## Design

`tests/test_postgresql_reverification.py` is the single real-server evidence
module. Every database-touching test uses Django's database test support and
asserts `connection.vendor == "postgresql"`; this makes an accidental SQLite
run a failure rather than evidence for #811.

The module exercises the following contracts through the current application
models and query paths:

| Prior outcome | Real PostgreSQL proof |
| --- | --- |
| PG-01 (#603) | `Session` generated duration and total columns build and compute for ended, running/manual-only, and manual-addition rows. |
| PG-02 (#604) | An unlinked `Purchase` stores a `NULL` per-game value; linked rows recompute it, and converted price takes precedence. |
| PG-03 (#605) | `PlayEvent.days_to_finish` stores zero for missing endpoints, one for a same-day event, and signed values for forward/reverse date ranges. |
| PG-04 (#606) | Nullable direct and aggregate list values order non-NULL before NULL in both directions, with primary-key tie-breaking. |
| PG-05 (#607) | The live test connection satisfies `validate_postgres_collation_contract`. |
| PG-06 (#608) | Timestamp/duration query paths, JSON persistence, declarative constraints, and deliberate direct-cursor catalog validation behave as the audit recorded. |

The module has no custom PostgreSQL launcher, direct connection construction,
or database setup. It relies on the project `DATABASE_URL`, Django migrations,
and #615's xdist worker database names. It may use deliberate raw SQL only to
prove a database-level generated value or constraint that cannot be observed
through the ORM; it must be parameterized and limited to that assertion.

## Defect handling and reversibility

A passing run changes no schema or production data. If a test exposes an
expression-level incompatibility, first capture it as a failing regression in
this module, then make the smallest compatible model/query-expression repair.
Migration changes are out of scope unless the broken expression cannot be
repaired without one; in that case stop and file a routed issue rather than
expanding #811. Any code repair follows its owning field/query's normal
rollback behavior; the added tests are reversible by removing them.

## Verification

- Run the dedicated module through `make test` with the repository's default
  worker policy; it must prove PostgreSQL rather than SQLite.
- Re-run the existing PG-01, PG-02, PG-03, PG-04, PG-05, and PG-06 focused
  tests, plus any focused regression for a discovered repair.
- Run one complete `make check` gate with the normal local worker policy.
- Add a concise, dated #811 findings entry to #599, listing every confirmed
  outcome and any routed or repaired defect.

## Non-goals

- Moving CI to PostgreSQL or enabling parallel CI (#616).
- Changing PostgreSQL provisioning or pytest-xdist topology (#614–#615).
- Replacing the PostgreSQL migration baseline (#609).
- Changing application product behavior beyond a defect repair directly
  demonstrated by this re-verification.
