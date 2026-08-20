"""Promote Session and play-history UUIDs without changing their identities."""

import importlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import psycopg
import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from timetracker.uuidv7 import UUIDv7Field

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_PROMOTION = ("games", "0013_catalog_uuid_primary_key")
WITH_PROMOTION = ("games", "0014_session_playhistory_uuid_primary_key")
TABLES = (
    "games_session",
    "games_playevent",
    "games_gamestatuschange",
)
PRESERVED_FIELDS = {
    "Session": (
        "game_id",
        "timestamp_start",
        "timestamp_end",
        "timestamp_start_timezone",
        "timestamp_end_timezone",
        "duration_manual",
        "duration_calculated",
        "duration_total",
        "device_id",
        "note",
        "emulated",
        "created_at",
        "modified_at",
    ),
    "PlayEvent": (
        "game_id",
        "started",
        "ended",
        "days_to_finish",
        "note",
        "created_at",
        "updated_at",
    ),
    "GameStatusChange": (
        "game_id",
        "old_status",
        "new_status",
        "timestamp",
    ),
}


@pytest.fixture
def promotion_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    assert WITH_PROMOTION in executor.loader.graph.nodes, (
        "the Session/play-history primary-key promotion migration is missing"
    )
    executor.migrate([BEFORE_PROMOTION])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_PROMOTION]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_promotion():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_PROMOTION])
    return executor.loader.project_state([WITH_PROMOTION]).apps


def snapshot_rows(model, identity_field: str, fields: tuple[str, ...]) -> dict:
    snapshot = {}
    for values in model.objects.values(identity_field, *fields):
        identity = values.pop(identity_field)
        snapshot[identity] = values
    return snapshot


def seed_relations(apps, *, username: str):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    Device = apps.get_model("games", "Device")
    Session = apps.get_model("games", "Session")
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")

    user = User.objects.create(username=username)
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    game = Game.objects.create(library_id=library.pk, name=f"{username} game")
    device = Device.objects.create(library_id=library.pk, name=f"{username} device")
    started = timezone.now().replace(microsecond=123_000)
    Session.objects.create(
        game_id=game.pk,
        device_id=device.uuid,
        timestamp_start=started,
        timestamp_end=started + timedelta(hours=2),
        timestamp_start_timezone="Europe/Prague",
        timestamp_end_timezone="UTC",
        duration_manual=timedelta(minutes=7),
        note="with device",
        emulated=True,
    )
    Session.objects.create(
        game_id=game.pk,
        timestamp_start=started + timedelta(days=1),
        timestamp_start_timezone="UTC",
        duration_manual=timedelta(minutes=13),
        note="without device",
    )
    for day in (1, 2):
        PlayEvent.objects.create(
            game_id=game.pk,
            started=date(2026, 1, day),
            ended=date(2026, 1, day + 2),
            note=f"event {day}",
        )
    for changes_so_far, (old_status, new_status) in enumerate((("u", "p"), ("p", "f"))):
        GameStatusChange.objects.create(
            game_id=game.pk,
            old_status=old_status,
            new_status=new_status,
            timestamp=started + timedelta(minutes=changes_so_far),
        )
    return {
        "game_id": game.pk,
        "device_uuid": device.uuid,
        "rows": {
            "Session": snapshot_rows(Session, "uuid", PRESERVED_FIELDS["Session"]),
            "PlayEvent": snapshot_rows(
                PlayEvent, "uuid", PRESERVED_FIELDS["PlayEvent"]
            ),
            "GameStatusChange": snapshot_rows(
                GameStatusChange,
                "uuid",
                PRESERVED_FIELDS["GameStatusChange"],
            ),
        },
    }


