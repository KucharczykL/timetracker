# PG-07: Fresh PostgreSQL-compatible migration baseline

Date: 2026-08-10

Related issue: https://github.com/KucharczykL/timetracker/issues/609

## Outcome

Replace the 36 historical `games` migrations with a single PostgreSQL-compatible
baseline, verified by building a fresh database on PostgreSQL 17 rather than by
inspection, and prove the baseline schema equivalent to the history it retires
before that history is deleted.

## Dependencies and scope

This slice follows PG-01 through PG-06. Those issues made the *model*
expressions portable; none of them ever executed DDL against PostgreSQL, so
their portability claims were reasoned rather than observed. PG-06 explicitly
assigned this issue the SQLite `julianday()` RawSQL in migration 0008, which it
declined to edit in place.

PG-11 owns `DATABASE_URL` and startup validation, PG-12 development
provisioning, PG-13 the permanent test topology, PG-16 backup and restore
verification, and the SQLite transfer and cutover group the transfer tool. This
issue therefore verifies against PostgreSQL with a
throwaway container and records the evidence; it adds no database dependency,
no settings change, no `make` target, and no PostgreSQL-backed test.

## Why the historical migrations cannot build a PostgreSQL database

Three defects abort `migrate` outright, and none is reachable by editing a later
migration — a fresh database replays the historical text:

- 0008 declares `PlayEvent.days_to_finish` with a `RawSQL` expression calling
  SQLite's `julianday()`;
- 0014 declares `Session.duration_total` as a generated column referencing the
  generated column `duration_calculated`, which PostgreSQL forbids; and
- 0012 declares `Session.duration_calculated` as `Coalesce(<interval>, 0)`,
  which PostgreSQL rejects as an unmatched type pair. 0034 repeats the same
  construct for `duration_total`, so this defect is present twice.

A fourth defect survives DDL and fails later: 0011 divides by `num_purchases`
without the `NULLIF` guard, so a Purchase inserted before its M2M links update
the count raises division by zero at insert time rather than yielding NULL.

The current models repair the first, second, and fourth. The third survives in
the models and is repaired by this issue; see below.

## Baseline construction

Delete the 36 migration files and regenerate a single baseline from the current
models with `makemigrations`, then hand-add a `replaces` list naming all 36. The
baseline is named `0001_squashed_0036_alter_playevent_days_to_finish`, never
`0001_initial`: a squashed migration whose `replaces` list contains its own key
is a cycle, and Django aborts `build_graph()` with `Cyclical squash replacement
found`, disabling every migration command and test-database build.

Regeneration rather than `squashmigrations` is deliberate: the seven
`RunPython`/`RunSQL` migrations are optimizer barriers, so a squash retains the
julianday RawSQL and the generated-on-generated column as historical text and
then requires hand surgery on generated output to remove them. Regenerating from
the models produces the repaired expressions by construction, and
`makemigrations --check` proves the result equals the model state.

`replaces` is retained even though the originals are deleted. The
deleted-history deployment supports the two database states that exist for this
project: a fresh database with none of the replaced migrations recorded, and
the sole production database at main commit `a62da2c` with all 36 recorded.
Django substitutes the baseline in both states. A partially applied 0001-0036
history is unsupported after the originals are deleted because Django can use a
replacement only when all or none of its targets are applied. The list becomes
dead weight after the PostgreSQL cutover and is removed in a follow-up cleanup
issue, per charter step 19.

The nine data operations across the seven `RunPython`/`RunSQL` migrations are
not carried over. Each is a backfill or cleanup over rows that already exist —
`initialize_num_purchases`, `set_finished_status`, `copy_year_released`,
`set_abandoned_status`, `create_game_status_changes`, `calculate_game_playtime`,
the `needs_price_update` UPDATE, `backfill_related_game`, and `remove_sentinels`
— and every one is a no-op on the empty database a baseline builds. None seeds
required data.

## The interval-literal repair

`Session.duration_calculated` coalesces an interval against the integer literal
`0`. PostgreSQL rejects the resulting DDL:

```
ProgrammingError: COALESCE types interval and integer cannot be matched
LINE 1: ... (COALESCE(("timestamp_end" - "timestamp_start"), 0)) STORED
```

The repair is a `timedelta(0)` literal in `games/models.py`, which also flows
into `duration_total` because that column repeats the elapsed expression. It
renders identical SQLite DDL, so no existing database changes.

This is PG-01 rework. It lands here because no buildable baseline exists without
it, and the issue that owns baselines is the first to execute DDL. The epic
records the adjustment for post-mortem rather than leaving it implicit in a
child issue's diff.

## Schema equivalence

The retired history and the baseline must produce the same schema, and only
SQLite can build both — the history's inability to build on PostgreSQL is the
premise of this issue. Equivalence is therefore established on SQLite, by
comparing `sqlite_master` between a database built from the 36 originals and one
built from the baseline, and is captured before the originals are deleted.

