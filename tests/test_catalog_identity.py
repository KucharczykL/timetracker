import uuid
from datetime import UTC, datetime

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from games.api import api
from games.forms import GameForm, PlatformForm
from games.models import Game, Platform

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_IDENTITY = ("games", "0004_user_library_ownership_cutover")
WITH_IDENTITY = ("games", "0005_catalog_uuid_identity")


def raw_insert_without_identity(model, **field_values):
    """INSERT a row through raw SQL that omits the `uuid` column entirely,
    so PostgreSQL's own `uuidv7()` column default fills it in - the only
    way to exercise `db_default`, since the ORM always resolves the field's
    Python `default` first and never leaves the column to the database.
    """
    instance = model(**field_values)
    now = timezone.now()
    if getattr(instance, "created_at", "missing") is None:
        instance.created_at = now
    if getattr(instance, "updated_at", "missing") is None:
        instance.updated_at = now
    fields = [
        field
        for field in model._meta.local_concrete_fields
        if not field.primary_key and not field.generated
    ]
    columns = ", ".join(f'"{field.column}"' for field in fields)
    placeholders = ", ".join(["%s"] * len(fields))
    values = [
        field.get_prep_value(getattr(instance, field.attname)) for field in fields
    ]
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{model._meta.db_table}" ({columns}) '
            f'VALUES ({placeholders}) RETURNING "id"',
            values,
        )
        return uuid.UUID(str(cursor.fetchone()[0]))


# --- Field contract ---------------------------------------------------------


def test_game_created_through_the_orm_gets_a_distinct_version_7_identity(
    owned_library,
):
    first = Game.objects.create(library=owned_library, name="First")
    second = Game.objects.create(library=owned_library, name="Second")
    assert first.id.version == 7
    assert second.id.version == 7
    assert first.id != second.id


def test_platform_created_through_the_orm_gets_a_distinct_version_7_identity():
    first = Platform.objects.create(name="First")
    second = Platform.objects.create(name="Second")
    assert first.id.version == 7
    assert second.id.version == 7
    assert first.id != second.id


def test_raw_insert_omitting_the_identity_gets_the_database_default(owned_library):
    game_id = raw_insert_without_identity(Game, library=owned_library, name="Raw Game")
    assert game_id.version == 7
    assert Game.objects.get(pk=game_id).name == "Raw Game"


def test_raw_platform_insert_omitting_the_identity_gets_the_database_default():
    platform_id = raw_insert_without_identity(Platform, name="Raw Platform")
    assert platform_id.version == 7
    assert Platform.objects.get(pk=platform_id).name == "Raw Platform"


def test_database_rejects_a_duplicate_game_identity(owned_library):
    shared = uuid.uuid7()
    Game.objects.create(library=owned_library, name="First", id=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        Game.objects.create(library=owned_library, name="Second", id=shared)


def test_database_rejects_a_duplicate_platform_identity():
    shared = uuid.uuid7()
    Platform.objects.create(name="First", id=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        Platform.objects.create(name="Second", id=shared)


def test_database_rejects_a_non_v7_game_identity(owned_library):
    # Through raw SQL: now that the identity is the primary key, the field's own
    # to_python rejects a non-v7 in Python first, which would leave the uuid_v7
    # domain - the guarantee under test - unexercised.
    game = Game.objects.create(library=owned_library, name="Bad")
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE games_game SET id = %s WHERE id = %s", [uuid.uuid4(), game.pk]
        )


def test_database_rejects_a_non_v7_platform_identity():
    # See the game case above: the domain, not the field, is what this pins.
    platform = Platform.objects.create(name="Bad")
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE games_platform SET id = %s WHERE id = %s",
            [uuid.uuid4(), platform.pk],
        )


# --- Invisibility ------------------------------------------------------------


def test_uuid_is_absent_from_game_form_fields():
    assert "uuid" not in GameForm.base_fields


def test_uuid_is_absent_from_platform_form_fields():
    assert "uuid" not in PlatformForm.base_fields


def test_uuid_is_absent_from_the_generated_openapi_schema():
    schemas = api.get_openapi_schema()["components"]["schemas"]
    game_schema = next(name for name in schemas if name.startswith("GameOut"))
    platform_schema = next(name for name in schemas if name.startswith("PlatformOut"))
    assert "uuid" not in schemas[game_schema].get("properties", {})
    assert "uuid" not in schemas[platform_schema].get("properties", {})


# --- Migration: forward backfill --------------------------------------------


