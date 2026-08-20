# CAT-01 Catalog Identities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add passive Game, Edition, and Release catalog identities and temporal release-date storage without changing current reads, writes, or legacy data.

**Architecture:** Extend `Game` with #655's explicit temporal consumer columns, add a UUIDv7 `Edition` child of Game, and add a UUIDv7 `Release` child of Edition with an optional Platform and the same temporal consumer shape. Ship one additive schema migration with no explicit data migration, prevent the new schema from expanding metadata-derived filter and fixture surfaces, and prove identity, cardinality, temporal precision, delete behavior, passivity, fresh-schema shape, and reversibility.

**Tech Stack:** Python 3.14, Django ORM/migrations, PostgreSQL 17, pytest-django, pytest-xdist, Make.

**Spec:** `docs/superpowers/specs/2026-08-20-issue-649-catalog-identities-design.md`

## Global Constraints

- Treat issue #649, the overhaul charter, the catalog wave specification, and #655's temporal-value contract as authoritative.
- Preserve `Game.id` exactly; do not alter or regenerate existing Game UUIDs.
- Keep every legacy Game field and every current user-visible read/write surface unchanged.
- Add no logical backfill, catalog writer, adapter, UI, API, filter feature, statistic, PlayerGame, matching, IGDB, product relation, merge, tombstone, redirect, or external-reference behavior.
- `Edition` and `Release` use `UUIDv7Field` primary keys; Edition belongs to Game, Release belongs to Edition, and Release Platform is optional and explicit.
- Declare all nine columns for each temporal fact explicitly; do not hide them behind a dynamic model-field injector.
- Set `serialize=False` on all generated projections; canonical temporal scalars remain fixture-serializable.
- Set wrapper-level `null=True` on all seven nullable projections and make generated `kind` physically and logically non-null.
- Suppress the Platform reverse accessor and exclude temporal generated expressions from the existing comparison registry so current filter choices do not change.
- Defer default-graph selection to #888; this slice does not imply that one of multiple UUID children is the default.
- Use `make test` and `make check` with the Makefile's default `PYTEST_WORKERS`; never set normal verification to serial mode.
- Stop and re-slice before approval if actual scope crosses three independent runtime subsystems, 40 files, or 2,000 non-generated changed lines.

## File structure

- Modify `games/models.py`: define Game original-release temporal fields and the Edition/Release models.
- Modify `common/criteria.py`: exclude #655 generated projections from metadata-derived comparison choices.
- Create `games/migrations/0018_catalog_hierarchy.py`: additive schema only, depending on `0017_temporal_value_domain`.
- Create `tests/test_catalog_hierarchy.py`: current-model identity, cardinality, dates, serialization, filter compatibility, delete behavior, and legacy-write passivity.
- Create `tests/test_catalog_hierarchy_migration.py`: forward/reverse migration and PostgreSQL schema contract.
- Modify `tests/test_uuid_identity_audit.py`: include the new UUIDv7 tables with no integer ordering source.
- Remove this plan and its paired issue design only after implementation and verification are complete; preserve the planning and review commits in the pushed PR range/review record, noting that a squash merge need not retain them in target-branch history.

## Planning gate checkpoint

Before runtime implementation, commit the adversarially reviewed versions of
this plan and its paired design:

```bash
git add docs/superpowers/specs/2026-08-20-issue-649-catalog-identities-design.md docs/superpowers/plans/2026-08-20-issue-649-catalog-identities.md
git commit -m "docs: harden catalog identity plan after review"
```

Then stop for explicit user approval. No Task 1 step may start before that
approval.

---

### Task 1: Add the passive catalog hierarchy and its schema contract

**Files:**
- Modify: `games/models.py`
- Modify: `common/criteria.py`
- Create: `games/migrations/0018_catalog_hierarchy.py`
- Create: `tests/test_catalog_hierarchy.py`
- Create: `tests/test_catalog_hierarchy_migration.py`
- Modify: `tests/test_uuid_identity_audit.py`

