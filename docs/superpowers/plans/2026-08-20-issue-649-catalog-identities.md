# CAT-01 Catalog Identities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add passive Game, Edition, and Release catalog identities and temporal release-date storage without changing current reads, writes, or legacy data.

**Architecture:** Extend `Game` with #655's explicit temporal consumer columns, add a UUIDv7 `Edition` child of Game, and add a UUIDv7 `Release` child of Edition with an optional Platform and the same temporal consumer shape. Ship one additive schema migration with no data operation; model and migration tests prove identity, cardinality, temporal precision, delete behavior, passivity, fresh-schema shape, and reversibility.

**Tech Stack:** Python 3.14, Django ORM/migrations, PostgreSQL 17, pytest-django, pytest-xdist, Make.

**Spec:** `docs/superpowers/specs/2026-08-20-issue-649-catalog-identities-design.md`

## Global Constraints

- Treat issue #649, the overhaul charter, the catalog wave specification, and #655's temporal-value contract as authoritative.
- Preserve `Game.id` exactly; do not alter or regenerate existing Game UUIDs.
- Keep every legacy Game field and every current read/write surface unchanged.
- Add no backfill, catalog writer, adapter, UI, API, filter, statistic, PlayerGame, matching, IGDB, product relation, merge, tombstone, redirect, or external-reference behavior.
- `Edition` and `Release` use `UUIDv7Field` primary keys; Edition belongs to Game, Release belongs to Edition, and Release Platform is optional and explicit.
- Declare all nine columns for each temporal fact explicitly; do not hide them behind a dynamic model-field injector.
- Use `make test` and `make check` with the Makefile's default `PYTEST_WORKERS`; never set normal verification to serial mode.
- Stop and re-slice before approval if actual scope crosses three independent runtime subsystems, 40 files, or 2,000 non-generated changed lines.

## File structure

- Modify `games/models.py`: define Game original-release temporal fields and the Edition/Release models.
- Create `games/migrations/0018_catalog_hierarchy.py`: additive schema only, depending on `0017_temporal_value_domain`.
- Create `tests/test_catalog_hierarchy.py`: current-model identity, cardinality, dates, delete behavior, and legacy-write passivity.
- Create `tests/test_catalog_hierarchy_migration.py`: forward/reverse migration and PostgreSQL schema contract.
- Remove this plan and its paired issue design only after implementation and verification are complete; the approved gate remains in branch history.

---

### Task 1: Add the passive catalog hierarchy and its schema contract

**Files:**
- Modify: `games/models.py`
- Create: `games/migrations/0018_catalog_hierarchy.py`
- Create: `tests/test_catalog_hierarchy.py`
- Create: `tests/test_catalog_hierarchy_migration.py`

**Interfaces:**
- Consumes: `UUIDv7Field` from `timetracker.uuidv7` and the nine #655 field/expression types from `timetracker.temporal`.
- Produces: `Game.original_release_date` plus its eight generated projections.
- Produces: `Edition(id: UUIDv7, game: Game)` with reverse accessor `Game.editions` and Django cascade deletion.
- Produces: `Release(id: UUIDv7, edition: Edition, platform: Platform | None, release_date: TemporalValue | None)` with reverse accessors `Edition.releases` and `Platform.releases`, Edition cascade deletion, and Platform `SET_NULL` deletion.
- Produces: `Release.release_date` plus its eight generated projections.
- Produces: migration node `("games", "0018_catalog_hierarchy")`, with no data operation.

- [ ] **Step 1: Write failing current-model tests.**

Create `tests/test_catalog_hierarchy.py`. Import `Edition`, `Game`, `Platform`,
and `Release` from `games.models`, `GameForm` from `games.forms`, and
`TemporalValue` from `timetracker.temporal`. Add these exact behavioral cases:

```python
import uuid
from datetime import date

import pytest

from games.forms import GameForm
from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


def test_catalog_hierarchy_preserves_game_identity_and_allows_multiplicity(
    owned_library,
):
    game_id = uuid.uuid7()
    game = Game.objects.create(id=game_id, library=owned_library, name="Portal 2")
    standard = Edition.objects.create(game=game)
    deluxe = Edition.objects.create(game=game)
    standard_releases = [
        Release.objects.create(edition=standard),
        Release.objects.create(edition=standard),
    ]
    deluxe_release = Release.objects.create(edition=deluxe)

    assert game.pk == game_id
    assert game.editions.count() == 2
    assert standard.releases.count() == 2
    assert deluxe.releases.get() == deluxe_release
    assert {row.pk.version for row in (standard, deluxe, *standard_releases, deluxe_release)} == {7}


def test_game_and_release_temporal_values_preserve_year_and_unknown(
    owned_library,
):
    game = Game.objects.create(
        library=owned_library,
        name="Year Game",
        original_release_date=TemporalValue.from_year(1987),
    )
    edition = Edition.objects.create(game=game)
    known = Release.objects.create(
        edition=edition,
        release_date=TemporalValue.from_year(1998),
    )
    unknown = Release.objects.create(edition=edition, release_date=None)

    game.refresh_from_db()
    known.refresh_from_db()
    unknown.refresh_from_db()

    assert game.original_release_date == TemporalValue.from_year(1987)
    assert (
        game.original_release_date_lower,
        game.original_release_date_upper,
        game.original_release_date_kind,
        game.original_release_date_precision,
    ) == (date(1987, 1, 1), date(1987, 12, 31), "atomic", "year")
    assert known.release_date == TemporalValue.from_year(1998)
    assert (
        known.release_date_lower,
        known.release_date_upper,
        known.release_date_kind,
        known.release_date_precision,
        known.release_date_start_kind,
        known.release_date_end_kind,
        known.release_date_start_precision,
        known.release_date_end_precision,
    ) == (
        date(1998, 1, 1),
        date(1998, 12, 31),
        "atomic",
        "year",
        None,
        None,
        None,
        None,
    )
    assert unknown.release_date is None
    assert unknown.release_date_lower is None
    assert unknown.release_date_upper is None
    assert unknown.release_date_kind == "unknown"
    assert unknown.release_date_precision is None


def test_catalog_hierarchy_delete_behavior_is_explicit(owned_library):
    platform = Platform.objects.create(name="Delete Platform")
    game = Game.objects.create(library=owned_library, name="Delete Game")
    first_edition = Edition.objects.create(game=game)
    platform_release = Release.objects.create(
        edition=first_edition, platform=platform
    )

    platform.delete()
    platform_release.refresh_from_db()
    assert platform_release.platform_id is None

    first_release_id = platform_release.pk
    first_edition.delete()
    assert not Release.objects.filter(pk=first_release_id).exists()

    second_edition = Edition.objects.create(game=game)
    second_release = Release.objects.create(edition=second_edition)
    game.delete()
    assert not Edition.objects.filter(pk=second_edition.pk).exists()
    assert not Release.objects.filter(pk=second_release.pk).exists()


def test_legacy_game_form_remains_authoritative_and_creates_no_graph(
    owned_library,
):
    platform = Platform.objects.create(name="Legacy Platform")
    form = GameForm(
        data={
            "name": "Legacy Game",
            "sort_name": "Legacy Game",
            "platform": str(platform.pk),
            "year_released": "2001",
            "original_year_released": "2000",
            "status": Game.Status.UNPLAYED,
            "wikidata": "",
        },
        library=owned_library,
    )

    assert "original_release_date" not in form.fields
    assert form.is_valid(), form.errors.as_json()
    game = form.save()
    assert (game.platform_id, game.year_released, game.original_year_released) == (
        platform.pk,
        2001,
        2000,
    )
    assert game.original_release_date is None
    assert not game.editions.exists()
```

Also assert the model metadata directly: `Edition` has no `library` field;
`Release` has no `library` field; Edition's `game` is non-null with
`models.CASCADE`; Release's `edition` is non-null with `models.CASCADE`; and
Release's `platform` is nullable with `models.SET_NULL`:

```python
def test_catalog_hierarchy_ownership_and_delete_metadata_are_explicit():
    assert "library" not in {field.name for field in Edition._meta.get_fields()}
    assert "library" not in {field.name for field in Release._meta.get_fields()}

    game_field = Edition._meta.get_field("game")
    edition_field = Release._meta.get_field("edition")
    platform_field = Release._meta.get_field("platform")
    assert game_field.null is False
    assert game_field.remote_field.on_delete is models.CASCADE
    assert edition_field.null is False
    assert edition_field.remote_field.on_delete is models.CASCADE
    assert platform_field.null is True
    assert platform_field.remote_field.on_delete is models.SET_NULL
```

Add `from django.db import models` to the test imports for these assertions.

- [ ] **Step 2: Write failing migration/schema tests.**

Create `tests/test_catalog_hierarchy_migration.py` with a transaction-marked
migration harness modeled on the repository's existing identity migration
tests:

```python
import uuid
from typing import NamedTuple

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_HIERARCHY = ("games", "0017_temporal_value_domain")
WITH_HIERARCHY = ("games", "0018_catalog_hierarchy")


@pytest.fixture
def hierarchy_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_HIERARCHY])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_HIERARCHY]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_hierarchy():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_HIERARCHY])
    return executor.loader.project_state([WITH_HIERARCHY]).apps


def seed_legacy_game(apps):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Platform = apps.get_model("games", "Platform")
    Game = apps.get_model("games", "Game")
    user = User.objects.create(username="catalog-hierarchy")
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    platform = Platform.objects.create(name="Legacy Platform")
    game_id = uuid.uuid7()
    Game.objects.create(
        id=game_id,
        library_id=library.pk,
        name="Legacy Game",
        sort_name="Legacy Sort",
        platform_id=platform.pk,
        year_released=2001,
        original_year_released=2000,
        wikidata="Q123",
        status="p",
        mastered=True,
    )
    return game_id, platform.pk


class ColumnMetadata(NamedTuple):
    domain_name: str | None
    is_generated: str
    is_nullable: str


def column_metadata(table_name: str, column_name: str) -> ColumnMetadata:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT domain_name, is_generated, is_nullable
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    assert row is not None, f"{table_name}.{column_name} does not exist"
    return ColumnMetadata(*row)


def foreign_key_targets(table_name: str) -> dict[str, tuple[str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT key_usage.column_name, ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints AS constraint_row
            JOIN information_schema.key_column_usage AS key_usage
                ON key_usage.constraint_name = constraint_row.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = constraint_row.constraint_name
            WHERE constraint_row.table_name = %s
                AND constraint_row.constraint_type = 'FOREIGN KEY'
            """,
            [table_name],
        )
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
```

Add helpers that query `information_schema.columns` for `domain_name`,
`is_generated`, and `is_nullable`, and the same `foreign_key_targets()` query
used in `tests/test_catalog_uuid_primary_key.py`. Then add these tests:

