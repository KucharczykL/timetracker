"""Promote Device and FilterPreset UUIDs without changing their identities."""

import importlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from timetracker.uuidv7 import UUIDv7Field

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_PROMOTION = ("games", "0015_purchase_uuid_primary_key")
WITH_PROMOTION = ("games", "0016_library_config_uuid_primary_key")
TABLES = ("games_device", "games_filterpreset")


@pytest.fixture
def promotion_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    assert WITH_PROMOTION in executor.loader.graph.nodes, (
        "the library configuration primary-key promotion migration is missing"
    )
    executor.migrate([BEFORE_PROMOTION])
    call_command("flush", interactive=False, verbosity=0)
    yield executor.loader.project_state([BEFORE_PROMOTION]).apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_promotion():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_PROMOTION])
    return executor.loader.project_state([WITH_PROMOTION]).apps


def seed_library(apps, *, username: str):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    user = User.objects.create(username=username)
    return UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())


def seed_configuration(apps, *, username: str):
    library = seed_library(apps, username=username)
    Game = apps.get_model("games", "Game")
    Device = apps.get_model("games", "Device")
    FilterPreset = apps.get_model("games", "FilterPreset")
    Session = apps.get_model("games", "Session")
    Preferences = apps.get_model("games", "UserLibraryPreferences")

    game = Game.objects.create(library_id=library.pk, name=f"{username} game")
    devices = [
        Device.objects.create(
            library_id=library.pk,
            name=f"{username} device {index}",
            type="Console" if index else "PC",
        )
        for index in range(2)
    ]
    presets = [
        FilterPreset.objects.create(
            library_id=library.pk,
            name=f"{username} preset {index}",
            mode="sessions" if index else "games",
            find_filter={"page": index + 1, "sort": "name"},
            object_filter={
                "nested": {"enabled": bool(index), "values": [index, None, "x"]}
            },
            ui_options={"columns": ["name", "platform"], "dense": bool(index)},
        )
        for index in range(2)
    ]
    Session.objects.create(
        game_id=game.pk,
        device_id=devices[0].uuid,
        timestamp_start=timezone.now(),
        note="with device",
    )
    Session.objects.create(
        game_id=game.pk,
        device_id=None,
        timestamp_start=timezone.now(),
        note="without device",
    )
    Preferences.objects.create(
        library_id=library.pk,
        default_device_id=devices[1].uuid,
        updated_at=timezone.now(),
    )

    return {
        "library_id": library.pk,
        "device_rows": {
            row.uuid: {
                "library_id": row.library_id,
                "name": row.name,
                "type": row.type,
                "created_at": row.created_at,
            }
            for row in devices
        },
        "preset_rows": {
            row.uuid: {
                "library_id": row.library_id,
                "name": row.name,
                "mode": row.mode,
                "find_filter": row.find_filter,
                "object_filter": row.object_filter,
                "ui_options": row.ui_options,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in presets
        },
        "device_ids": [row.uuid for row in devices],
    }


def snapshot(model, fields):
    values = {}
    for row in model.objects.values("id", *fields):
        identity = row.pop("id")
        values[identity] = row
    return values


def table_columns(table_name: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def column_property(table: str, column: str, property_name: str):
    assert property_name in {
        "domain_name",
        "data_type",
        "column_default",
        "is_nullable",
        "is_identity",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {property_name} FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            [table, column],
        )
        row = cursor.fetchone()
    return None if row is None else row[0]


def constraints(table_name: str) -> dict[str, dict]:
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, table_name)


def indexed_column_sets(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(details["columns"])
        for details in constraints(table_name).values()
        if details["index"] or details["unique"] or details["primary_key"]
    }


def primary_key_columns(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(details["columns"])
        for details in constraints(table_name).values()
        if details["primary_key"]
    }


def non_primary_unique_columns(table_name: str) -> set[tuple[str, ...]]:
    return {
        tuple(details["columns"])
        for details in constraints(table_name).values()
        if details["unique"] and not details["primary_key"]
    }


def foreign_key_targets(table_name: str) -> dict[str, tuple[str, str]]:
    return {
        details["columns"][0]: details["foreign_key"]
        for details in constraints(table_name).values()
        if details["foreign_key"] is not None
    }


def raw_insert(model, *, identity=None, **field_values):
    instance = model(**field_values)
    fields = [
        field
        for field in model._meta.local_concrete_fields
        if not field.primary_key and not field.generated
    ]
    columns = [field.column for field in fields]
    values = [
        field.get_db_prep_save(field.pre_save(instance, True), connection)
        for field in fields
    ]
    if identity is not None:
        columns.insert(0, "id")
        values.insert(0, identity)
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{model._meta.db_table}" ({quoted_columns}) '
            f"VALUES ({placeholders}) RETURNING id",
            values,
        )
        return uuid.UUID(str(cursor.fetchone()[0]))


