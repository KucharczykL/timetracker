> # ⚠ SUPERSEDED — DO NOT IMPLEMENT
>
> Kept as historical evidence only. The design below does not work, and its
> "✅ Verification Results" section does not verify what it claims to.
>
> **Replaced by:**
> [`2026-09-11-clean-02-legacy-table-removal.md`](2026-09-11-clean-02-legacy-table-removal.md),
> whose §Why the prior design fails walks each point with the evidence.
>
> Short version of what is wrong here:
>
> 1. Migrations `0049`–`0053` are bare `RunSQL`, so migration state keeps both
>    models while the tables go. The §Model removal step then makes the
>    autodetector emit `DeleteModel`, which issues a plain `DROP TABLE` against
>    a table `0052` already dropped. This document's own step 5 — "verify
>    `makemigrations` still reports No changes detected" *after* the classes are
>    gone — cannot hold.
> 2. The FK-constraint theory describes no real mechanism. Postgres drops a
>    table's own constraints with the table, nothing references either table,
>    and Django's `sql_flush` truncates every table in one statement.
> 3. The real blocker is unaddressed: migrations `0033`, `0045` and `0048`
>    import the live models and the backfill modules, and `elidable=True` is
>    read only by `squashmigrations`, so those passes still run on every fresh
>    test database.
> 4. `0053` clears `ContentType` rows while `models.py` still defines both
>    models, so `post_migrate` recreates them on the same run.
>
> The inventory is also short: it misses 209 `games.playevent` rows in
> `sample.yaml.gz`, three `e2e/` files, 14 of the 39 affected test files, and
> the `Makefile` targets; it names a `PlayEventFilter` that never existed; and
> it asks for edits to a gitignored generated fixture.

# CLEAN-02: Remove legacy PlayEvent and GameStatusChange storage

**Date:** 2026-09-10 (revised)
**Related issue:** https://github.com/KucharczykL/timetracker/issues/771
**Parent phase:** #602
**Status:** Draft — abandoned approach v1 superseded by migration-first design

## Problem statement

`PlayEvent` and `GameStatusChange` are legacy models whose data has been fully
converted to the `Playthrough`/`PlayerGame` projection pipeline (migration 0045)
and whose start-repair pass has run (migration 0048). The tables are now empty
ghosts that consume schema space, confuse the identity audit, and block the
filter name cleanup in issue #687.

**Previous attempt:** Deleted model classes from `models.py`, let Django auto-generate
a migration, then patched tests. Result: 862 test errors caused by Django's test
database flush trying to truncate `games_playevent` before the migration dropped it,
because the FK constraint chain prevented truncation during the flush phase.

**New approach:** Design the migration sequence first, verify it works in isolation,
then delete model classes and update code.

## Outcome

- Two model classes removed from `games/models.py`
- Two database tables dropped via a carefully sequenced migration
- All runtime references cleaned up across models, management commands, tests,
  and frontend fixtures
- Full test suite passes

## Scope

Dropping the model releases three names issue #687 could not rename, because each
is the model's own name wearing a suffix:

- `PlayEventFilter` — `filter_for_model` resolves
  `globals()[f"{model.__name__}Filter"]` by convention and keeps no registry.
- The singular key `"playevent"`, which is `PlayEvent._meta.model_name`. It is
  what `apps.get_model` takes, what the builder URL segment `/playevent/filter`
  reads, and what `ts/elements/filter-tree/fixtures.json` and
  `ts/elements/filter-tree/fixtures.canonical.json` name.
- `related_name="playevents"` and `game.playevents`.

## Boundary

Deliver only this independently reviewable outcome. Keep adjacent projection
schema, projector behavior, query services, UI surfaces, cutovers, and
compatibility cleanup in their separately tracked issues.

## Dependencies

- Issue #684 (conversion) — **complete** (migration 0045, `elidable=True`)
- Issue #1038 (start repair) — **complete** (migration 0048, `elidable=True`)
- Issue #688 (replay-parity gate) — **complete** (merged)
- Issue #687 (name cleanup) — **blocked** by this issue (this issue unblocks it)

## Architecture

### Module deletions

Four modules written solely for the migration pipeline are deleted:

| Module | Lines | Purpose |
|--------|-------|---------|
| `games/backfill/playthrough.py` | 697 | PlayEvent → Playthrough conversion pass |
| `games/backfill/playergame.py` | 401 | GameStatusChange → PlayerGame backfill |
| `games/backfill/playthrough_start.py` | 644 | One-time #1038 start repair |
| `games/preflight/playthrough.py` | ~560 | PlayEvent preflight inspection |