Observed during planning, by building both databases and diffing them: no
missing or extra tables, indexes, or constraints, and six tables differing by
column order alone — `games_game`, `games_platform`, `games_playevent`,
`games_purchase`, `games_session`, `games_userpreferences` — with every column
name, type, nullability, foreign-key clause, `CHECK`, and generated expression
identical. Implementation re-runs the comparison and records it against the
committed baseline.

Column order is a real difference with one consequence: the SQLite-to-PostgreSQL
transfer tool must copy by column name, never by ordinal position. That
constraint belongs to the transfer issues and is filed against them.

## One test retires with the history

`tests/test_migration_sentinel_removal.py` pins two migration module names and
drives `MigrationExecutor.migrate()` between them to round-trip migration 0024's
sentinel removal. All three migrations are retired here, so the test raises
`KeyError` on a name that no longer exists.

It is deleted rather than repaired. Its subject is a historical data migration
that ceases to exist, and there is no surviving migration to round-trip. The
invariant it guarded — no sentinel Platform or Device rows — is structural
today: both foreign keys are nullable and no code creates a sentinel.

## Static portability guard

A test walks `games/migrations/` and rejects `RawSQL`/`RunSQL`, a
`GeneratedField` whose expression reads another generated column, and
SQLite-only function names in migration source. It runs on SQLite and needs no
PostgreSQL, so it guards the three defect classes this issue removes during the
interval before PG-13 supplies a real harness.

It makes PG-06's static-audit line repeatable rather than closing it. Two
constructs stay out of reach by design: `RunSQL` nested inside
`SeparateDatabaseAndState`, and a lookup inside a `Q` object, whose left-hand
side `Q.flatten()` discards. Nor does a source scan see
`DatabaseDateDifference.as_sqlite`, which still emits `julianday(` into SQLite
DDL — correctly, as the dialect-aware rendering the baseline imports rather than
literal SQL written into a migration. The PostgreSQL build is what covers those.

Migration drift gets a permanent home at the same time: `make check` never
verified it, so a new `check-migrations` target runs `makemigrations --check
--dry-run` and joins both aggregates. Bare `makemigrations` is not a substitute
— on drift it writes a new migration instead of failing.

## Reversibility

Reverting the change restores the 36 files. The sole production database at
main commit `a62da2c` carries one extra `django_migrations` row after its first
`migrate` — `MigrationExecutor.check_replacements` records the squashed
migration itself once all 36 replaced keys are applied — which the restored
history ignores. No application row is written, altered, or deleted in either
direction, and no operator action is required for either supported state.

That extra row is the mechanism, not a side effect: it is what makes an upgrade
of the production 0036 database report no work rather than attempt to create
live tables. A partially applied history is outside the deployment contract and
would not select the replacement.

## Verification

- `migrate` builds a complete fresh database on a throwaway PostgreSQL 17
  container initialized with the `builtin` locale provider and builtin locale
  `C.UTF-8`, matching PG-05's deployment contract.
- An ORM smoke test on that database proves all four generated columns compute,
  not merely parse: elapsed, manual-only, and mixed Sessions; a multi-day, a
  same-day, and an open PlayEvent; and a Purchase with and without linked games.
- `sqlite_master` comparison between history-built and baseline-built SQLite
  databases, captured before deletion. Generated-column clauses are extracted
  and compared as a set; whole `CREATE TABLE` statements are not comparable,
  since both statement order and column order legitimately differ.
- An upgrade run against the production database state at 0036 reports no work
  and leaves the schema untouched, evidencing the zero-action upgrade claim
  directly.
- `make check-migrations` is clean, proving the baseline equals the model state.
- The static portability guard passes.
- The full `make check` gate passes; its test database is built from the
  baseline, so the existing suite exercises it throughout.

Container output and both diffs are recorded in the pull request. They are
one-shot evidence, not a permanent harness; PG-13 owns making PostgreSQL
verification routine.

## Acceptance mapping

- The historical migrations that cannot build a PostgreSQL database are replaced
  by one baseline that demonstrably can.
- Equivalence to the retired history is proven before deletion, and the single
  divergence is documented and routed to the issue it constrains.
- Reversibility is stated and requires no operator action.
- No runtime configuration, database dependency, test topology, transfer, regex,
  data, preset, statistics, API, or user-isolation work is absorbed.

## Follow-up issues

Filed and slotted into the phase tracker by dependency, not by origin — none
belongs in the PostgreSQL compatibility group, since each is blocked on work
that group precedes.

- #809: remove the `replaces` list once the PostgreSQL cutover retires the
  SQLite lineage (charter step 19). SQLite transfer and cutover group.
- #810: constrain the SQLite-to-PostgreSQL transfer to copy by column name
  rather than ordinal position. SQLite transfer and cutover group.
- #811: re-verify PG-01 through PG-06 against a real PostgreSQL server once
  PG-13's harness exists. Their outcomes were reasoned, and the first execution
  against PostgreSQL found a defect in PG-01's. PostgreSQL runtime group.
