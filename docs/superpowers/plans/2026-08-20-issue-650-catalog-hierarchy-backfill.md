# CAT-03 Existing Game Catalog Hierarchy Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Atomically migrate every existing Game into one explicit default Edition/Release graph while preserving its UUID, legacy state, ownership boundary, and exact year/Platform meaning.

**Architecture:** Add one idempotent historical-model data migration after `0019` that preflights legacy values, bulk-synchronizes canonical fields and missing default children, re-runs its ensure step to prove identity stability, and fails closed after deterministic whole-dataset reconciliation. The exact migration emits a versioned compact JSON record plus a human summary and one human line for every mismatch; the ordinary verified production backup and prior image are the only deployment rollback.

**Tech Stack:** Python 3.14, Django 6 historical migrations/ORM, PostgreSQL 17 temporal and UUIDv7 domains, pytest-django migration harnesses, pytest-xdist, Make, `pg_dump`/`pg_restore`.

**Spec:** `docs/superpowers/specs/2026-08-20-issue-650-catalog-hierarchy-backfill-design.md`

## Global Constraints

- Treat issue #650, the overhaul charter, the catalog wave specification, and delivered #649/#888 behavior as authoritative.
- Preserve every Game UUID and never merge or look up by name, year, Platform, Wikidata, external identifier, child count, or UUID order.
- Map `original_year_released` to Game original-release year precision, `year_released` to default Release year precision, and the exact legacy Platform to that Release; SQL NULL remains unknown/unspecified.
- Reuse only explicitly default children; preserve every non-default Edition and Release unchanged.
- Keep status, mastered, playtime, sort name, Wikidata, timestamps, and all existing Game relationships on the same Game row.
- Use historical models from `apps`; do not import or call the live `games.catalog_writes` service from migration history.
- Collect and emit every detected mismatch deterministically; any mismatch raises inside the atomic migration transaction.
- Emit the exact version-1 machine JSON, human summary, and human mismatch lines defined by the paired design.
- Make a repeated forward pass insert zero children and preserve every default Edition/Release UUID.
- Use a no-op reverse data function. Rollback after deployment is restore of the ordinary verified backup plus the prior application image, never destructive reverse data logic.
- Rehearse the exact migration against a current production copy and separately prove restore of that same verified artifact before opening the PR.
- Do not change runtime reads/writes, forms, URLs, APIs, filters, statistics, templates, frontend code, external references, shared catalog rules, or unrelated code.
- Run `make check` with the Makefile's default `PYTEST_WORKERS`; do not set normal verification to serial mode.
- Stop and return to the design gate if actual scope crosses three independent runtime subsystems, 40 files, 2,000 non-generated changed lines, or requires an application/runtime command.

## File structure

- Create `games/migrations/0020_catalog_hierarchy_backfill.py`: own source snapshot, preflight, batched default-graph synchronization, repeated-pass identity proof, deterministic reconciliation, output, and atomic failure.
- Modify `tests/test_catalog_hierarchy_migration.py`: extend the existing historical migration harness with CAT-03 fixtures and happy-path, preservation, output, mismatch, transaction, idempotency, and reverse/no-op coverage.
- Remove this plan and its paired issue design only after implementation, production-copy/restore rehearsal, and all verification pass; preserve the planning commit in the pushed branch/PR history.

## Planning gate checkpoint

Commit this plan and its paired design, then stop for explicit approval. No Task
1 step may start before approval.

```bash
git add docs/superpowers/specs/2026-08-20-issue-650-catalog-hierarchy-backfill-design.md docs/superpowers/plans/2026-08-20-issue-650-catalog-hierarchy-backfill.md
git commit -m "docs: plan existing Game catalog backfill"
```

---

### Task 1: Pin the successful historical migration contract

**Files:**
- Modify: `tests/test_catalog_hierarchy_migration.py`
- Create later: `games/migrations/0020_catalog_hierarchy_backfill.py`

**Interfaces:**
- Consumes: historical schema `games.0019_catalog_write_defaults`.
- Produces: historical schema `games.0020_catalog_hierarchy_backfill` with no model-state changes.
- Preserves: exact Game UUID/state and representative dependent links.
- Maps: legacy years to four-digit year precision and exact Platform/NULL to one explicit default graph.