```python
def test_forward_migration_is_additive_and_does_not_backfill(hierarchy_harness):
    game_id, platform_id = seed_legacy_game(hierarchy_harness)
    apps = migrate_to_hierarchy()
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")

    game = Game.objects.get(pk=game_id)
    assert (
        game.pk,
        game.sort_name,
        game.platform_id,
        game.year_released,
        game.original_year_released,
        game.wikidata,
        game.status,
        game.mastered,
    ) == (game_id, "Legacy Sort", platform_id, 2001, 2000, "Q123", "p", True)
    assert game.original_release_date is None
    assert game.original_release_date_kind == "unknown"
    assert Edition.objects.count() == 0
    assert Release.objects.count() == 0


def test_hierarchy_schema_uses_uuidv7_temporal_and_generated_columns(
    hierarchy_harness,
):
    migrate_to_hierarchy()
    assert column_metadata("games_edition", "id").domain_name == "uuid_v7"
    assert column_metadata("games_release", "id").domain_name == "uuid_v7"
    assert column_metadata("games_game", "original_release_date").domain_name == "temporal_value"
    assert column_metadata("games_release", "release_date").domain_name == "temporal_value"
    for table, prefix in (
        ("games_game", "original_release_date"),
        ("games_release", "release_date"),
    ):
        for suffix in (
            "lower",
            "upper",
            "kind",
            "precision",
            "start_kind",
            "end_kind",
            "start_precision",
            "end_precision",
        ):
            assert column_metadata(table, f"{prefix}_{suffix}").is_generated == "ALWAYS"
    assert foreign_key_targets("games_edition")["game_id"] == ("games_game", "id")
    assert foreign_key_targets("games_release")["edition_id"] == ("games_edition", "id")
    assert foreign_key_targets("games_release")["platform_id"] == ("games_platform", "id")
    assert column_metadata("games_edition", "game_id").is_nullable == "NO"
    assert column_metadata("games_release", "edition_id").is_nullable == "NO"
    assert column_metadata("games_release", "platform_id").is_nullable == "YES"


def test_reverse_migration_preserves_the_legacy_game(hierarchy_harness):
    game_id, platform_id = seed_legacy_game(hierarchy_harness)
    migrate_to_hierarchy()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_HIERARCHY])
    apps = executor.loader.project_state([BEFORE_HIERARCHY]).apps
    Game = apps.get_model("games", "Game")
    game = Game.objects.get(pk=game_id)

    assert game.platform_id == platform_id
    assert game.year_released == 2001
    assert game.original_year_released == 2000
    assert "original_release_date" not in {
        field.name for field in Game._meta.get_fields()
    }
```

Do not assert PostgreSQL `ON DELETE` clauses: Django owns these `on_delete`
semantics in its collector, and Step 1 exercises the actual model behavior.

- [ ] **Step 3: Run both files and verify the expected red state.**

Run each file independently so both missing-contract failures are observed:

```bash
make test ARGS="tests/test_catalog_hierarchy.py -q"
make test ARGS="tests/test_catalog_hierarchy_migration.py -q"
```

Expected: the current-model file fails collection because `Edition` and
`Release` do not exist; the migration file fails because the migration graph
has no `0018_catalog_hierarchy` node. Keep the Makefile's default worker count.

- [ ] **Step 4: Add the exact model declarations.**

In `games/models.py`, import these names from `timetracker.temporal`:

```python
from timetracker.temporal import (
    TemporalEndKind,
    TemporalEndPrecision,
    TemporalKind,
    TemporalLowerBound,
    TemporalPrecisionValue,
    TemporalStartKind,
    TemporalStartPrecision,
    TemporalUpperBound,
    TemporalValueField,
)
```

Add this explicit block to `Game` next to the two legacy year fields:

```python
    original_release_date = TemporalValueField()
    original_release_date_lower = models.GeneratedField(
        expression=TemporalLowerBound("original_release_date"),
        output_field=models.DateField(null=True),
        db_persist=True,
        editable=False,
    )
    original_release_date_upper = models.GeneratedField(
        expression=TemporalUpperBound("original_release_date"),
        output_field=models.DateField(null=True),
        db_persist=True,
        editable=False,
    )
    original_release_date_kind = models.GeneratedField(
        expression=TemporalKind("original_release_date"),
        output_field=models.CharField(max_length=7),
        db_persist=True,
        editable=False,
    )
    original_release_date_precision = models.GeneratedField(
        expression=TemporalPrecisionValue("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
    original_release_date_start_kind = models.GeneratedField(
        expression=TemporalStartKind("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
    original_release_date_end_kind = models.GeneratedField(
        expression=TemporalEndKind("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
    original_release_date_start_precision = models.GeneratedField(
        expression=TemporalStartPrecision("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
    original_release_date_end_precision = models.GeneratedField(
        expression=TemporalEndPrecision("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
```