**Interfaces:**
- Consumes: `UUIDv7Field` from `timetracker.uuidv7` and the nine #655 field/expression types from `timetracker.temporal`.
- Produces: `Game.original_release_date` plus its eight generated projections.
- Produces: `Edition(id: UUIDv7, game: Game)` with reverse accessor `Game.editions` and Django cascade deletion.
- Produces: `Release(id: UUIDv7, edition: Edition, platform: Platform | None, release_date: TemporalValue | None)` with reverse accessor `Edition.releases`, no Platform reverse accessor, Edition cascade deletion, and Platform `SET_NULL` deletion.
- Produces: `Release.release_date` plus its eight generated projections.
- Produces: migration node `("games", "0018_catalog_hierarchy")`, with no explicit data operation and final non-null `kind` projections.
- Preserves: the existing comparison-field vocabulary and fixture loadability.

- [ ] **Step 1: Write failing current-model tests.**

Create `tests/test_catalog_hierarchy.py`. Import `Edition`, `Game`, `Platform`,
and `Release` from `games.models`, `GameForm` from `games.forms`, and
`TemporalValue` from `timetracker.temporal`. Add these exact behavioral cases:

```python
import json
import uuid
from datetime import date

import pytest
from django.core import serializers
from django.db import models

from common.criteria import FilterError, _comparison_group_for, comparable_columns
from games.forms import GameForm
from games.models import (
    Edition,
    Game,
    Platform,
    PlayEvent,
    Purchase,
    Release,
    Session,
)
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


def test_game_and_release_temporal_values_preserve_ranges_and_unknown(
    owned_library,
):
    game = Game.objects.create(
        library=owned_library,
        name="Year Game",
        original_release_date=TemporalValue.parse("1987/1989-03"),
    )
    edition = Edition.objects.create(game=game)
    known = Release.objects.create(
        edition=edition,
        release_date=TemporalValue.parse("1998-04/2000"),
    )
    unknown = Release.objects.create(edition=edition, release_date=None)

    game.refresh_from_db()
    known.refresh_from_db()
    unknown.refresh_from_db()

    assert game.original_release_date == TemporalValue.parse("1987/1989-03")
    assert (
        game.original_release_date_lower,
        game.original_release_date_upper,
        game.original_release_date_kind,
        game.original_release_date_precision,
        game.original_release_date_start_kind,
        game.original_release_date_end_kind,
        game.original_release_date_start_precision,
        game.original_release_date_end_precision,
    ) == (
        date(1987, 1, 1),
        date(1989, 3, 31),
        "range",
        None,
        "known",
        "known",
        "year",
        "month",
    )
    assert known.release_date == TemporalValue.parse("1998-04/2000")
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
        date(1998, 4, 1),
        date(2000, 12, 31),
        "range",
        None,
        "known",
        "known",
        "month",
        "year",
    )
    assert unknown.release_date is None
    assert unknown.release_date_lower is None
    assert unknown.release_date_upper is None
    assert unknown.release_date_kind == "unknown"
    assert unknown.release_date_precision is None
    assert unknown.release_date_start_kind is None
    assert unknown.release_date_end_kind is None
    assert unknown.release_date_start_precision is None
    assert unknown.release_date_end_precision is None


def test_game_and_release_preserve_year_precision(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Year Game",
        original_release_date=TemporalValue.from_year(1987),
    )
    release = Release.objects.create(
        edition=Edition.objects.create(game=game),
        release_date=TemporalValue.from_year(1998),
    )
    game.refresh_from_db()
    release.refresh_from_db()

    assert (
        game.original_release_date_lower,
        game.original_release_date_upper,
        game.original_release_date_kind,
        game.original_release_date_precision,
    ) == (date(1987, 1, 1), date(1987, 12, 31), "atomic", "year")
    assert (
        release.release_date_lower,
        release.release_date_upper,
        release.release_date_kind,
        release.release_date_precision,
    ) == (date(1998, 1, 1), date(1998, 12, 31), "atomic", "year")


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
    second_edition_id = second_edition.pk
    second_release_id = second_release.pk
    game.delete()
    assert not Edition.objects.filter(pk=second_edition_id).exists()
    assert not Release.objects.filter(pk=second_release_id).exists()


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
    assert platform_field.remote_field.related_name == "+"
```