- [ ] **Step 1: Extend migration constants and add a CAT-03 harness**

At the top of `tests/test_catalog_hierarchy_migration.py`, retain all existing
constants and add:

```python
BEFORE_CATALOG_BACKFILL = WITH_CATALOG_WRITES
WITH_CATALOG_BACKFILL = ("games", "0020_catalog_hierarchy_backfill")
```

Add a fixture with the same cleanup discipline as the existing harnesses:

```python
@pytest.fixture
def catalog_backfill_migration_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CATALOG_BACKFILL])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_CATALOG_BACKFILL]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_catalog_backfill():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_CATALOG_BACKFILL])
    return executor.loader.project_state([WITH_CATALOG_BACKFILL]).apps
```

- [ ] **Step 2: Add a mixed source-world builder**

Add `seed_catalog_backfill_world(apps)` using only historical models. Build two
users/libraries, one shared Platform, one private Platform per library, and
three Games:

1. library A, name `"Same Name"`, known original/release years and shared
   Platform, with no Edition;
2. library B, the exact same name and years, NULL Platform and unknown original
   year, with an existing explicit default Edition/Release whose canonical
   values are deliberately stale; and
3. library A, name `"Existing children"`, unknown release year and its private
   Platform, with one non-default Edition/Release carrying a non-NULL date and
   Platform.

Give the Games distinct explicit `uuid.uuid7()` values. Set distinctive
`sort_name`, `wikidata`, status, mastered, and playtime values. Add one
representative historical `Session`, `PlayEvent`, `GameStatusChange`,
`Purchase.related_game`, and `Purchase.games` link wherever required fields in
the frozen `0019` models permit it. Return a dictionary containing all source
Game IDs, Platform IDs, preserved field tuples, existing child IDs, and
dependent-link target IDs so the test compares identities rather than names.

Use `TemporalValue` only in test assertions after migration; seed the stale
canonical values as strings (`"1980"`, `"1981"`) accepted by the historical
field.

- [ ] **Step 3: Write the successful mapping and preservation test**

Add:

```python
def test_catalog_backfill_maps_every_game_without_merging_or_changing_legacy_state(
    catalog_backfill_migration_harness,
    capsys,
):
    seeded = seed_catalog_backfill_world(catalog_backfill_migration_harness)
    apps = migrate_to_catalog_backfill()
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")

    assert set(Game.objects.values_list("pk", flat=True)) == set(seeded["game_ids"])
    for game_id, expected in seeded["preserved_games"].items():
        game = Game.objects.get(pk=game_id)
        assert preserved_game_tuple(game) == expected

    graph_ids = {}
    for game_id in seeded["game_ids"]:
        edition = Edition.objects.get(game_id=game_id, is_default=True)
        release = Release.objects.get(edition=edition, is_default=True)
        graph_ids[game_id] = (edition.pk, release.pk)

    assert len({*graph_ids.values()}) == len(seeded["game_ids"])
    assert graph_ids[seeded["prewritten_game_id"]] == seeded[
        "prewritten_default_ids"
    ]
    assert Edition.objects.filter(is_default=True).count() == len(seeded["game_ids"])
    assert Release.objects.filter(is_default=True).count() == len(seeded["game_ids"])

    known = Game.objects.get(pk=seeded["known_game_id"])
    known_release = Release.objects.get(
        edition__game_id=known.pk,
        edition__is_default=True,
        is_default=True,
    )
    assert known.original_release_date == TemporalValue.from_year(2000)
    assert known_release.release_date == TemporalValue.from_year(2001)
    assert known_release.platform_id == seeded["shared_platform_id"]

    unknown = Game.objects.get(pk=seeded["unknown_game_id"])
    unknown_release = Release.objects.get(
        edition__game_id=unknown.pk,
        edition__is_default=True,
        is_default=True,
    )
    assert unknown.original_release_date is None
    assert unknown_release.release_date == TemporalValue.from_year(2001)
    assert unknown_release.platform_id is None

    nondefault_release = Release.objects.get(pk=seeded["nondefault_release_id"])
    assert (
        nondefault_release.edition_id,
        nondefault_release.release_date.serialize(),
        nondefault_release.platform_id,
        nondefault_release.is_default,
    ) == seeded["nondefault_release"]
    assert_dependent_game_links(apps, seeded)
```