Place `Edition` and `Release` after `Platform`, so the direct Platform class is
available. Add exactly these identity and relation fields, followed by the
explicit Release temporal projections:

```python
class Edition(models.Model):
    id = UUIDv7Field(primary_key=True, editable=False)
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="editions",
    )


class Release(models.Model):
    id = UUIDv7Field(primary_key=True, editable=False)
    edition = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="releases",
    )
    platform = models.ForeignKey(
        Platform,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="releases",
    )
    release_date = TemporalValueField()
    release_date_lower = models.GeneratedField(
        expression=TemporalLowerBound("release_date"),
        output_field=models.DateField(null=True),
        db_persist=True,
        editable=False,
    )
    release_date_upper = models.GeneratedField(
        expression=TemporalUpperBound("release_date"),
        output_field=models.DateField(null=True),
        db_persist=True,
        editable=False,
    )
    release_date_kind = models.GeneratedField(
        expression=TemporalKind("release_date"),
        output_field=models.CharField(max_length=7),
        db_persist=True,
        editable=False,
    )
    release_date_precision = models.GeneratedField(
        expression=TemporalPrecisionValue("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
    release_date_start_kind = models.GeneratedField(
        expression=TemporalStartKind("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
    release_date_end_kind = models.GeneratedField(
        expression=TemporalEndKind("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
    release_date_start_precision = models.GeneratedField(
        expression=TemporalStartPrecision("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
    release_date_end_precision = models.GeneratedField(
        expression=TemporalEndPrecision("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        db_persist=True,
        editable=False,
    )
```

Do not add `__str__`, managers, validation, names, timestamps, default flags,
unique constraints, signals, services, forms, APIs, or admin registrations.

- [ ] **Step 5: Generate and inspect the additive migration.**

Run:

```bash
make makemigrations
```

Rename the generated `0018_*.py` to `0018_catalog_hierarchy.py` if Django does
not naturally emit that exact name. Inspect the file and require all of these
facts:

- dependency is exactly `("games", "0017_temporal_value_domain")`;
- operations only create Edition/Release and add the nine Game fields;
- Edition and Release IDs deconstruct as `UUIDv7Field` primary keys;
- all generated expressions use the semantic field prefix they project;
- all three foreign keys point at the approved models and carry the approved
  `on_delete` behavior; and
- there is no `RunPython`, data loop, backfill, legacy-field alteration, index,
  constraint, or unrelated model change.

- [ ] **Step 6: Run focused tests and repair only contract failures.**

Run:

```bash
make test ARGS="tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py -q"
```

Expected: both files pass with the Makefile's default parallel workers. If the
migration test exposes a mismatch between model state and physical PostgreSQL
schema, correct the declaration/migration rather than weakening the assertion.

- [ ] **Step 7: Prove there is no migration drift.**

Run:

```bash
make check-migrations
```

Expected: `No changes detected` and exit status 0.

- [ ] **Step 8: Commit the implementation slice.**

```bash
git add games/models.py games/migrations/0018_catalog_hierarchy.py tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py
git commit -m "feat: introduce catalog hierarchy identities"
```

---

### Task 2: Verify the approved boundary and deliver the pull request

**Files:**
- Verify: all issue implementation and test files.
- Remove after verification: `docs/superpowers/specs/2026-08-20-issue-649-catalog-identities-design.md`
- Remove after verification: `docs/superpowers/plans/2026-08-20-issue-649-catalog-identities.md`
- Create temporarily outside the repository: `/tmp/issue-649-pr-body.md`

**Interfaces:**
- Consumes: Task 1's passing catalog hierarchy.
- Produces: a clean issue-only branch and a GitHub PR targeting `codex/catalog-wave`.

- [ ] **Step 1: Re-run the focused gate with default workers.**

```bash
make test ARGS="tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py -q"
```

Record the final exit status and worker count from the Make/pytest output.

- [ ] **Step 2: Run the authoritative full gate with default workers.**

```bash
make check
```

