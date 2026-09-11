# CLEAN-02: Remove legacy PlayEvent and GameStatusChange storage

**Date:** 2026-09-11
**Issue:** https://github.com/KucharczykL/timetracker/issues/771
**Parent phase:** #602
**Status:** Draft

**Supersedes:**
[`2026-09-10-cleaning-02-remove-playevent-and-gamestatuschange.md`](2026-09-10-cleaning-02-remove-playevent-and-gamestatuschange.md)
and [`../notes/2026-09-10-cleaning-02-lessons-learned.md`](../notes/2026-09-10-cleaning-02-lessons-learned.md).
Both sit beside this one, each opening with a banner saying what is wrong with it,
because a reader who finds only the replacement learns nothing about the trap.
They are superseded rather than amended: their root-cause diagnosis is wrong, and
the five-migration sequence they prescribe (`0049`–`0053`) creates the failure it
was written to avoid. §Why the prior design fails records that, because the prior
design will look reasonable to anyone who rereads it cold.

## Problem statement

`PlayEvent` and `GameStatusChange` are legacy tables. Every run and every status
transition they once held is now in the event store and in the
`Playthrough`/`PlayerGame` projections: migration `0045` converted the runs, `0033`
recorded the status baseline, `0048` dated the runs that held no legacy row. No
runtime reader remains — `games/reads/playthrough_completions.py` and
`games/reads/playergame_history.py` answer from the projections.

The two tables still cost: they hold schema, they carry a `GeneratedField`
(`days_to_finish`) nothing computes against, `PlayEvent` sits in `REMOVABLE_MODELS`
and `IDENTITY_ORDER_SOURCE` names `games_gamestatuschange`, and the legacy names
block #687's rename.

## Outcome

The two model classes, their two tables, the four modules and two management
commands written to migrate off them, and every reference in code, tests,
fixtures and docs are gone. `make check` green.

## Dependencies

| Issue | What it gave | State |
|-------|--------------|-------|
| #684 | conversion pass, migration `0045` | complete |
| #1038 | start repair, migration `0048` | complete (merged, `f238f672`) |
| #688 | replay-parity gate | complete |
| #687 | name cleanup | **blocked by this issue** |

**Deployment precondition, and it is load-bearing.** This change makes `0033`,
`0045` and `0048` no-ops (§Commit A). Any database that still holds unconverted
legacy rows must pass through a release that applied all three *before* taking
this one. Rehearse with `make verify-dump` against a fresh production dump and
confirm `showmigrations games` lists `0048` as applied. §Commit C adds a guard
migration so a database that slipped through fails loudly instead of silently
losing the rows.

## Why the prior design fails

Four findings, each verified against the tree at `f238f672` rather than inferred.

### 1. `RunSQL` without `state_operations` splits state from schema

The prior `0049`–`0053` are bare `migrations.RunSQL`. RunSQL does not touch
migration state, so after `0053` the project state still holds both models while
the tables are gone.

The prior spec's headline evidence — "`makemigrations --check` reports No changes
detected" — was collected while the model classes still existed, so state and
`models.py` still agreed. Delete the classes, as that spec's own §Model removal
step requires, and the autodetector emits `DeleteModel`, whose `schema_editor`
issues a plain `DROP TABLE` with no `IF EXISTS`, against a table `0052` already
dropped. Fresh-database migrate fails.

That spec's step 5 — "verify `makemigrations` still reports No changes detected"
*after* deleting the classes — cannot hold. It is self-contradictory.

### 2. The FK-constraint theory describes no real mechanism

- Postgres `DROP TABLE` drops the constraints the table owns. An *outbound* FK
  never blocks a drop. Only inbound references need `CASCADE`, and nothing
  references either table: the only FKs are `PlayEvent.game` (`models.py:1360`)
  and `GameStatusChange.game` (`models.py:1415`), both pointing out at `Game`.
- Django's flush is one statement. `sql_flush` in
  `django/db/backends/postgresql/operations.py` emits
  `TRUNCATE "a", "b", "c" …`, and its own comment says this "allows us to truncate
  tables referenced by a foreign key in any other table". FKs among the listed
  tables are fine.

`cannot truncate a table referenced in a foreign key constraint` therefore arises
in exactly one situation: a referencing table exists in the database but is *not*
in Django's table list — the state/schema split of finding 1. So `0049` and `0050`
peel constraints that never blocked anything, and `0051`–`0053` manufacture the
divergence that produces the reported error.

### 3. The real blocker is the historical migrations, and `elidable` does not help

`0033`, `0045` and `0048` call `from games.backfill… import` and
`from games.models import` inside their `RunPython`. That is deliberate — `0033`'s
docstring (`games/migrations/0033_playergame_baseline_backfill.py:64`) says
historical models "cannot run a projector or validate a payload", and accepts
that the migration "is pinned to the application as it stands when it runs".

Those modules query the legacy models: `games/backfill/playthrough.py:357,376`,
`games/backfill/playergame.py:166,349`, `games/preflight/playthrough.py:381,449,558`.