Add serialization and metadata-registry compatibility tests. The canonical
field is additive fixture state, but no generated projection may be serialized;
no comparison choice reachable from current models may mention either new
temporal prefix, and a crafted projection operand must be rejected:

```python
def test_generated_temporal_projections_are_not_fixture_serialized(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Serialized Game",
        original_release_date=TemporalValue.from_year(1998),
    )
    release = Release.objects.create(
        edition=Edition.objects.create(game=game),
        release_date=TemporalValue.from_year(1999),
    )
    game_payload, release_payload = [
        row["fields"]
        for row in json.loads(serializers.serialize("json", [game, release]))
    ]

    assert game_payload["original_release_date"] == "1998"
    assert not any(
        name.startswith("original_release_date_") for name in game_payload
    )
    assert release_payload["release_date"] == "1999"
    assert not any(name.startswith("release_date_") for name in release_payload)


@pytest.mark.parametrize("model", [Game, Session, Purchase, PlayEvent, Platform])
def test_temporal_schema_does_not_expand_comparison_choices(model):
    values = {column["value"] for column in comparable_columns(model)}
    assert not any(
        "original_release_date" in value or "release_date" in value
        for value in values
    )

    with pytest.raises(FilterError):
        _comparison_group_for(Game, "original_release_date_lower")
```

Also assert `Platform._meta` exposes no auto-created relation whose
`related_model` is `Release`. The tests deliberately cover both direct Game
columns and Game columns reached through current Session/Purchase/PlayEvent
relations.

Modify `tests/test_uuid_identity_audit.py` as part of the red phase. Add
`"games_edition"` and `"games_release"` to
`EXPECTED_IDENTITY_TABLES`, then extend the ordering-source test:

```python
    assert sources["games_edition"] is None
    assert sources["games_release"] is None
```

This pins automatic audit discovery without changing the audit runtime and is
expected to fail until the models and migration exist.

Also add these automatically discovered UUID relation columns to
`EXPECTED_RELATION_COLUMNS`:

```python
    ("games_edition", "game_id"),
    ("games_release", "edition_id"),
    ("games_release", "platform_id"),
```

The existing type-agreement test then proves all three relations use the same
`uuid_v7` domain as their targets.

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
    generation_expression: str | None


def column_metadata(table_name: str, column_name: str) -> ColumnMetadata:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT domain_name, is_generated, is_nullable, generation_expression
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
        expected_functions = {
            "lower": "timetracker_temporal_lower",
            "upper": "timetracker_temporal_upper",
            "kind": "timetracker_temporal_kind",
            "precision": "timetracker_temporal_precision",
            "start_kind": "timetracker_temporal_start_kind",
            "end_kind": "timetracker_temporal_end_kind",
            "start_precision": "timetracker_temporal_start_precision",
            "end_precision": "timetracker_temporal_end_precision",
        }
        for suffix, function_name in expected_functions.items():
            metadata = column_metadata(table, f"{prefix}_{suffix}")
            assert metadata.is_generated == "ALWAYS"
            generation_expression = metadata.generation_expression
            assert generation_expression is not None
            assert function_name in generation_expression
            assert metadata.is_nullable == ("NO" if suffix == "kind" else "YES")
    assert foreign_key_targets("games_edition")["game_id"] == ("games_game", "id")
    assert foreign_key_targets("games_release")["edition_id"] == ("games_edition", "id")
    assert foreign_key_targets("games_release")["platform_id"] == ("games_platform", "id")
    assert column_metadata("games_edition", "game_id").is_nullable == "NO"
    assert column_metadata("games_release", "edition_id").is_nullable == "NO"
    assert column_metadata("games_release", "platform_id").is_nullable == "YES"