Expected: exit status 0. Do not pass `PYTEST_WORKERS=0` or any other override.
If an unrelated failure occurs, report it instead of expanding #649; if an
in-scope regression occurs, fix it under the same TDD cycle and rerun the full
gate.

- [ ] **Step 3: Check migration and diff integrity.**

```bash
make check-migrations
git diff --check origin/codex/catalog-wave...HEAD
git diff --stat origin/codex/catalog-wave...HEAD
git diff origin/codex/catalog-wave...HEAD
```

Require no drift or whitespace errors. Review every changed line against the
specification. Confirm there are no changes to current forms, views, URLs,
filters, APIs, statistics, templates, TypeScript, CSS, legacy fields, or data.

- [ ] **Step 4: Reconcile actual complexity with the planning gate.**

Count implementation/test files and non-generated added/deleted lines. Record
forecast versus actual in the PR body. Stop for a new design approval if the
branch reaches three independent runtime subsystems, more than 40 files, or
more than 2,000 non-generated changed lines.

- [ ] **Step 5: Remove transient planning artifacts after all evidence is green.**

Delete only the two issue-specific planning files listed above. Preserve the
catalog-wave design and all other documentation. Then run:

```bash
git diff --check
git status --short
```

- [ ] **Step 6: Commit the planning cleanup.**

```bash
git add docs/superpowers/specs/2026-08-20-issue-649-catalog-identities-design.md docs/superpowers/plans/2026-08-20-issue-649-catalog-identities.md
git commit -m "chore: remove catalog identity planning artifacts"
```

- [ ] **Step 7: Push the issue branch.**

```bash
git push -u origin codex/issue-649-catalog-identities
```

- [ ] **Step 8: Open the PR against the catalog integration branch.**

Write `/tmp/issue-649-pr-body.md` only after the commands above have produced
their final evidence. Use the exact observed commands, result counts, worker
count, and scope totals in the Verification bullets; do not use approximate or
prospective values. The static portion of the body is:

```markdown
Closes #649

## Summary

- add passive UUIDv7 Edition and Release identities beneath the existing Game UUID
- add #655 temporal storage for Game original release and Release availability
- preserve all legacy reads, writes, fields, and rows without backfill

## Verification

- focused hierarchy tests pass with the Makefile's default workers
- `make check` passes with the Makefile's default workers
- `make check-migrations` reports no model/migration drift
- actual scope is reported against the forecast of four implementation/test files and 500–850 non-generated changed lines
```

Expand each Verification bullet with its recorded numeric output before calling
`gh pr create`; the body must not claim a worker count or test total that was
not present in the final logs.

Then run:

```bash
gh pr create --repo KucharczykL/timetracker --base codex/catalog-wave --head codex/issue-649-catalog-identities --title "CAT-01: Introduce Game, Edition, and Release catalog identities" --body-file /tmp/issue-649-pr-body.md
```

Read the created PR back and confirm its base is `codex/catalog-wave`, its head
is the issue branch, it links #649, and the verification evidence is exact.

## Plan self-review

- **Specification coverage:** additive identities and cardinality are Task 1
  Steps 1/4/5; UUIDv7 is Steps 1/4/5; temporal year/unknown preservation is
  Steps 1/4; explicit relation/delete behavior is Steps 1/4/5; additive fresh
  PostgreSQL migration and reverse safety are Steps 2/5/6; unchanged current
  behavior is Step 1 plus Task 2's full gate; default-worker verification and
  PR delivery are Task 2.
- **Boundary coverage:** no backfill or graph writer appears in an implementation
  step; no surface outside models/migration/focused tests is modified; planning
  cleanup occurs only after green evidence.
- **Type consistency:** both temporal prefixes expose the same nine #655 field
  types; Edition/Game and Release/Edition are non-null; Release/Platform is
  nullable; every identity is UUIDv7.
- **Completeness scan:** every implementation step names exact fields,
  relations, tests, commands, and expected outcomes. Future PR evidence is
  required to come from the recorded final command output rather than being
  predicted in the plan.
