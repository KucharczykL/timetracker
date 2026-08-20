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
BEFORE_CATALOG_WRITES = WITH_HIERARCHY
WITH_CATALOG_WRITES = ("games", "0019_catalog_write_defaults")


@pytest.fixture
def hierarchy_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_HIERARCHY])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_HIERARCHY]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.fixture
def catalog_write_migration_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CATALOG_WRITES])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_CATALOG_WRITES]).apps
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
    assert (
        column_metadata("games_game", "original_release_date").domain_name
        == "temporal_value"
    )
    assert (
        column_metadata("games_release", "release_date").domain_name == "temporal_value"
    )
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
    assert foreign_key_targets("games_edition")["game_id"] == (
        "games_game",
        "id",
    )
    assert foreign_key_targets("games_release")["edition_id"] == (
        "games_edition",
        "id",
    )
    assert foreign_key_targets("games_release")["platform_id"] == (
        "games_platform",
        "id",
    )
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
        edition_row = cursor.fetchone()
        assert edition_row is not None
        edition_id = edition_row[0]
        cursor.execute(
            "INSERT INTO games_release (edition_id, release_date) "
            "VALUES (%s, NULL) RETURNING id",
            [edition_id],
        )
        release_row = cursor.fetchone()
        assert release_row is not None
        release_id = release_row[0]

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
            "SELECT typname FROM pg_type WHERE typname IN ('uuid_v7', 'temporal_value')"
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "uuid_v7",
            "temporal_value",
        }


def test_catalog_write_migration_preserves_children_as_nondefaults(
    catalog_write_migration_harness,
):
    apps = catalog_write_migration_harness
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    user = User.objects.create(username="catalog-writer-migration")
    library = UserLibrary.objects.create(
        user_id=user.pk,
        created_at=timezone.now(),
    )
    game = Game.objects.create(library_id=library.pk, name="Existing")
    edition = Edition.objects.create(game_id=game.pk)
    release = Release.objects.create(edition_id=edition.pk)

    executor = MigrationExecutor(connection)
    executor.migrate([WITH_CATALOG_WRITES])
    new_apps = executor.loader.project_state([WITH_CATALOG_WRITES]).apps
    NewEdition = new_apps.get_model("games", "Edition")
    NewRelease = new_apps.get_model("games", "Release")
    assert NewEdition.objects.get(pk=edition.pk).is_default is False
    assert NewRelease.objects.get(pk=release.pk).is_default is False

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CATALOG_WRITES])
    restored_apps = executor.loader.project_state([BEFORE_CATALOG_WRITES]).apps
    assert (
        restored_apps.get_model("games", "Edition")
        .objects.filter(pk=edition.pk)
        .exists()
    )
    assert (
        restored_apps.get_model("games", "Release")
        .objects.filter(pk=release.pk)
        .exists()
    )