Import `TemporalValue` and implement the two tiny assertion helpers next to the
world builder. `preserved_game_tuple` must include exactly the preserved fields
listed in the design. `assert_dependent_game_links` compares foreign-key/M2M
IDs to the returned source UUIDs.

- [ ] **Step 4: Run the new happy-path test to verify RED**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_hierarchy_migration.py::test_catalog_backfill_maps_every_game_without_merging_or_changing_legacy_state -q
```

Expected: FAIL because migration node `games.0020_catalog_hierarchy_backfill`
does not exist.

- [ ] **Step 5: Commit only after Task 2 makes the test green**

Do not commit a deliberately failing test alone. Task 2 completes this
test/implementation cycle, then commits both files together.

---

### Task 2: Implement the atomic idempotent backfill and success report

**Files:**
- Create: `games/migrations/0020_catalog_hierarchy_backfill.py`
- Modify: `tests/test_catalog_hierarchy_migration.py`

**Interfaces:**
- Produces: `backfill_catalog_hierarchy(apps, schema_editor) -> None` for `RunPython`.
- Produces: `_ensure_default_graphs(apps) -> tuple[int, int]`, returning inserted Edition and Release counts.
- Produces: `_default_graph_ids(apps) -> tuple[tuple[str, str, str], ...]` in Game UUID order.
- Produces: deterministic `CATALOG_HIERARCHY_RECONCILIATION_JSON=...` and `CAT hierarchy reconciliation: ...` lines.

- [ ] **Step 1: Create migration constants and normalization helpers**

Create `games/migrations/0020_catalog_hierarchy_backfill.py` with imports:

```python
import json

from django.db import migrations