`elidable=True` does not exempt them. In Django it is read in exactly one place —
`Operation.reduce()` at `django/db/migrations/operations/base.py:166` — which is
the optimizer, reached from `squashmigrations`. On a fresh database, including
every test database, all three `RunPython`s execute.

So deleting the modules or the models while those migrations still call them
raises `ImportError` during test-database creation, and every test errors. That is
the coherent account of v1's 862 errors; the flush theory is not.

### 4. `0053` runs too early to do anything

It deletes the `ContentType` and `auth_permission` rows while `models.py` still
defines both models, so `post_migrate` recreates them on the same run. The prior
spec notices this (its lines 132–137) and calls the migration correct anyway. Net
zero on a fresh database.

## What the prior specs also missed

Inventory taken at `f238f672`. These are additions to that spec's file lists, not
corrections of them.

| Finding | Prior spec | Actual |
|---|---|---|
| `games/fixtures/sample.yaml.gz` holds **209 `games.playevent` rows** | not mentioned | `make loadsample` and `LOAD_SAMPLE_DATA=1` break the moment the model is gone |
| e2e suite creates `PlayEvent` | not mentioned | `e2e/test_table_width_e2e.py:22,122`, `e2e/test_responsive_table_e2e.py:22,89`; `e2e/test_date_picker_e2e.py:2,20` names it in prose |
| Test files touching the models | "~25" | **39** under `tests/`, plus 3 under `e2e/` |
| `PlayEventFilter` | listed as a name this issue releases | **does not exist.** `filter_for_model` (`games/filters.py:864`) resolves by convention; no such class was ever written. The real names released are the `renamed_fields` aliases at `games/filters.py:142-143` and `related_name="playevents"` |
| `ts/elements/filter-tree/fixtures.canonical.json` | "remove the three canonical entries" | **gitignored** (`.gitignore:26`), regenerated by vitest. Editing it is a no-op |
| `fixtures.json` entries | "three comparison entries" | 3 cases at lines 228–252, and they are the suite's only ANY/ALL/NONE multivalued-comparison coverage — §Commit D retargets rather than deletes |
| `Makefile:336-343` targets `preflight-playthroughs`, `report-playthrough-starts` | not mentioned | must go with the commands |
| `CLAUDE.md` rows for both targets, and both models under §Models | not mentioned | must go |

Unrelated staleness noticed in passing: `CLAUDE.md` §Views lists
`games/views/statuschange.py`, which no longer exists. Out of scope — see
§Follow-ups.

## Design

Four commits, each independently green. The ordering principle is the inverse of
the prior spec's: **make the migration history stop depending on the application
first, and every later step becomes ordinary Django.**

### Commit A — neutralize the historical data passes

Replace the `RunPython` callable in `0033`, `0045` and `0048` with
`migrations.RunPython.noop`; keep the files, the dependency edges and the
module-level helpers' removal for Commit B.

The argument this rests on: those three passes only ever act on legacy rows. A
database holding legacy rows has already applied them — the row is in
`django_migrations`. A database that has not applied them is fresh, and a fresh
database has no `Game`, no `PlayEvent` and no `GameStatusChange`, so all three
passes are provably no-ops on it. There is no database on which this changes
behaviour, *given* the §Dependencies precondition. Commit C makes the exception
loud rather than silent.

Verify: fresh test database builds and the full suite is green with both model
classes still present. That isolates this commit from every later one.

### Commit B — delete the migration-only modules

| Path | Why it existed |
|---|---|
| `games/backfill/playthrough.py` | #684 conversion |
| `games/backfill/playergame.py` | #678 status baseline |
| `games/backfill/playthrough_start.py` | #1038 start repair |
| `games/preflight/playthrough.py` | #686 preflight report |
| `games/management/commands/preflight_playthroughs.py` | its report |
| `games/management/commands/report_playthrough_starts.py` | its report |

Plus `Makefile:336-343` and the two `CLAUDE.md` command rows.

Tests deleted whole, because their subject is deleted: `test_playthrough_conversion.py`,
`test_playthrough_preflight.py`, `test_playergame_backfill.py`,
`test_playthrough_start_repair.py`.

`games/backfill/appending.py` and `mismatch.py` go with them: their only importers
are `playthrough.py`, `playthrough_start.py` and the two tests deleted above.
Re-check the import graph before deleting rather than trusting this line.

### Commit C — drop the tables the ordinary way

Two migrations:

1. **Guard.** `RunPython` that raises if either legacy table holds a row, with a
   sentence naming the release to upgrade through first. Reverse is `noop`. This
   is the only thing standing between a stale deployment and silent data loss, so
   it counts a row rather than trusting `showmigrations`.
2. **`DeleteModel` pair**, autogenerated: delete the classes (`models.py:1350-1356`
   `PlayEventQuerySet`/`PlayEvent`, `models.py:1401-1407`
   `GameStatusChangeQuerySet`/`GameStatusChange`), then `make makemigrations`.
   State and schema move together, so no `RunSQL`, no constraint peeling, and no
   flush divergence. Confirm the generated file contains `DeleteModel` and
   nothing hand-written.