Two management commands that report on these modules are also deleted:

| Command | Purpose |
|---------|---------|
| `preflight_playthroughs` | Legacy PlayEvent preflight report |
| `report_playthrough_starts` | Legacy start-repair diagnostic |

These modules are imported only by:
- Their own cross-references (deleted together)
- Migration 0045 (`0045_playthrough_conversion_backfill.py`) — `elidable=True`
- Migration 0048 (`0048_playthrough_start_repair.py`) — `elidable=True`
- `load_sample_data.py` — imports for sample generation (dead after deletion)
- ~12 test files — tests for deleted functionality

After deletion, no runtime code references these modules.

### FK constraint analysis

Before designing the migration, we must understand the FK constraint chain:

| Source Table | FK Column | Target Table | ON DELETE |
|--------------|-----------|--------------|-----------|
| `games_playevent` | `game_id` | `games_game` | CASCADE |
| `games_gamestatuschange` | `game_id` | `games_game` | CASCADE |

No other model has a FK to `PlayEvent` or `GameStatusChange`.
No model has a reverse FK reference via `related_name="playevents"` or
`related_name="status_changes"` that other code depends on.

### Migration sequence (DESIGNED FIRST)

The migration sequence must handle the FK constraint before dropping tables.
Django's test database flush truncates all tables after applying migrations.
If a table has FK constraints, truncation fails. The sequence uses five
independent migrations:

```
0049_remove_playevent_game_fk    -- ALTER TABLE DROP CONSTRAINT on games_playevent.game_id
0050_remove_gamestatuschange_game_fk -- ALTER TABLE DROP CONSTRAINT on games_gamestatuschange.game_id
0051_drop_gamestatuschange_table -- DROP TABLE games_gamestatuschange
0052_drop_playevent_table        -- DROP TABLE games_playevent
0053_clear_content_types         -- Delete ContentType + Permission entries
```

**Why this order:**

1. **0049 & 0050**: Remove FK constraints. This allows the tables to be truncated
   during Django's test flush, because there are no longer any FK constraints
   blocking it. The tables still exist with their data, but the constraints are gone.
2. **0051 & 0052**: Drop the tables. After constraints are removed, the tables
   can be safely dropped.
3. **0053**: Clear ContentType entries. Django has no built-in mechanism to
   remove ContentType entries when models are deleted. We must manually delete
   `auth_permission` rows first (FK references ContentType), then ContentType rows.

**Note on ContentType entries:** Django does **not** automatically clean up
ContentType entries when tables are dropped. The `post_migrate` signal only
**creates** entries for new models. Since we use `RunSQL` to drop tables,
we need a separate migration to clean up ContentType entries (and their
referenced `auth_permission` rows).

**Important:** The `post_migrate` signal will re-create ContentType entries
for any model that still exists in `models.py`. This means the ContentType
cleanup migration must run AFTER the tables are dropped (so the migration
is reversible) but the entries won't be re-created until the model classes
are deleted from `models.py`. The migration is correct — it will clean up
the entries after the model classes are deleted.

**Decision: Split into five migrations** — each is independently verifiable,
reversible (for the SQL drops), and isolates failure points.

**Discovered FK constraint names (verified on test database):**

| Table | Constraint Name |
|-------|----------------|
| `games_playevent` | `games_playevent_game_id_05d20a2b_fk_games_game_id` |
| `games_gamestatuschange` | `games_gamestatuschange_game_id_90c2cee6_fk_games_game_id` |

These names are deterministic (Django generates them from the field definition).
The `DROP CONSTRAINT IF EXISTS` syntax handles unknown names gracefully.

**Migration details:**