MACHINE_PREFIX = "CATALOG_HIERARCHY_RECONCILIATION_JSON="
HUMAN_PREFIX = "CAT hierarchy reconciliation:"
BATCH_SIZE = 1000
PRESERVED_GAME_FIELDS = (
    "library_id",
    "name",
    "sort_name",
    "original_year_released",
    "year_released",
    "platform_id",
    "wikidata",
    "status",
    "mastered",
    "playtime",
    "created_at",
    "updated_at",
)
SUMMARY_KEYS = (
    "games",
    "editions",
    "releases",
    "default_editions",
    "default_releases",
    "original_dates_known",
    "original_dates_unknown",
    "release_dates_known",
    "release_dates_unknown",
    "unspecified_platforms",
    "mismatches",
)
```

Implement `_json_value(value)` so NULL stays `None`, scalar strings/integers/
booleans stay scalar, and UUID/date/datetime/timedelta/model-field values use
`str(value)`. Implement `_year_value(year)` as `None` for NULL and
`f"{year:04d}"` for integers in `1..9999`. Preflight, rather than this helper,
owns invalid-year reporting.

- [ ] **Step 2: Snapshot preserved Game state and preflight all source rows**

Implement `_game_snapshot(Game)` as an ordered dictionary keyed by `str(pk)`;
each value is a dictionary of `PRESERVED_GAME_FIELDS` normalized with
`_json_value`. Query with `.order_by("pk").values("pk", *PRESERVED_GAME_FIELDS)`.

Implement `_preflight_mismatches(apps, snapshot)` to return all of:

- `invalid_original_year` for each non-NULL `original_year_released` outside
  `1..9999`;
- `invalid_release_year` for each non-NULL `year_released` outside `1..9999`;
  and
- `legacy_platform_cross_library` for each Game whose Platform has a non-NULL
  library unequal to `Game.library_id`.

Each object has `code`, `game_id`, and exact `field`/`expected`/`actual` or
`platform_id`/`game_library_id`/`platform_library_id` keys. Do not raise inside
the loop.

- [ ] **Step 3: Implement batched canonical synchronization**

Implement `_ensure_default_graphs(apps)` using frozen `Game`, `Edition`, and
`Release` models:

1. Load Games ordered by UUID. Assign `game.original_release_date =
   _year_value(game.original_year_released)` and `bulk_update` only
   `original_release_date` with `batch_size=BATCH_SIZE`.
2. Read existing default Game IDs, construct `Edition(game_id=..., is_default=True)`
   only for missing Games, and `bulk_create` with the same batch size. No
   `ignore_conflicts`: the application is offline and any unexpected conflict
   must fail rather than be hidden.
3. Build the exact `game_id -> default_edition_id` map and create a default
   Release only for default Editions missing one.
4. Load all default Releases with their Edition's Game source values. Assign
   exact `_year_value(game.year_released)` and `game.platform_id`, then
   `bulk_update` only `release_date` and `platform`.
5. Return `(inserted_edition_count, inserted_release_count)`.

Do not touch non-default rows. Do not use `.first()`, ordering as selection,
names, years, Platforms, or the live catalog service.

- [ ] **Step 4: Implement graph identity and reconciliation collectors**

Implement `_default_graph_ids(apps)` with one values query ordered by Game UUID
and return string triples `(game_id, edition_id, release_id)`. Missing graphs
are absent here and separately reported.

Implement `_result_mismatches(apps, before_snapshot, first_graph_ids,
second_graph_ids, second_insert_counts)` to collect:

- `missing_game` and `extra_game` from snapshot/current UUID set differences;
- one `preserved_game_field_changed` per changed preserved field;
- `default_edition_count` per Game unless the count is exactly one;
- `default_release_count` per default Edition unless the count is exactly one;
- `original_date_mismatch`, `release_date_mismatch`, and
  `release_platform_mismatch` against the legacy columns;
- `release_platform_cross_library` for a private foreign Platform; and
- `non_idempotent_default_graph` if second-pass insert counts are not `(0, 0)`
  or the two ordered graph-ID tuples differ.

Use exact IDs and normalized expected/actual values in each object. Query all
rows and append every mismatch; never raise early.

Implement `_summary(apps, mismatch_count)` from the post-write state. Total
Edition/Release counts include non-default rows. Date known/unknown and
unspecified Platform counts cover only Game original dates and explicit default
Releases, respectively. Assert no unclassified temporal kind by producing a
`temporal_kind_mismatch` rather than silently excluding it.

- [ ] **Step 5: Implement deterministic output and failure**

Implement:

```python
def _mismatch_sort_key(mismatch):
    return tuple(
        str(mismatch.get(key) or "")
        for key in (
            "code",
            "game_id",
            "edition_id",
            "release_id",
            "field",
            "expected",
            "actual",
        )
    )


def _emit(summary, mismatches):
    mismatches = sorted(mismatches, key=_mismatch_sort_key)
    payload = {
        "schema_version": 1,
        "summary": summary,
        "mismatches": mismatches,
    }
    print(
        MACHINE_PREFIX
        + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )
    print(
        HUMAN_PREFIX
        + " "
        + " ".join(f"{key}={summary[key]}" for key in SUMMARY_KEYS)
    )
    for mismatch in mismatches:
        details = " ".join(
            f"{key}={_human_value(value)}"
            for key, value in sorted(mismatch.items())
            if key != "code"
        )
        print(
            f"CAT hierarchy mismatch: code={mismatch['code']}"
            + (f" {details}" if details else "")
        )
```

`_human_value(None)` returns `null`; other values use `str(value)`. `_emit`
must receive `summary["mismatches"] == len(mismatches)`.

- [ ] **Step 6: Wire the forward migration in the required order**

Implement:

```python
def backfill_catalog_hierarchy(apps, schema_editor):
    del schema_editor
    Game = apps.get_model("games", "Game")
    before_snapshot = _game_snapshot(Game)
    mismatches = _preflight_mismatches(apps, before_snapshot)
    if mismatches:
        summary = _summary(apps, len(mismatches))
        _emit(summary, mismatches)
        raise RuntimeError(
            f"CAT hierarchy reconciliation failed with {len(mismatches)} mismatch(es)."
        )

    _ensure_default_graphs(apps)
    first_graph_ids = _default_graph_ids(apps)
    second_insert_counts = _ensure_default_graphs(apps)
    second_graph_ids = _default_graph_ids(apps)
    mismatches = _result_mismatches(
        apps,
        before_snapshot,
        first_graph_ids,
        second_graph_ids,
        second_insert_counts,
    )
    summary = _summary(apps, len(mismatches))
    _emit(summary, mismatches)
    if mismatches:
        raise RuntimeError(
            f"CAT hierarchy reconciliation failed with {len(mismatches)} mismatch(es)."
        )