def test_models_use_uuidv7_primary_keys_and_device_relations_target_the_pk(
    owned_library,
):
    from games.models import Device, FilterPreset, Session, UserLibraryPreferences

    for model in (Device, FilterPreset):
        assert isinstance(model._meta.pk, UUIDv7Field)
        assert model._meta.pk.name == "id"
        assert model._meta.pk.primary_key is True
        assert model._meta.pk.editable is False
        assert model._meta.pk.serialize is False
        assert "uuid" not in {field.name for field in model._meta.local_fields}

    assert Session._meta.get_field("device").remote_field.field_name == "id"
    assert (
        UserLibraryPreferences._meta.get_field("default_device").remote_field.field_name
        == "id"
    )

    device = Device.objects.create(library=owned_library, name="Default device")
    preferences = owned_library.preferences
    assert preferences.set_default_device(device) is True
    assert preferences.set_default_device(device) is False


def test_forward_preserves_identities_values_json_and_device_reference_sets(
    promotion_harness,
):
    expected = seed_configuration(promotion_harness, username="promotion-forward")

    apps = migrate_to_promotion()
    Device = apps.get_model("games", "Device")
    FilterPreset = apps.get_model("games", "FilterPreset")
    Session = apps.get_model("games", "Session")
    Preferences = apps.get_model("games", "UserLibraryPreferences")

    assert (
        snapshot(Device, ("library_id", "name", "type", "created_at"))
        == expected["device_rows"]
    )
    assert (
        snapshot(
            FilterPreset,
            (
                "library_id",
                "name",
                "mode",
                "find_filter",
                "object_filter",
                "ui_options",
                "created_at",
                "updated_at",
            ),
        )
        == expected["preset_rows"]
    )
    assert set(Session.objects.values_list("device_id", flat=True)) == {
        None,
        expected["device_ids"][0],
    }
    assert (
        Preferences.objects.get(library_id=expected["library_id"]).default_device_id
        == expected["device_ids"][1]
    )

    for model in (Device, FilterPreset):
        assert isinstance(model._meta.pk, UUIDv7Field)
        assert "uuid" not in {field.name for field in model._meta.local_fields}
    assert Session._meta.get_field("device").remote_field.field_name == "id"
    assert Preferences._meta.get_field("default_device").remote_field.field_name == "id"


def test_forward_installs_the_physical_identity_and_constraint_contract(
    promotion_harness,
):
    seed_configuration(promotion_harness, username="promotion-contract")
    migrate_to_promotion()

    for table in TABLES:
        assert table_columns(table).isdisjoint({"uuid"})
        assert column_property(table, "id", "domain_name") == "uuid_v7"
        assert column_property(table, "id", "is_nullable") == "NO"
        assert "uuidv7()" in column_property(table, "id", "column_default")
        assert primary_key_columns(table) == {("id",)}
        assert ("id",) not in non_primary_unique_columns(table)

    assert foreign_key_targets("games_device")["library_id"] == (
        "games_userlibrary",
        "id",
    )
    assert foreign_key_targets("games_filterpreset")["library_id"] == (
        "games_userlibrary",
        "id",
    )
    assert foreign_key_targets("games_session")["device_id"] == (
        "games_device",
        "id",
    )
    assert foreign_key_targets("games_userlibrarypreferences")["default_device_id"] == (
        "games_device",
        "id",
    )
    assert ("library_id",) in indexed_column_sets("games_device")
    assert ("library_id",) in indexed_column_sets("games_filterpreset")
    assert ("device_id",) in indexed_column_sets("games_session")
    assert ("default_device_id",) in indexed_column_sets("games_userlibrarypreferences")
    assert ("library_id", "mode", "name") in indexed_column_sets("games_filterpreset")