`ContentType` rows: Django leaves them stale by design;
`manage.py remove_stale_contenttypes` is the supported route and it prompts. Decide
between running it in `entrypoint.sh` with `--no-input` and a small `RunPython`
that deletes the two rows *after* the classes are gone. Either is fine; the prior
spec's `0053` is not, because it ran while the classes still existed.

### Commit D — cross-cutting code, tests and fixtures

Code:

| File | Change |
|---|---|
| `games/removal.py` | drop `PlayEvent` from `REMOVABLE_MODELS` + import |
| `games/identity_audit.py` | drop `"games_gamestatuschange": "timestamp"` from `IDENTITY_ORDER_SOURCE` |
| `games/filters.py:142-143` | drop `renamed_fields` (its own comment says #771 takes it) |
| `games/management/commands/load_sample_data.py` | drop both `"games.playevent"` map entries and the backfill imports |
| `games/management/commands/audit_library_ownership.py` | drop both count queries |
| `games/management/commands/anonymize_sample.py` | drop the `playevents` pass (`:229-242`), the count (`:308`), and `"games.PlayEvent"` from `IDENTITY_MODELS` |
| `CLAUDE.md` | drop both §Models bullets |

`ts/elements/filter-tree/fixtures.json:228-252` — **retarget, do not delete.**
These three cases are the only ANY/ALL/NONE multivalued-comparison coverage in the
cross-language contract. `game__player_games__playthroughs__completed_lower` is the
candidate replacement: `PlayerGame.game` carries `related_name="player_games"`
(`models.py:1595`) and `Playthrough.player_game` carries
`related_name="playthroughs"` (`models.py:1697`), so the path stays multivalued and
the quantifier still means something. Verify against
`tests/test_filter_tree_contract.py` — if `to_q()` equivalence does not hold on
that path, pick another to-many path rather than dropping the cases.
`fixtures.canonical.json` regenerates; do not edit it.

Tests: 39 files under `tests/` and 3 under `e2e/`. Enumerate with

```bash
grep -rln "PlayEvent\|GameStatusChange" --include="*.py" tests/ e2e/
```

rather than working from a list in this document — a stale list is how the prior
spec undercounted by 14. Three shapes: fixtures to rewrite onto `Playthrough` or
`PlayerGame` events, assertions naming the dropped tables or FKs
(`test_uuid_identity_audit.py`, `test_session_playhistory_uuid_primary_key.py`,
`test_library_commands.py`), and the four alias tests in `test_filters.py` that
exercise `renamed_fields`. `test_playthrough_preset_migration.py` is untouched —
the `"playevents"` → `"playthroughs"` preset mode in `0046` is a saved-filter word,
not the model.

**Regenerate `games/fixtures/sample.yaml.gz` last**, after
`anonymize_sample.py` no longer knows `PlayEvent`: `make fetch-dump`,
`make restore-dump`, `make migrate`, `make anonymize-sample`. Do not hand-edit the
gz. Then confirm `make loadsample` into an empty database.

## Verification

Gate is full `make check` — including `e2e/`, which the prior spec's §Verification
never names and which creates `PlayEvent` in two files.

Per-commit, in order:

1. **A:** fresh test database, full suite green, both models still defined.
2. **B:** `make check-fast` green; `grep -rn "games.backfill\|games.preflight" games/migrations/` empty.
3. **C:** fresh database `make migrate` green; `make makemigrations ARGS="--check --dry-run"`
   reports no changes *with the classes deleted*; `make verify-dump` green against a
   production dump; guard migration raises on a database seeded with one legacy row.
4. **D:** `make check` green. `make test-ts` regenerates `fixtures.canonical.json`
   and `tests/test_filter_tree_contract.py` passes. `make loadsample` into an empty
   database succeeds.

Final greps, all expected empty:

```bash
grep -rn "PlayEvent\|GameStatusChange" --include="*.py" games/ common/ tests/ e2e/ | grep -v games/migrations/
grep -rn "playevent" --include="*.py" games/ | grep -v games/migrations/
grep -rn "playevents__ended" ts/
grep -rn "preflight-playthroughs\|report-playthrough-starts" Makefile CLAUDE.md
```

`games/migrations/` keeps its references: `0001_squashed_0036_alter_playevent_days_to_finish.py`
creates both tables and the history must stay replayable from zero.

## Rollback

Not reversible in production: the tables are dropped and the events are the only
copy. Acceptable for the reasons #684 and #1038 already established — both passes
ran with reconciliation gates, `make verify-replay-parity` covers the projections,
and the charter's history requirement is met by the event store.

Recovery is `git revert` of the commit range *before* the migration applies. After
it applies, recovery is a restore from dump. `make verify-dump` before deploy is
what keeps that from being needed.

## Follow-ups to file

- `CLAUDE.md` §Views lists `games/views/statuschange.py`, which does not exist.
- #687 name cleanup unblocks once this lands; retarget it at `renamed_fields`
  and `related_name="playevents"`, not at the non-existent `PlayEventFilter`.
- Decide whether `remove_stale_contenttypes --no-input` belongs in `entrypoint.sh`
  permanently, rather than being a one-off for this change.