class Migration(migrations.Migration):
    dependencies = [("games", "0019_catalog_write_defaults")]
    operations = [
        migrations.RunPython(
            backfill_catalog_hierarchy,
            migrations.RunPython.noop,
        )
    ]
```

Keep the migration atomic (the Django default); do not set `atomic = False`.

- [ ] **Step 7: Pin the exact success output**

Finish the Task 1 test by reading `capsys.readouterr().out.splitlines()`. Parse
the one line starting with `MACHINE_PREFIX`, and compare the full literal
payload. Also compare the full human line literal. Derive only fixture UUID
values; all summary numbers must be literal expectations from the three-Game
world. Assert `mismatches == []` and `summary["mismatches"] == 0`.

- [ ] **Step 8: Run the happy-path migration test to GREEN**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_hierarchy_migration.py::test_catalog_backfill_maps_every_game_without_merging_or_changing_legacy_state -q
```

Expected: PASS.

- [ ] **Step 9: Commit the first independently testable migration slice**

```bash
git add games/migrations/0020_catalog_hierarchy_backfill.py tests/test_catalog_hierarchy_migration.py
git commit -m "feat: backfill default catalog graphs"
```

---

### Task 3: Prove whole-report failure, rollback, idempotency, and reverse behavior

**Files:**
- Modify: `tests/test_catalog_hierarchy_migration.py`
- Modify if tests expose a gap: `games/migrations/0020_catalog_hierarchy_backfill.py`

**Interfaces:**
- Consumes: the Task 2 migration helpers and output contract.
- Produces: evidence that every source mismatch is reported and every failed write rolls back.
- Preserves: no-op reverse and repeat-safe forward behavior.

- [ ] **Step 1: Write a multi-mismatch preflight/rollback test**

Seed two libraries and one private Platform owned by library B. In library A,
create one Game using that foreign Platform with `original_year_released=0` and
`year_released=10000`. Capture its exact `0019` fields. Run a new
`MigrationExecutor(connection).migrate([WITH_CATALOG_BACKFILL])` inside:

```python
with pytest.raises(
    RuntimeError,
    match=r"CAT hierarchy reconciliation failed with 3 mismatch\(es\)\.",
):
    executor.migrate([WITH_CATALOG_BACKFILL])
```

Assert the JSON array contains exactly these codes in deterministic order:
`invalid_original_year`, `invalid_release_year`, and
`legacy_platform_cross_library`, with the exact Game/Platform/library IDs and
values. Assert all three exact human mismatch lines are present. Rebuild the
migration executor after failure and prove the database leaf is still `0019`,
the Game is unchanged, and Edition/Release counts remain zero.

- [ ] **Step 2: Write direct repeated-forward identity coverage**

After a successful migration, capture all default triples and total child
counts. Import the migration module with:

```python
from importlib import import_module

catalog_backfill = import_module(
    "games.migrations.0020_catalog_hierarchy_backfill"
)
```

Call `catalog_backfill.backfill_catalog_hierarchy(apps, None)` using the frozen
`0020` app state. Assert the triples/counts are unchanged and the second report
has zero mismatches. This tests the whole forward function, not only an
internal helper.

- [ ] **Step 3: Write empty-database and reverse/no-op tests**

For an empty `0019` database, migrate forward and compare the exact zero-valued
JSON/human reports. Then seed and migrate a populated world, record canonical
and child rows, migrate backward to `0019`, and assert the data remains present
unchanged. Migrate forward again and assert no new children and zero
mismatches. This pins the documented no-op reverse without pretending it is a
deployment rollback.