def table_columns(table_name: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def column_type(table_name: str, column_name: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT coalesce(domain_name, data_type)
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    return None if row is None else row[0]


def column_default(table_name: str, column_name: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_default FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def column_is_identity(table_name: str, column_name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT is_identity FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def column_nullability(table_name: str, column_name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


def constraints(table_name: str) -> dict[str, dict]:
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, table_name)


def foreign_key_targets(table_name: str) -> dict[str, tuple[str, str]]:
    return {
        details["columns"][0]: details["foreign_key"]
        for details in constraints(table_name).values()
        if details["foreign_key"] is not None
    }


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


def raw_insert(model, *, identity=None, **field_values):
    instance = model(**field_values)
    fields = [
        field
        for field in model._meta.local_concrete_fields
        if not field.primary_key and not field.generated
    ]
    columns = [field.column for field in fields]
    values = [field.get_prep_value(field.pre_save(instance, True)) for field in fields]
    if identity is not None:
        columns.insert(0, model._meta.pk.column)
        values.insert(0, identity)
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{model._meta.db_table}" ({quoted_columns}) '
            f'VALUES ({placeholders}) RETURNING "{model._meta.pk.column}"',
            values,
        )
        return uuid.UUID(str(cursor.fetchone()[0]))


def test_models_declare_uuidv7_primary_keys_without_a_second_uuid_field():
    from games.models import GameStatusChange, PlayEvent, Session

    for model in (Session, PlayEvent, GameStatusChange):
        assert isinstance(model._meta.pk, UUIDv7Field)
        assert model._meta.pk.name == "id"
        assert model._meta.pk.primary_key is True
        assert model._meta.pk.editable is False
        assert "uuid" not in {field.name for field in model._meta.local_fields}


def test_forward_migration_preserves_uuids_rows_values_and_relationships(
    promotion_harness,
):
    expected = seed_relations(promotion_harness, username="promotion-forward")

    apps = migrate_to_promotion()

    for model_name in ("Session", "PlayEvent", "GameStatusChange"):
        model = apps.get_model("games", model_name)
        assert (
            snapshot_rows(
                model,
                "id",
                PRESERVED_FIELDS[model_name],
            )
            == expected["rows"][model_name]
        )
        assert isinstance(model._meta.pk, UUIDv7Field)
        assert model._meta.pk.name == "id"
        assert "uuid" not in {field.name for field in model._meta.local_fields}


def test_forward_migration_installs_physical_uuid_primary_keys(promotion_harness):
    seed_relations(promotion_harness, username="promotion-primary-keys")

    migrate_to_promotion()

    for table in TABLES:
        assert table_columns(table).isdisjoint({"uuid"})
        assert column_type(table, "id") == "uuid_v7"
        assert primary_key_columns(table) == {("id",)}
        assert column_nullability(table, "id") == "NO"
        assert ("id",) not in non_primary_unique_columns(table)


def test_reverse_preflight_locks_every_table_against_concurrent_writes(
    promotion_harness, monkeypatch
):
    migrate_to_promotion()
    migration = importlib.import_module(
        "games.migrations.0014_session_playhistory_uuid_primary_key"
    )
    connection.ensure_connection()
    assert connection.connection is not None
    dsn = connection.connection.info.dsn
    locks_acquired = threading.Event()
    probe_complete = threading.Event()

    def probe_concurrent_writes():
        blocked_tables = []
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
                        blocked_tables.append(table)
        finally:
            probe_complete.set()
        return blocked_tables

    original_lock = migration.lock_promoted_tables

    def observed_lock(cursor):
        original_lock(cursor)
        locks_acquired.set()
        assert probe_complete.wait(timeout=5)

    monkeypatch.setattr(migration, "lock_promoted_tables", observed_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        probe = pool.submit(probe_concurrent_writes)
        MigrationExecutor(connection).migrate([BEFORE_PROMOTION])
        blocked_tables = probe.result(timeout=5)

    assert blocked_tables == list(TABLES)


def test_forward_migration_preserves_unrelated_indexes_and_outbound_foreign_keys(
    promotion_harness,
):
    seed_relations(promotion_harness, username="promotion-constraints")

    migrate_to_promotion()

    assert foreign_key_targets("games_session") == {
        "device_id": ("games_device", "uuid"),
        "game_id": ("games_game", "id"),
    }
    assert foreign_key_targets("games_playevent") == {"game_id": ("games_game", "id")}
    assert foreign_key_targets("games_gamestatuschange") == {
        "game_id": ("games_game", "id")
    }
    assert {
        ("timestamp_start",),
        ("game_id",),
        ("device_id",),
    } <= indexed_column_sets("games_session")
    assert ("game_id",) in indexed_column_sets("games_playevent")
    assert ("game_id",) in indexed_column_sets("games_gamestatuschange")


def test_forward_migration_keeps_every_outbound_foreign_key_enforced(
    promotion_harness,
):
    seeded = seed_relations(promotion_harness, username="promotion-enforcement")
    apps = migrate_to_promotion()
    missing = uuid.uuid7()

    invalid_rows = (
        (
            apps.get_model("games", "Session"),
            {"game_id": missing, "timestamp_start": timezone.now()},
        ),
        (apps.get_model("games", "PlayEvent"), {"game_id": missing}),
        (
            apps.get_model("games", "GameStatusChange"),
            {"game_id": missing, "new_status": "p"},
        ),
        (
            apps.get_model("games", "Session"),
            {
                "game_id": seeded["game_id"],
                "device_id": missing,
                "timestamp_start": timezone.now(),
            },
        ),
    )
    for model, field_values in invalid_rows:
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.create(**field_values)
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_promoted_identities_keep_database_defaults_and_reject_bad_values(
    promotion_harness,
):
    seeded = seed_relations(promotion_harness, username="promotion-domain")
    apps = migrate_to_promotion()
    model_values = (
        (
            apps.get_model("games", "Session"),
            {"game_id": seeded["game_id"], "timestamp_start": timezone.now()},
        ),
        (apps.get_model("games", "PlayEvent"), {"game_id": seeded["game_id"]}),
        (
            apps.get_model("games", "GameStatusChange"),
            {"game_id": seeded["game_id"], "new_status": "p"},
        ),
    )

    for model, field_values in model_values:
        generated = raw_insert(model, **field_values)
        assert generated.version == 7
        assert "uuidv7()" in column_default(model._meta.db_table, "id")

        with pytest.raises(IntegrityError), transaction.atomic():
            raw_insert(model, identity=generated, **field_values)
        with pytest.raises(IntegrityError), transaction.atomic():
            raw_insert(model, identity=uuid.uuid4(), **field_values)


def test_empty_reverse_restores_integer_ids_and_separate_uuid_columns(
    promotion_harness,
):
    migrate_to_promotion()

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_PROMOTION])
    apps = executor.loader.project_state([BEFORE_PROMOTION]).apps

    for model_name, table in zip(
        ("Session", "PlayEvent", "GameStatusChange"), TABLES, strict=True
    ):
        model = apps.get_model("games", model_name)
        assert isinstance(model._meta.pk, models.BigAutoField)
        assert model._meta.get_field("uuid").unique is True
        assert column_type(table, "id") == "bigint"
        assert column_is_identity(table, "id") == "YES"
        assert column_type(table, "uuid") == "uuid_v7"
        assert "uuidv7()" in column_default(table, "uuid")
        assert ("uuid",) in non_primary_unique_columns(table)


@pytest.mark.parametrize("model_name", ["Session", "PlayEvent", "GameStatusChange"])
def test_populated_reverse_fails_before_mutating_any_table(
    promotion_harness, model_name
):
    seeded = seed_relations(promotion_harness, username=f"reverse-{model_name}")
    for other_model_name in {"Session", "PlayEvent", "GameStatusChange"} - {model_name}:
        promotion_harness.get_model("games", other_model_name).objects.all().delete()
    migrate_to_promotion()
    before = {table: table_columns(table) for table in TABLES}

    with pytest.raises(RuntimeError, match="backup taken before"):
        MigrationExecutor(connection).migrate([BEFORE_PROMOTION])

    assert {table: table_columns(table) for table in TABLES} == before
    for table in TABLES:
        assert column_type(table, "id") == "uuid_v7"
        assert column_type(table, "uuid") is None
    assert seeded["rows"][model_name]


def test_one_migration_executor_can_reverse_and_reapply_the_promotion(
    promotion_harness,
):
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_PROMOTION])
    # MigrationLoader snapshots the recorder when the executor is constructed;
    # refresh that snapshot while retaining the same executor and migration
    # operation objects for the historical-state mutation regression.
    executor.loader.build_graph()
    executor.migrate([BEFORE_PROMOTION])
    executor.loader.build_graph()
    executor.migrate([WITH_PROMOTION])

    apps = executor.loader.project_state([WITH_PROMOTION]).apps
    for model_name, table in zip(
        ("Session", "PlayEvent", "GameStatusChange"), TABLES, strict=True
    ):
        model = apps.get_model("games", model_name)
        assert isinstance(model._meta.pk, UUIDv7Field)
        assert table_columns(table).isdisjoint({"uuid"})
        assert column_type(table, "id") == "uuid_v7"
