import json
import uuid
from datetime import timedelta
from importlib import import_module
from typing import NamedTuple

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_HIERARCHY = ("games", "0017_temporal_value_domain")
WITH_HIERARCHY = ("games", "0018_catalog_hierarchy")
BEFORE_CATALOG_WRITES = WITH_HIERARCHY
WITH_CATALOG_WRITES = ("games", "0019_catalog_write_defaults")
BEFORE_CATALOG_BACKFILL = WITH_CATALOG_WRITES
WITH_CATALOG_BACKFILL = ("games", "0020_catalog_hierarchy_backfill")


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


@pytest.fixture
def catalog_backfill_migration_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CATALOG_BACKFILL])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_CATALOG_BACKFILL]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_hierarchy():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_HIERARCHY])
    return executor.loader.project_state([WITH_HIERARCHY]).apps


def migrate_to_catalog_backfill():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_CATALOG_BACKFILL])
    return executor.loader.project_state([WITH_CATALOG_BACKFILL]).apps


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


def seed_catalog_backfill_world(apps):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Platform = apps.get_model("games", "Platform")
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    Session = apps.get_model("games", "Session")
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")
    Purchase = apps.get_model("games", "Purchase")

    user_a = User.objects.create(username="catalog-backfill-a")
    user_b = User.objects.create(username="catalog-backfill-b")
    library_a = UserLibrary.objects.create(
        user_id=user_a.pk,
        created_at=timezone.now(),
    )
    library_b = UserLibrary.objects.create(
        user_id=user_b.pk,
        created_at=timezone.now(),
    )
    shared_platform = Platform.objects.create(name="Shared Platform")
    private_platform = Platform.objects.create(
        library_id=library_a.pk,
        name="Private Platform",
    )

    known_id = uuid.uuid7()
    known = Game.objects.create(
        id=known_id,
        library_id=library_a.pk,
        name="Same Name",
        sort_name="Name, Same A",
        platform_id=shared_platform.pk,
        year_released=2001,
        original_year_released=2000,
        wikidata="Q100",
        status="p",
        mastered=True,
        playtime=timedelta(hours=12, minutes=30),
    )
    prewritten_id = uuid.uuid7()
    prewritten = Game.objects.create(
        id=prewritten_id,
        library_id=library_b.pk,
        name="Same Name",
        sort_name="Name, Same B",
        platform_id=None,
        year_released=2001,
        original_year_released=None,
        wikidata="Q200",
        status="u",
        mastered=False,
        playtime=timedelta(hours=3),
        original_release_date="1980",
    )
    prewritten_edition = Edition.objects.create(
        game_id=prewritten.pk,
        is_default=True,
    )
    prewritten_release = Release.objects.create(
        edition_id=prewritten_edition.pk,
        is_default=True,
        platform_id=shared_platform.pk,
        release_date="1981",
    )
    children_id = uuid.uuid7()
    children = Game.objects.create(
        id=children_id,
        library_id=library_a.pk,
        name="Existing children",
        sort_name="children existing",
        platform_id=private_platform.pk,
        year_released=None,
        original_year_released=None,
        wikidata="",
        status="f",
        mastered=True,
        playtime=timedelta(hours=50),
    )
    nondefault_edition = Edition.objects.create(game_id=children.pk)
    nondefault_release = Release.objects.create(
        edition_id=nondefault_edition.pk,
        platform_id=shared_platform.pk,
        release_date="1990",
    )
    session = Session.objects.create(
        game_id=known.pk,
        timestamp_start=timezone.now(),
    )
    play_event = PlayEvent.objects.create(
        game_id=known.pk,
        started=timezone.now().date(),
    )
    status_change = GameStatusChange.objects.create(
        game_id=known.pk,
        old_status="u",
        new_status="p",
        timestamp=timezone.now(),
    )
    purchase = Purchase.objects.create(
        library_id=library_a.pk,
        date_purchased=timezone.now().date(),
        price_currency="USD",
        related_game_id=known.pk,
    )
    purchase.games.add(children)

    preserved_fields = (
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
    preserved_games = {
        game.pk: tuple(getattr(game, field) for field in preserved_fields)
        for game in (known, prewritten, children)
    }
    return {
        "game_ids": (known_id, prewritten_id, children_id),
        "known_game_id": known_id,
        "prewritten_game_id": prewritten_id,
        "children_game_id": children_id,
        "shared_platform_id": shared_platform.pk,
        "private_platform_id": private_platform.pk,
        "prewritten_default_ids": (
            prewritten_edition.pk,
            prewritten_release.pk,
        ),
        "nondefault_edition_id": nondefault_edition.pk,
        "nondefault_release_id": nondefault_release.pk,
        "session_id": session.pk,
        "play_event_id": play_event.pk,
        "status_change_id": status_change.pk,
        "purchase_id": purchase.pk,
        "preserved_fields": preserved_fields,
        "preserved_games": preserved_games,
    }


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


def test_catalog_backfill_maps_every_game_without_merging_or_changing_legacy_state(
    catalog_backfill_migration_harness,
    capsys,
):
    seeded = seed_catalog_backfill_world(catalog_backfill_migration_harness)
    apps = migrate_to_catalog_backfill()
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    Session = apps.get_model("games", "Session")
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")
    Purchase = apps.get_model("games", "Purchase")

    assert set(Game.objects.values_list("pk", flat=True)) == set(seeded["game_ids"])
    for game_id, expected in seeded["preserved_games"].items():
        game = Game.objects.get(pk=game_id)
        assert (
            tuple(getattr(game, field) for field in seeded["preserved_fields"])
            == expected
        )

    graph_ids = {}
    for game_id in seeded["game_ids"]:
        edition = Edition.objects.get(game_id=game_id, is_default=True)
        release = Release.objects.get(edition=edition, is_default=True)
        graph_ids[game_id] = (edition.pk, release.pk)

    assert len(set(graph_ids.values())) == 3
    assert graph_ids[seeded["prewritten_game_id"]] == seeded["prewritten_default_ids"]
    assert Edition.objects.filter(is_default=True).count() == 3
    assert Release.objects.filter(is_default=True).count() == 3

    known = Game.objects.get(pk=seeded["known_game_id"])
    known_release = Release.objects.get(
        edition__game_id=known.pk,
        edition__is_default=True,
        is_default=True,
    )
    assert known.original_release_date == TemporalValue.from_year(2000)
    assert known_release.release_date == TemporalValue.from_year(2001)
    assert known_release.platform_id == seeded["shared_platform_id"]

    prewritten = Game.objects.get(pk=seeded["prewritten_game_id"])
    prewritten_release = Release.objects.get(
        edition__game_id=prewritten.pk,
        edition__is_default=True,
        is_default=True,
    )
    assert prewritten.original_release_date is None
    assert prewritten_release.release_date == TemporalValue.from_year(2001)
    assert prewritten_release.platform_id is None

    children = Game.objects.get(pk=seeded["children_game_id"])
    children_release = Release.objects.get(
        edition__game_id=children.pk,
        edition__is_default=True,
        is_default=True,
    )
    assert children.original_release_date is None
    assert children_release.release_date is None
    assert children_release.platform_id == seeded["private_platform_id"]

    nondefault_release = Release.objects.get(pk=seeded["nondefault_release_id"])
    assert nondefault_release.edition_id == seeded["nondefault_edition_id"]
    assert nondefault_release.release_date == TemporalValue.from_year(1990)
    assert nondefault_release.platform_id == seeded["shared_platform_id"]
    assert nondefault_release.is_default is False

    assert (
        Session.objects.get(pk=seeded["session_id"]).game_id == seeded["known_game_id"]
    )
    assert (
        PlayEvent.objects.get(pk=seeded["play_event_id"]).game_id
        == seeded["known_game_id"]
    )
    assert (
        GameStatusChange.objects.get(pk=seeded["status_change_id"]).game_id
        == seeded["known_game_id"]
    )
    purchase = Purchase.objects.get(pk=seeded["purchase_id"])
    assert purchase.related_game_id == seeded["known_game_id"]
    assert set(purchase.games.values_list("pk", flat=True)) == {
        seeded["children_game_id"]
    }

    lines = capsys.readouterr().out.splitlines()
    machine_line = next(
        line
        for line in lines
        if line.startswith("CATALOG_HIERARCHY_RECONCILIATION_JSON=")
    )
    assert json.loads(machine_line.split("=", 1)[1]) == {
        "schema_version": 1,
        "summary": {
            "games": 3,
            "editions": 4,
            "releases": 4,
            "default_editions": 3,
            "default_releases": 3,
            "original_dates_known": 1,
            "original_dates_unknown": 2,
            "release_dates_known": 2,
            "release_dates_unknown": 1,
            "unspecified_platforms": 1,
            "mismatches": 0,
        },
        "mismatches": [],
    }
    assert (
        "CAT hierarchy reconciliation: games=3 editions=4 releases=4 "
        "default_editions=3 default_releases=3 original_dates_known=1 "
        "original_dates_unknown=2 release_dates_known=2 "
        "release_dates_unknown=1 unspecified_platforms=1 mismatches=0"
    ) in lines


def test_catalog_backfill_reports_every_source_mismatch_and_rolls_back(
    catalog_backfill_migration_harness,
    capsys,
):
    apps = catalog_backfill_migration_harness
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Platform = apps.get_model("games", "Platform")
    Game = apps.get_model("games", "Game")
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")

    user_a = User.objects.create(username="catalog-backfill-invalid-a")
    user_b = User.objects.create(username="catalog-backfill-invalid-b")
    library_a = UserLibrary.objects.create(
        user_id=user_a.pk,
        created_at=timezone.now(),
    )
    library_b = UserLibrary.objects.create(
        user_id=user_b.pk,
        created_at=timezone.now(),
    )
    foreign_platform = Platform.objects.create(
        library_id=library_b.pk,
        name="Foreign private Platform",
    )
    game = Game.objects.create(
        library_id=library_a.pk,
        name="Invalid source",
        original_year_released=0,
        year_released=10000,
        platform_id=foreign_platform.pk,
    )

    executor = MigrationExecutor(connection)
    try:
        with pytest.raises(
            RuntimeError,
            match=r"CAT hierarchy reconciliation failed with 3 mismatch\(es\)\.",
        ):
            executor.migrate([WITH_CATALOG_BACKFILL])

        lines = capsys.readouterr().out.splitlines()
        machine_line = next(
            line
            for line in lines
            if line.startswith("CATALOG_HIERARCHY_RECONCILIATION_JSON=")
        )
        payload = json.loads(machine_line.split("=", 1)[1])
        assert [row["code"] for row in payload["mismatches"]] == [
            "invalid_original_year",
            "invalid_release_year",
            "legacy_platform_cross_library",
        ]
        assert payload["summary"] == {
            "games": 1,
            "editions": 0,
            "releases": 0,
            "default_editions": 0,
            "default_releases": 0,
            "original_dates_known": 0,
            "original_dates_unknown": 1,
            "release_dates_known": 0,
            "release_dates_unknown": 0,
            "unspecified_platforms": 0,
            "mismatches": 3,
        }
        assert payload["mismatches"] == [
            {
                "code": "invalid_original_year",
                "game_id": str(game.pk),
                "field": "original_year_released",
                "expected": "1..9999 or null",
                "actual": 0,
            },
            {
                "code": "invalid_release_year",
                "game_id": str(game.pk),
                "field": "year_released",
                "expected": "1..9999 or null",
                "actual": 10000,
            },
            {
                "code": "legacy_platform_cross_library",
                "game_id": str(game.pk),
                "platform_id": str(foreign_platform.pk),
                "game_library_id": str(library_a.pk),
                "platform_library_id": str(library_b.pk),
            },
        ]
        assert (
            "CAT hierarchy mismatch: code=invalid_original_year actual=0 "
            f"expected=1..9999 or null field=original_year_released game_id={game.pk}"
        ) in lines
        assert (
            "CAT hierarchy mismatch: code=invalid_release_year actual=10000 "
            f"expected=1..9999 or null field=year_released game_id={game.pk}"
        ) in lines
        assert (
            "CAT hierarchy mismatch: code=legacy_platform_cross_library "
            f"game_id={game.pk} game_library_id={library_a.pk} "
            f"platform_id={foreign_platform.pk} platform_library_id={library_b.pk}"
        ) in lines

        applied = MigrationRecorder(connection).applied_migrations()
        assert WITH_CATALOG_BACKFILL not in applied
        game.refresh_from_db()
        assert game.original_release_date is None
        assert Edition.objects.count() == 0
        assert Release.objects.count() == 0
    finally:
        Game.objects.filter(pk=game.pk).update(
            original_year_released=2000,
            year_released=2001,
            platform_id=None,
        )


def test_catalog_backfill_empty_database_emits_exact_zero_report(
    catalog_backfill_migration_harness,
    capsys,
):
    capsys.readouterr()
    migrate_to_catalog_backfill()

    lines = capsys.readouterr().out.splitlines()
    machine_line = next(
        line
        for line in lines
        if line.startswith("CATALOG_HIERARCHY_RECONCILIATION_JSON=")
    )
    assert json.loads(machine_line.split("=", 1)[1]) == {
        "schema_version": 1,
        "summary": {
            "games": 0,
            "editions": 0,
            "releases": 0,
            "default_editions": 0,
            "default_releases": 0,
            "original_dates_known": 0,
            "original_dates_unknown": 0,
            "release_dates_known": 0,
            "release_dates_unknown": 0,
            "unspecified_platforms": 0,
            "mismatches": 0,
        },
        "mismatches": [],
    }
    assert (
        "CAT hierarchy reconciliation: games=0 editions=0 releases=0 "
        "default_editions=0 default_releases=0 original_dates_known=0 "
        "original_dates_unknown=0 release_dates_known=0 "
        "release_dates_unknown=0 unspecified_platforms=0 mismatches=0"
    ) in lines


def test_catalog_backfill_forward_function_is_idempotent(
    catalog_backfill_migration_harness,
    capsys,
):
    seed_catalog_backfill_world(catalog_backfill_migration_harness)
    apps = migrate_to_catalog_backfill()
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    before_ids = tuple(
        Release.objects.filter(
            is_default=True,
            edition__is_default=True,
        )
        .order_by("edition__game_id")
        .values_list("edition__game_id", "edition_id", "pk")
    )
    before_counts = (Edition.objects.count(), Release.objects.count())
    capsys.readouterr()

    migration = import_module("games.migrations.0020_catalog_hierarchy_backfill")
    migration.backfill_catalog_hierarchy(apps, None)

    after_ids = tuple(
        Release.objects.filter(
            is_default=True,
            edition__is_default=True,
        )
        .order_by("edition__game_id")
        .values_list("edition__game_id", "edition_id", "pk")
    )
    assert after_ids == before_ids
    assert (Edition.objects.count(), Release.objects.count()) == before_counts
    machine_line = next(
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("CATALOG_HIERARCHY_RECONCILIATION_JSON=")
    )
    payload = json.loads(machine_line.split("=", 1)[1])
    assert payload["summary"]["mismatches"] == 0
    assert payload["mismatches"] == []


def test_catalog_backfill_reverse_is_data_noop_and_forward_remains_idempotent(
    catalog_backfill_migration_harness,
):
    seeded = seed_catalog_backfill_world(catalog_backfill_migration_harness)
    apps = migrate_to_catalog_backfill()
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    before_ids = tuple(
        Release.objects.filter(
            is_default=True,
            edition__is_default=True,
        )
        .order_by("edition__game_id")
        .values_list("edition__game_id", "edition_id", "pk")
    )
    before_counts = (Edition.objects.count(), Release.objects.count())

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CATALOG_BACKFILL])
    reverse_apps = executor.loader.project_state([BEFORE_CATALOG_BACKFILL]).apps
    ReverseEdition = reverse_apps.get_model("games", "Edition")
    ReverseRelease = reverse_apps.get_model("games", "Release")
    assert (
        ReverseEdition.objects.count(),
        ReverseRelease.objects.count(),
    ) == before_counts
    assert set(
        ReverseEdition.objects.filter(is_default=True).values_list("game_id", flat=True)
    ) == set(seeded["game_ids"])

    apps = migrate_to_catalog_backfill()
    Edition = apps.get_model("games", "Edition")
    Release = apps.get_model("games", "Release")
    after_ids = tuple(
        Release.objects.filter(
            is_default=True,
            edition__is_default=True,
        )
        .order_by("edition__game_id")
        .values_list("edition__game_id", "edition_id", "pk")
    )
    assert after_ids == before_ids
    assert (Edition.objects.count(), Release.objects.count()) == before_counts