```python
# 0049_remove_playevent_game_fk.py
class Migration(migrations.Migration):
    dependencies = [("games", "0048_playthrough_start_repair")]
    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE games_playevent
                DROP CONSTRAINT IF EXISTS games_playevent_game_id_05d20a2b_fk_games_game_id;
            """,
            reverse_sql="""
                ALTER TABLE games_playevent
                ADD CONSTRAINT games_playevent_game_id_05d20a2b_fk_games_game_id
                FOREIGN KEY (game_id) REFERENCES games_game(id)
                ON DELETE CASCADE;
            """,
        ),
    ]

# 0050_remove_gamestatuschange_game_fk.py
class Migration(migrations.Migration):
    dependencies = [("games", "0049_remove_playevent_game_fk")]
    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE games_gamestatuschange
                DROP CONSTRAINT IF EXISTS games_gamestatuschange_game_id_90c2cee6_fk_games_game_id;
            """,
            reverse_sql="""
                ALTER TABLE games_gamestatuschange
                ADD CONSTRAINT games_gamestatuschange_game_id_90c2cee6_fk_games_game_id
                FOREIGN KEY (game_id) REFERENCES games_game(id)
                ON DELETE CASCADE;
            """,
        ),
    ]

# 0051_drop_gamestatuschange_table.py
class Migration(migrations.Migration):
    dependencies = [("games", "0050_remove_gamestatuschange_game_fk")]
    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS games_gamestatuschange;",
            reverse_sql="-- Not reversible",
        ),
    ]

# 0052_drop_playevent_table.py
class Migration(migrations.Migration):
    # Depends on 0049 (PlayEvent FK constraint removed) but NOT on 0051
    # (GameStatusChange table drop) — the two are independent.
    dependencies = [("games", "0049_remove_playevent_game_fk")]
    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS games_playevent;",
            reverse_sql="-- Not reversible",
        ),
    ]

# 0053_clear_content_types.py
#
# Django does not clean up ContentType entries when models are deleted.
# We must delete auth.Permission rows first (FK references ContentType),
# then ContentType rows.
#
# Uses raw SQL to avoid apps registry issues during migration.
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("games", "0051_drop_gamestatuschange_table"),
        ("games", "0052_drop_playevent_table"),
    ]
    operations = [
        migrations.RunSQL(
            sql="""
                -- Delete permissions first (FK references ContentType)
                DELETE FROM auth_permission
                WHERE content_type_id IN (
                    SELECT id FROM django_content_type
                    WHERE app_label = 'games'
                      AND model IN ('playevent', 'gamestatuschange')
                );
                -- Then delete ContentType entries
                DELETE FROM django_content_type
                WHERE app_label = 'games'
                  AND model IN ('playevent', 'gamestatuschange');
            """,
            reverse_sql="-- Not reversible: ContentType entries are gone.",
        ),
    ]

```

**Note on FK constraint names:** The actual constraint names are deterministic
(Django generates them from the field definition). The discovered names are:

| Table | Constraint Name |
|-------|----------------|
| `games_playevent` | `games_playevent_game_id_05d20a2b_fk_games_game_id` |
| `games_gamestatuschange` | `games_gamestatuschange_game_id_90c2cee6_fk_games_game_id` |

These must be hardcoded in the `RunSQL` operations. The `DROP CONSTRAINT IF
EXISTS` syntax handles unknown names gracefully.

### Model removal

In `games/models.py`:
- Delete `PlayEventQuerySet` (line ~1350) and `PlayEvent` (line ~1356)
- Delete `GameStatusChangeQuerySet` (line ~1401) and `GameStatusChange` (line ~1407)

These deletions happen AFTER the migration is created and verified.

### Cross-cutting updates

**`games/removal.py`:** Remove `PlayEvent` from `REMOVABLE_MODELS` and its import.

**`games/identity_audit.py`:** Remove the `"games_gamestatuschange": "timestamp"`
entry from `IDENTITY_ORDER_SOURCE` and the comment referencing
`GameStatusChange`.

**`games/filters.py`:** Remove the `renamed_fields` class variable containing the
`"playevent_count"` and `"playevent_filter"` aliases.

**`games/management/commands/load_sample_data.py`:** Remove imports of
`PlayEvent`, `GameStatusChange`, `backfill_library`, and the
`playthrough_start` sub-modules. Remove `"games.playevent"` and
`"games.gamestatuschange"` from the data dump mapping.

**`games/management/commands/audit_library_ownership.py`:** Remove PlayEvent and
GameStatusChange count queries and their imports.

**`games/management/commands/anonymize_sample.py`:** Remove PlayEvent import,
anonymization logic, count reporting, and `"games.PlayEvent"` from
`IDENTITY_MODELS`.

**`ts/elements/filter-tree/fixtures.json`:** Remove the three `game__playevents__ended`
comparison entries.

**`ts/elements/filter-tree/fixtures.canonical.json`:** Remove the three
corresponding `game__playevents__ended` canonical entries.

### Test cleanup

~25 test files need updates. They fall into three categories:

1. **Tests for deleted functionality — removed entirely:**
   - `tests/test_playthrough_conversion.py` — tests the conversion pass
   - `tests/test_playthrough_preflight.py` — tests the preflight report
   - `tests/test_playergame_backfill.py` — tests the PlayerGame backfill
   - `tests/test_playthrough_start_repair.py` — tests the start repair pass AND
     the `report_playthrough_starts` command (54 tests, 974 lines)
   - `tests/test_generated_days_to_finish.py` — tests the `days_to_finish` generated field on PlayEvent