- [ ] **Step 4: Run the new tests to verify meaningful RED where needed**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_hierarchy_migration.py -k 'catalog_backfill' -q
```

If a test unexpectedly passes before its intended guard exists, temporarily
remove the corresponding preflight, second-pass comparison, output line, or
exception and prove that exact test fails; restore immediately. Do not commit
the temporary mutation.

- [ ] **Step 5: Fix only reconciliation gaps and run the full migration file**

Update only the Task 2 migration helper needed by a failing contract. Then run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_hierarchy_migration.py -q
```

Expected: PASS, including all #649 and #888 historical migration coverage.

- [ ] **Step 6: Run focused catalog regression suites**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py tests/test_catalog_writes.py tests/test_catalog_write_views.py -q
```

Expected: PASS with the default pytest configuration.

- [ ] **Step 7: Commit reconciliation hardening**

```bash
git add games/migrations/0020_catalog_hierarchy_backfill.py tests/test_catalog_hierarchy_migration.py
git commit -m "test: prove catalog backfill reconciliation"
```

---

### Task 4: Rehearse the exact production copy and rollback-by-restore

**Files:**
- No repository file changes expected.
- Retain protected dump, hash, migration logs, and reconciliation evidence outside Git.

**Interfaces:**
- Consumes: a current ordinary custom-format production backup and this exact branch.
- Produces: successful exact migration evidence and successful restore evidence without mutating production.

- [ ] **Step 1: Establish protected task-specific paths and verify the backup**

Use an existing current production backup created with the flags in
`docs/deployment.md`. Set task-specific variables without printing credentials:

```bash
CAT650_REHEARSAL_DIR=$(mktemp -d /tmp/timetracker-cat650-rehearsal.XXXXXX)
CAT650_DUMP=/absolute/protected/path/to/current-timetracker.dump
sha256sum "$CAT650_DUMP" | tee "$CAT650_REHEARSAL_DIR/source.sha256"
pg_restore --list "$CAT650_DUMP" > "$CAT650_REHEARSAL_DIR/archive.list"
```

Record the source application/migration leaf alongside the protected evidence.
Do not commit the dump, hash record, SQL output, or credentials.

- [ ] **Step 2: Restore into a newly created disposable database**

Choose explicit admin/app URLs for a dedicated CAT-03 database, create it, and
restore with the documented flags:

```bash
set -o pipefail
createdb --maintenance-db="$CAT650_ADMIN_URL" timetracker_cat650_rehearsal
pg_restore --exit-on-error --no-owner --no-privileges \
  --dbname="$CAT650_REHEARSAL_URL" "$CAT650_DUMP" \
  2>&1 | tee "$CAT650_REHEARSAL_DIR/restore.log"
```

The URLs must target only the disposable database. Validate the database name
before any later cleanup; never use a broad path, unresolved variable, or
production URL as a destructive target.

- [ ] **Step 3: Capture exact before evidence**

With `DATABASE_URL="$CAT650_REHEARSAL_URL"`, record `showmigrations games`,
Game count, known/unknown legacy original/release years, specified/unspecified
Platforms, same-name groups, and representative relationship counts. Use
read-only SQL/ORM queries and save output under `$CAT650_REHEARSAL_DIR`.

- [ ] **Step 4: Run the exact branch migration offline and retain output**

Run:

```bash
set -o pipefail
DATABASE_URL="$CAT650_REHEARSAL_URL" \
  direnv exec . uv run --frozen python manage.py migrate \
  2>&1 | tee "$CAT650_REHEARSAL_DIR/migrate.log"
```

Record exit status and elapsed time. Extract the single
`CATALOG_HIERARCHY_RECONCILIATION_JSON=` line, parse its JSON suffix, and assert
`schema_version == 1`, `summary.mismatches == 0`, an empty mismatch array, and
the exact before/after count equations. Retain the exact human summary too.

- [ ] **Step 5: Run post-migration ownership and graph checks**

Run `showmigrations games`, `migrate --check`, and:

```bash
set -o pipefail
DATABASE_URL="$CAT650_REHEARSAL_URL" \
  direnv exec . uv run --frozen python manage.py audit_library_ownership --all-libraries \
  2>&1 | tee "$CAT650_REHEARSAL_DIR/ownership-audit.log"