def test_database_defaults_generate_uuidv7_for_raw_hierarchy_inserts(
    hierarchy_harness,
):
    game_id, _ = seed_legacy_game(hierarchy_harness)
    migrate_to_hierarchy()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO games_edition (game_id) VALUES (%s) RETURNING id",
            [game_id],
        )
        edition_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO games_release (edition_id, release_date) "
            "VALUES (%s, NULL) RETURNING id",
            [edition_id],
        )
        release_id = cursor.fetchone()[0]

    assert edition_id.version == 7
    assert release_id.version == 7


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
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('games_edition'), to_regclass('games_release')"
        )
        assert cursor.fetchone() == (None, None)
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'games_game' "
            "AND column_name LIKE 'original_release_date%'"
        )
        assert cursor.fetchall() == []
        cursor.execute(
            "SELECT typname FROM pg_type "
            "WHERE typname IN ('uuid_v7', 'temporal_value')"
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "uuid_v7",
            "temporal_value",
        }
```

Do not assert PostgreSQL `ON DELETE` clauses: Django owns these `on_delete`
semantics in its collector, and Step 1 exercises the actual model behavior.

- [ ] **Step 3: Run the focused files and verify the expected red state.**

Run each file independently so all missing-contract failures are observed:

```bash
make test ARGS="tests/test_catalog_hierarchy.py -q"
make test ARGS="tests/test_catalog_hierarchy_migration.py -q"
make test ARGS="tests/test_uuid_identity_audit.py -q"
```

Expected: the current-model file fails collection because `Edition` and
`Release` do not exist; the migration file fails because the migration graph
has no `0018_catalog_hierarchy` node; the identity audit fails because the two
expected UUID carriers do not yet exist. Keep the Makefile's default worker
count.

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
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_upper = models.GeneratedField(
        expression=TemporalUpperBound("original_release_date"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_kind = models.GeneratedField(
        expression=TemporalKind("original_release_date"),
        output_field=models.CharField(max_length=7),
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_precision = models.GeneratedField(
        expression=TemporalPrecisionValue("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_start_kind = models.GeneratedField(
        expression=TemporalStartKind("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_end_kind = models.GeneratedField(
        expression=TemporalEndKind("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_start_precision = models.GeneratedField(
        expression=TemporalStartPrecision("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_end_precision = models.GeneratedField(
        expression=TemporalEndPrecision("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
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
        related_name="+",
    )
    release_date = TemporalValueField()
    release_date_lower = models.GeneratedField(
        expression=TemporalLowerBound("release_date"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_upper = models.GeneratedField(
        expression=TemporalUpperBound("release_date"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_kind = models.GeneratedField(
        expression=TemporalKind("release_date"),
        output_field=models.CharField(max_length=7),
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_precision = models.GeneratedField(
        expression=TemporalPrecisionValue("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_start_kind = models.GeneratedField(
        expression=TemporalStartKind("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_end_kind = models.GeneratedField(
        expression=TemporalEndKind("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_start_precision = models.GeneratedField(
        expression=TemporalStartPrecision("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_end_precision = models.GeneratedField(
        expression=TemporalEndPrecision("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
```

In `common/criteria.py`, import the eight projection expression classes and
group them in a private tuple:

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
)

_TEMPORAL_PROJECTION_EXPRESSIONS = (
    TemporalLowerBound,
    TemporalUpperBound,
    TemporalKind,
    TemporalPrecisionValue,
    TemporalStartKind,
    TemporalEndKind,
    TemporalStartPrecision,
    TemporalEndPrecision,
)
```

At the start of `_maybe_group_for()`, after resolving the field and rejecting
relations, make these projections non-comparable:

```python
    if isinstance(model_field, models.GeneratedField) and isinstance(
        model_field.expression, _TEMPORAL_PROJECTION_EXPRESSIONS
    ):
        return None