2. **Tests that create PlayEvent/GameStatusChange fixtures — remove setup and
   assertions:**
   - `tests/test_removal.py` — remove PlayEvent import, fixture creation, and
     the test that uses them (`test_the_api_removes_a_playthrough`)
   - `tests/test_removal_confirmation.py` — remove PlayEvent import and the
     `"playevent"` fixture entries in the confirmation tests
   - `tests/test_playergame_view_cutover.py` — remove PlayEvent import and
     fixture creation; convert remaining tests to use Playthrough
   - `tests/test_playthrough_api_writes.py` — remove PlayEvent import and all
     fixture creation; convert remaining tests to use Playthrough
   - `tests/test_playergame_playthrough_gate.py` — remove backfill imports and
     PlayEvent fixture creation
   - `tests/test_session_playhistory_runtime_identity.py` — remove conversion
     fixture and PlayEvent fixture creation; convert to use Playthrough
   - `tests/test_playergame_history_read.py` — remove backfill import and
     GameStatusChange fixture creation; convert to use PlayerGame events
   - `tests/test_session_playhistory_identity.py` — remove PlayEvent and
     GameStatusChange UUID identity tests; these test that the DB generates
     UUIDv7 for these models
   - `tests/test_session_playhistory_uuid_primary_key.py` — remove PlayEvent
     and GameStatusChange entries from migration snapshot tests
   - `tests/test_catalog_hierarchy_migration.py` — remove PlayEvent and
     GameStatusChange from migration fixture setup
   - `tests/test_catalog_hierarchy.py` — remove PlayEvent from the model list
     parameterized test
   - `tests/test_anonymize_sample.py` — remove PlayEvent import, fixture
     creation, and the anonymization assertions
   - `tests/test_library_commands.py` — remove PlayEvent import and fixture
     creation; update the FK assertion for `"games.playevent"`
   - `tests/test_library_models.py` — remove PlayEvent and GameStatusChange
     imports and the `for_library` fixture test
   - `tests/test_library_page_isolation.py` — remove PlayEvent fixture creation
   - `tests/test_retention.py` — remove PlayEvent import and fixture creation
   - `tests/test_uuid_identity_audit.py` — remove `("games_playevent", "game_id")`
     from FK audit assertions and the GameStatusChange UUID test
   - `tests/test_table_width_policy.py` — remove GameStatusChange import and
     fixture creation; the `test_playevents_note_column_may_wrap` test is for
     the playthroughs list page HTML width policy and remains valid
   - `tests/test_session_timezones.py` — remove GameStatusChange import and the
     `_meta.get_fields()` assertion
   - `tests/test_external_reference_migration.py` — remove PlayEvent and
     GameStatusChange from migration fixture setup
   - `tests/test_game_detail_links.py` — remove PlayEvent import and fixture
     creation
   - `tests/test_playthrough_view_cutover.py` — remove PlayEvent import and all
     fixture creation; convert remaining tests to use Playthrough

3. **Tests that reference PlayEventFilter aliases:**
   - `tests/test_filters.py` — remove the four alias-reading test methods
     (`test_the_old_count_key_is_read_as_the_new_one`,
     `test_the_old_relation_key_is_read_as_the_new_one`,
     `test_the_current_key_wins_where_a_blob_holds_both`,
     `test_a_nested_operator_renames_too`), remove PlayEvent import and
     fixture creation, remove `_comparison_group_for(PlayEvent)` assertion,
     and remove `_lookup_is_nullable(PlayEvent)` assertions

**Not changed:** `tests/test_playthrough_preset_migration.py` — the
`mode="playevents"` → `"playthroughs"` migration (0046) is independent of
the PlayEvent model and should remain.

## Rollback and reversibility

This change is **not reversible** in production. The two tables are dropped, and
the conversion events are the only copy of the data. This is acceptable because:

1. The conversion migration (0045) is `atomic=True` and has been verified to
   complete successfully on all libraries.
2. The start-repair migration (0048) is `elidable=True` and has been verified.
3. The tables are empty on any deployment that reached this point.
4. The charter's principle of preserving history is satisfied by the event store,
   which now holds the complete history.

If rollback is needed, revert to the commit before the migration runs and the
models are deleted.

## Verification Results

**Date:** 2026-09-10
**Status:** ✅ All migration verification complete

### What was tested