```

Use read-only SQL/ORM checks to prove every Game has one default Edition and
Release, exact known/unknown dates and Platform mapping, same-name rows retain
distinct Game/default UUIDs, non-default children are unchanged if present,
and representative incoming relationships still point at the original Game
UUIDs.

- [ ] **Step 6: Prove rollback-by-restore with the same artifact**

Create a second explicitly named clean disposable database (or, after retaining
the migrated evidence, recreate the first only after validating its exact
name). Restore the same hash-verified dump with `--exit-on-error --no-owner
--no-privileges`. Confirm its migration leaf and all Step 3 before-counts match,
and `python manage.py migrate --check` reports the expected unapplied catalog
wave migrations rather than applying them. Record the restore exit status.

Document the deployment rollback sequence in the retained evidence: keep
web/worker offline, replace the failed database with a clean restore of this
artifact, point the prior application image at it, verify leaf/counts, then
start processes. Do not use `migrate games 0019` as rollback evidence.

- [ ] **Step 7: Report rehearsal evidence without exposing protected data**

In the eventual PR body, record the dump date/identifier (not its path or
contents), abbreviated SHA-256, migration/restore exit statuses, elapsed time,
exact reconciliation summary, ownership audit result, and before/after count
equations. Keep full logs and dump outside Git.

---

### Task 5: Complete verification, scope audit, cleanup, push, and PR

**Files:**
- Delete after all gates pass: `docs/superpowers/specs/2026-08-20-issue-650-catalog-hierarchy-backfill-design.md`
- Delete after all gates pass: `docs/superpowers/plans/2026-08-20-issue-650-catalog-hierarchy-backfill.md`
- Review: every file changed from `origin/codex/catalog-wave`

**Interfaces:**
- Consumes: green implementation, focused tests, and production-copy/restore evidence.
- Produces: one verified issue-only branch and PR targeting `codex/catalog-wave`.

- [ ] **Step 1: Run focused catalog verification again**

Run:

```bash
direnv exec . uv run --frozen pytest tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py tests/test_catalog_writes.py tests/test_catalog_write_views.py -q
```

Expected: PASS.

- [ ] **Step 2: Verify migration state and whitespace**

Run:

```bash
direnv exec . uv run --frozen python manage.py makemigrations --check
git diff --check origin/codex/catalog-wave...HEAD
```

Expected: “No changes detected” and no diff-check output.

- [ ] **Step 3: Run the required full gate with default workers**

Run exactly:

```bash
direnv exec . make check
```

Expected: exit 0. Do not set `PYTEST_WORKERS`; retain the Makefile default.

- [ ] **Step 4: Audit issue-only scope and thresholds**

Run:

```bash
git diff --stat origin/codex/catalog-wave...HEAD
git diff --numstat origin/codex/catalog-wave...HEAD
git status --short
```

Confirm only the migration and focused migration test remain in the final tree
diff, fewer than 40 implementation/test files, fewer than 2,000 non-generated
changed lines, and no second independent runtime subsystem. If any threshold or
the design's two-file forecast is crossed, stop and return to approval before
continuing.

- [ ] **Step 5: Remove planning artifacts only after all green gates**

Delete the paired design and plan with `apply_patch`, then commit their removal:

```bash
git add docs/superpowers/specs/2026-08-20-issue-650-catalog-hierarchy-backfill-design.md docs/superpowers/plans/2026-08-20-issue-650-catalog-hierarchy-backfill.md
git commit -m "chore: remove catalog backfill planning artifacts"
```

The planning commit remains visible in the branch/PR range even though the
final target-tree diff contains implementation only.

- [ ] **Step 6: Run final lightweight integrity checks**

Run:

```bash
git diff --check origin/codex/catalog-wave...HEAD
git status --short --branch
```

Expected: no whitespace errors and a clean issue branch.

- [ ] **Step 7: Push and open the requested PR**

Push `codex/issue-650-catalog-hierarchy-migration` and open a GitHub PR with
base `codex/catalog-wave`. The PR body must summarize the mapping/default-graph
contract, deterministic machine/human reconciliation, mismatch rollback,
focused tests, production-copy migration and restore evidence, full
`make check` result with default workers, actual scope totals, and include
`Closes #650`.