```

This is expression-type based rather than prefix based, so later #655 consumers
inherit the same exclusion without hiding unrelated generated fields. Do not
alter any existing comparison groups or operator behavior.

Update `_maybe_group_for()` and `comparable_columns()` docstrings so they state
that generated fields with unresolved output types **and** #655 temporal
projection expressions are excluded. Do not leave documentation claiming the
unresolved-output case is the only GeneratedField exclusion.

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
- operations create Edition/Release, add the nine Game fields, and finish with
  exactly two `AlterField` operations for generated-kind nullability;
- Edition and Release IDs deconstruct as `UUIDv7Field` primary keys;
- all generated expressions use the semantic field prefix they project;
- all three foreign keys point at the approved models and carry the approved
  `on_delete` behavior; and
- every generated projection deconstructs with `serialize=False`, and the seven
  nullable projections also carry wrapper-level `null=True`; and
- there is no `RunPython`, data loop, logical backfill, legacy-field alteration,
  index, uniqueness/check constraint, or unrelated model change.

Django's initial PostgreSQL DDL for a stored generated column does not emit a
null clause. Hand-edit the migration so each `kind` projection is first created
with `null=True`, after which the migration has an `AlterField` to the final
`null=False` declaration. Do this for both `Game.original_release_date_kind`
and `Release.release_date_kind`. The final migration state must exactly match
the model; the explicit alter is required to produce physical `NOT NULL`.

Inspect the emitted SQL before testing:

```bash
direnv exec . uv run --frozen python manage.py sqlmigrate games 0018
```

Confirm the SQL consumes but does not recreate the existing domains, adds
stored generated expressions using the intended source columns, and emits
`SET NOT NULL` for both kind columns. Record whether the nine additions to
populated `games_game` are separate table-altering statements for the
production-copy rehearsal handoff.

- [ ] **Step 6: Run focused tests and repair only contract failures.**

Run:

```bash
make test ARGS="tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py tests/test_uuid_identity_audit.py -q"
```

Expected: all three files pass with the Makefile's default parallel workers. If the
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
git add common/criteria.py games/models.py games/migrations/0018_catalog_hierarchy.py tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py tests/test_uuid_identity_audit.py
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
make test ARGS="tests/test_catalog_hierarchy.py tests/test_catalog_hierarchy_migration.py tests/test_uuid_identity_audit.py -q"
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
direnv exec . uv run --frozen python manage.py sqlmigrate games 0018
git diff --check origin/codex/catalog-wave...HEAD
git diff --stat origin/codex/catalog-wave...HEAD
git diff origin/codex/catalog-wave...HEAD
```

Require no drift or whitespace errors. Reconfirm the SQL evidence recorded in
Task 1, including both `SET NOT NULL` statements and the populated-Game
lock/rewrite rehearsal handoff. Review every changed line against the
specification. Confirm there are no changes to current forms, views, URLs,
filter vocabulary, APIs, statistics, templates, TypeScript, CSS, legacy fields,
or canonical data. The only filter-runtime diff must be the projection
exclusion required to preserve that vocabulary.

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
- `sqlmigrate games 0018` confirms generated expressions and physical kind nullability
- actual scope is reported against the forecast of six implementation/test files and 700–1,100 non-generated changed lines
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
  Steps 1/4/5; Python and database UUIDv7 defaults are Steps 1/2/4/5; temporal
  range/year/unknown preservation and serialization are Steps 1/4; explicit
  relation/delete behavior is Steps 1/4/5; physical nullability, additive fresh
  PostgreSQL migration, SQL inspection, and reverse safety are Steps 2/5/6;
  unchanged current filter and write behavior is Step 1 plus Task 2's full gate;
  default-worker verification and PR delivery are Task 2.
- **Boundary coverage:** no backfill or graph writer appears in an implementation
  step; the only runtime compatibility edit outside models/migration is the
  expression-type exclusion in `common.criteria`; planning cleanup occurs only
  after green evidence, with its commits retained in the pushed PR range.
- **Type consistency:** both temporal prefixes expose the same nine #655 field
  types; Edition/Game and Release/Edition are non-null; Release/Platform is
  nullable; nullable projections agree in Django state and PostgreSQL; kind is
  non-null in both; every identity is UUIDv7.
- **Adversarial-review closure:** default selection is explicitly handed to
  #888; fixture projections cannot be dumped; physical reverse checks and raw
  database defaults are tested; range cases distinguish every endpoint
  projection; and SQL inspection makes generated-column rewrite risk visible.
- **Completeness scan:** every implementation step names exact fields,
  relations, tests, commands, and expected outcomes. Future PR evidence is
  required to come from the recorded final command output rather than being
  predicted in the plan.