| Step | Status |
|------|--------|
| Create fresh database, apply migrations 0001-0048 | ✅ OK |
| Create migration 0049 that drops FK constraints using `RunSQL` | ✅ OK |
| Apply migration 0049 | ✅ OK |
| Create migration 0050 that drops GameStatusChange FK | ✅ OK |
| Create migration 0051 that drops GameStatusChange table | ✅ OK |
| Create migration 0052 that drops PlayEvent table | ✅ OK |
| Create migration 0053 that clears ContentType entries | ✅ OK |
| Apply all 5 migrations (0049-0053) to fresh database | ✅ OK |
| Run `makemigrations --check --dry-run` | ✅ "No changes detected" |
| Run `pytest tests/test_removal.py` (triggers test DB creation) | ⚠️ 4 passed, 1 failed (expected — model class still exists) |

### What this proves

- Django's test database creation works when FK constraints are removed before
  the test flush runs
- The `RunSQL` approach with hardcoded constraint names works
- Test database flush succeeds (no `cannot truncate a table referenced in a
  foreign key constraint` errors)
- `makemigrations --check` reports "No changes detected" — migration sequence
  is self-consistent with Django's model state
- ContentType cleanup SQL works (deletes permissions first, then ContentType
  entries) — entries are re-created by `post_migrate` until model classes are
  deleted from `models.py`
- The 1 test failure (`test_the_api_removes_a_playthrough_rather_than_destroying_it`) is
  expected: the model class `PlayEvent` still exists in `models.py` but the
  table has been dropped. This resolves when we delete the model class.

## Migration-first verification plan

**Status:** ✅ COMPLETED

All five migrations (0049-0053) have been created, applied, and verified:
- `0049_remove_playevent_game_fk` — drops FK constraint on `games_playevent.game_id`
- `0050_remove_gamestatuschange_game_fk` — drops FK constraint on `games_gamestatuschange.game_id`
- `0051_drop_gamestatuschange_table` — drops the `games_gamestatuschange` table
- `0052_drop_playevent_table` — drops the `games_playevent` table
- `0053_clear_content_types` — deletes `auth_permission` and `ContentType` entries

`makemigrations --check --dry-run` reports "No changes detected" — the
migration sequence is self-consistent with Django's model state.

### Next: proceed with model deletion

Once the migration sequence is verified, proceed with:
1. Delete model classes from `models.py`
2. Update cross-cutting modules
3. Update tests
4. Run full test suite
5. Verify `makemigrations` still reports "No changes detected"

## Verification

### Unit tests

- All PlayEvent/GameStatusChange fixtures removed from test files.
- All PlayEventFilter alias-reading tests removed.
- Tests for deleted backfill modules removed entirely.
- Remaining tests pass with `pytest -x`.

### Acceptance criteria

- The approved issue-level specification defines dependencies, rollback or
  reversibility where relevant, and exact verification.
- The outcome is implemented with focused tests and migration/reconciliation
  evidence where data changes.
- Affected filters, saved presets, statistics, APIs, attribution, and user
  isolation are updated where applicable.
- The full `make check` gate passes.

### Specific checks

1. **Model removal:** `grep -rn "PlayEvent\|GameStatusChange" --include="*.py" games/` returns no results except in `games/migrations/` (historical migrations that reference the models by name for data integrity).
2. **Filter cleanup:** `grep -rn "PlayEventFilter" --include="*.py" games/ tests/` returns no results.
3. **Related name cleanup:** `grep -rn "playevents" --include="*.py" games/` returns no results except in `games/migrations/`.
4. **Filter aliases:** `grep -rn "playevent_count\|playevent_filter" --include="*.py" games/` returns no results.
5. **Test suite:** `make check` passes with no failures.
6. **Frontend fixtures:** `grep -rn "playevents__ended" --include="*.json" ts/` returns no results.

## Lessons from abandoned v1

1. **Migration-first, not code-first.** Design the migration sequence and verify
   it works in isolation BEFORE deleting model classes.
2. **Test database flush is the killer.** Django's flush truncates all tables after
   applying migrations. If a table has FK constraints, truncation fails. The
   migration must remove FK constraints BEFORE the table is dropped.
3. **Auto-generated migrations don't handle FK constraints well.** Django's
   `makemigrations` generates `RemoveField` operations that try to drop FK
   constraints at the same time as dropping the table, but the test flush happens
   between migration application and test execution, and it doesn't know about
   the FK constraint chain.
4. **Manual migration design is safer.** Write the migration manually with
   explicit `RunSQL` operations that remove FK constraints first, then drop tables.
   This gives full control over the order of operations.