def table_columns(table_name: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def create_game_at(apps, library, *, name: str, created_at: datetime):
    Game = apps.get_model("games", "Game")
    game = Game.objects.create(library_id=library.pk, name=name)
    Game.objects.filter(pk=game.pk).update(created_at=created_at)
    game.refresh_from_db()
    return game


def create_platform_at(apps, *, name: str, created_at: datetime):
    Platform = apps.get_model("games", "Platform")
    platform = Platform.objects.create(name=name)
    Platform.objects.filter(pk=platform.pk).update(created_at=created_at)
    platform.refresh_from_db()
    return platform


@pytest.fixture
def identity_harness():
    # Migrating down to BEFORE_IDENTITY unapplies every later migration too, so
    # the restore target is the graph's leaf nodes rather than WITH_IDENTITY,
    # which would strand this worker's shared database behind head for every
    # later test that reuses it.
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_IDENTITY])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_IDENTITY]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_identity():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_IDENTITY])
    return executor.loader.project_state([WITH_IDENTITY]).apps


def test_forward_migration_backfills_every_row_with_a_distinct_ordered_uuid(
    identity_harness, capsys
):
    apps = identity_harness
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    user = User.objects.create(username="identity-owner")
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())

    tied_ms = datetime(2024, 6, 1, 12, 0, 0, 500_000, tzinfo=UTC)
    later = datetime(2024, 6, 1, 12, 0, 1, 0, tzinfo=UTC)

    # game_late is created first (lowest pk) but stamped with the latest
    # created_at, so order_by("created_at", "pk") must disagree with
    # creation/pk order - the "one row out of primary-key order" case.
    game_late = create_game_at(apps, library, name="Late", created_at=later)
    game_tied_a = create_game_at(apps, library, name="TiedA", created_at=tied_ms)
    game_tied_b = create_game_at(apps, library, name="TiedB", created_at=tied_ms)

    platform_tied_a = create_platform_at(apps, name="TiedA", created_at=tied_ms)
    platform_tied_b = create_platform_at(apps, name="TiedB", created_at=tied_ms)
    platform_late = create_platform_at(apps, name="Late", created_at=later)

    new_apps = migrate_to_identity()
    Game = new_apps.get_model("games", "Game")
    Platform = new_apps.get_model("games", "Platform")

    games = list(Game.objects.order_by("pk"))
    platforms = list(Platform.objects.order_by("pk"))

    assert all(game.uuid is not None for game in games)
    assert all(platform.uuid is not None for platform in platforms)
    assert len({game.uuid for game in games}) == len(games)
    assert len({platform.uuid for platform in platforms}) == len(platforms)
    assert all(game.uuid.version == 7 for game in games)
    assert all(platform.uuid.version == 7 for platform in platforms)

    def floor_ms(moment: datetime) -> int:
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        elapsed = moment - epoch
        return (
            elapsed.days * 86_400_000
            + elapsed.seconds * 1000
            + elapsed.microseconds // 1000
        )

    for game in games:
        assert game.uuid.time == floor_ms(game.created_at)
    for platform in platforms:
        assert platform.uuid.time == floor_ms(platform.created_at)

    assert list(Game.objects.order_by("uuid").values_list("pk", flat=True)) == list(
        Game.objects.order_by("created_at", "pk").values_list("pk", flat=True)
    )
    assert list(Platform.objects.order_by("uuid").values_list("pk", flat=True)) == list(
        Platform.objects.order_by("created_at", "pk").values_list("pk", flat=True)
    )

    expected_game_order = [game_tied_a.pk, game_tied_b.pk, game_late.pk]
    assert (
        list(Game.objects.order_by("uuid").values_list("pk", flat=True))
        == expected_game_order
    )
    expected_platform_order = [platform_tied_a.pk, platform_tied_b.pk, platform_late.pk]
    assert (
        list(Platform.objects.order_by("uuid").values_list("pk", flat=True))
        == expected_platform_order
    )

    output = capsys.readouterr().out
    assert "CAT identity backfilled" in output
    assert "game_rows=3 game_distinct=3" in output
    assert "platform_rows=3 platform_distinct=3" in output
    assert "max_timestamp_delta_ms=0 order_preserved=true" in output


# --- Migration: reverse -------------------------------------------------------


def test_reverse_migration_drops_both_columns_and_keeps_other_data(identity_harness):
    apps = identity_harness
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    user = User.objects.create(username="reverse-owner")
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    game = create_game_at(
        apps, library, name="Persistent Game", created_at=timezone.now()
    )
    platform = create_platform_at(
        apps, name="Persistent Platform", created_at=timezone.now()
    )

    new_apps = migrate_to_identity()
    Game = new_apps.get_model("games", "Game")
    Platform = new_apps.get_model("games", "Platform")
    assert Game.objects.get(pk=game.pk).uuid is not None
    assert Platform.objects.get(pk=platform.pk).uuid is not None

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_IDENTITY])
    reverted_apps = executor.loader.project_state([BEFORE_IDENTITY]).apps

    assert "uuid" not in table_columns("games_game")
    assert "uuid" not in table_columns("games_platform")

    RevertedGame = reverted_apps.get_model("games", "Game")
    RevertedPlatform = reverted_apps.get_model("games", "Platform")
    assert RevertedGame.objects.get(pk=game.pk).name == "Persistent Game"
    assert RevertedPlatform.objects.get(pk=platform.pk).name == "Persistent Platform"