def test_forward_keeps_primary_key_defaults_domains_and_constraints_enforced(
    promotion_harness,
):
    apps = promotion_harness
    library = seed_library(apps, username="promotion-enforcement")
    apps = migrate_to_promotion()
    Device = apps.get_model("games", "Device")
    FilterPreset = apps.get_model("games", "FilterPreset")
    Session = apps.get_model("games", "Session")
    Preferences = apps.get_model("games", "UserLibraryPreferences")
    Game = apps.get_model("games", "Game")

    generated_device = raw_insert(
        Device, library_id=library.pk, name="Generated device"
    )
    generated_preset = raw_insert(
        FilterPreset,
        library_id=library.pk,
        name="Generated preset",
        mode="games",
    )
    assert generated_device.version == 7
    assert generated_preset.version == 7

    with pytest.raises(IntegrityError), transaction.atomic():
        raw_insert(
            Device,
            identity=uuid.uuid4(),
            library_id=library.pk,
            name="Bad device",
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        raw_insert(
            FilterPreset,
            identity=uuid.uuid4(),
            library_id=library.pk,
            name="Bad preset",
            mode="games",
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        FilterPreset.objects.create(
            library_id=library.pk, name="Generated preset", mode="games"
        )

    game = Game.objects.create(library_id=library.pk, name="Enforcement game")
    missing = uuid.uuid7()
    for model, values in (
        (
            Session,
            {
                "game_id": game.pk,
                "device_id": missing,
                "timestamp_start": timezone.now(),
            },
        ),
        (
            Preferences,
            {
                "library_id": library.pk,
                "default_device_id": missing,
                "updated_at": timezone.now(),
            },
        ),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.create(**values)
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_empty_reverse_restores_integer_ids_uuid_columns_and_device_fk_targets(
    promotion_harness,
):
    migrate_to_promotion()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_PROMOTION])
    apps = executor.loader.project_state([BEFORE_PROMOTION]).apps

    for model_name, table in zip(("Device", "FilterPreset"), TABLES, strict=True):
        model = apps.get_model("games", model_name)
        assert isinstance(model._meta.pk, models.BigAutoField)
        assert model._meta.get_field("uuid").unique is True
        assert column_property(table, "id", "data_type") == "bigint"
        assert column_property(table, "id", "is_identity") == "YES"
        assert column_property(table, "uuid", "domain_name") == "uuid_v7"
        assert "uuidv7()" in column_property(table, "uuid", "column_default")
        assert primary_key_columns(table) == {("id",)}
        assert ("uuid",) in non_primary_unique_columns(table)

    assert foreign_key_targets("games_session")["device_id"] == (
        "games_device",
        "uuid",
    )
    assert foreign_key_targets("games_userlibrarypreferences")["default_device_id"] == (
        "games_device",
        "uuid",
    )
    assert ("device_id",) in indexed_column_sets("games_session")
    assert ("default_device_id",) in indexed_column_sets("games_userlibrarypreferences")


@pytest.mark.parametrize("populated_table", TABLES)
def test_populated_reverse_fails_before_mutation(promotion_harness, populated_table):
    apps = promotion_harness
    library = seed_library(apps, username=f"reverse-{populated_table}")
    if populated_table == "games_device":
        apps.get_model("games", "Device").objects.create(
            library_id=library.pk, name="Reverse device"
        )
    else:
        apps.get_model("games", "FilterPreset").objects.create(
            library_id=library.pk,
            name="Reverse preset",
            mode="games",
        )
    migrate_to_promotion()
    before = {table: table_columns(table) for table in TABLES}

    with pytest.raises(RuntimeError, match="pre-migration backup"):
        MigrationExecutor(connection).migrate([BEFORE_PROMOTION])

    assert {table: table_columns(table) for table in TABLES} == before


def test_reverse_preflight_locks_both_promoted_tables(promotion_harness, monkeypatch):
    migrate_to_promotion()
    migration = importlib.import_module(
        "games.migrations.0016_library_config_uuid_primary_key"
    )
    connection.ensure_connection()
    assert connection.connection is not None
    dsn = connection.connection.info.dsn
    locks_acquired = threading.Event()
    probe_complete = threading.Event()

    def probe_writes():
        blocked = []
        try:
            assert locks_acquired.wait(timeout=5)
            with psycopg.connect(dsn) as concurrent:
                for table in TABLES:
                    try:
                        with concurrent.transaction():
                            concurrent.execute("SET LOCAL lock_timeout = '100ms'")
                            concurrent.execute(
                                f'LOCK TABLE "{table}" IN ROW EXCLUSIVE MODE'
                            )
                    except psycopg.errors.LockNotAvailable:
                        blocked.append(table)
        finally:
            probe_complete.set()
        return blocked

    original_lock = migration.lock_promoted_tables

    def observed_lock(cursor):
        original_lock(cursor)
        locks_acquired.set()
        assert probe_complete.wait(timeout=5)

    monkeypatch.setattr(migration, "lock_promoted_tables", observed_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        probe = pool.submit(probe_writes)
        MigrationExecutor(connection).migrate([BEFORE_PROMOTION])
        assert probe.result(timeout=5) == list(TABLES)


def test_one_executor_can_reverse_and_reapply(promotion_harness):
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_PROMOTION])
    executor.loader.build_graph()
    executor.migrate([BEFORE_PROMOTION])
    executor.loader.build_graph()
    executor.migrate([WITH_PROMOTION])

    apps = executor.loader.project_state([WITH_PROMOTION]).apps
    for model_name, table in zip(("Device", "FilterPreset"), TABLES, strict=True):
        model = apps.get_model("games", model_name)
        assert isinstance(model._meta.pk, UUIDv7Field)
        assert table_columns(table).isdisjoint({"uuid"})
        assert column_property(table, "id", "domain_name") == "uuid_v7"
    assert foreign_key_targets("games_session")["device_id"] == (
        "games_device",
        "id",
    )
    assert foreign_key_targets("games_userlibrarypreferences")["default_device_id"] == (
        "games_device",
        "id",
    )
