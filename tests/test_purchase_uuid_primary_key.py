"""Promote Purchase UUIDs and the deferred many-to-many relation together."""

import importlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import psycopg
import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from timetracker.uuidv7 import UUIDv7Field

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_PROMOTION = ("games", "0014_session_playhistory_uuid_primary_key")
WITH_PROMOTION = ("games", "0015_purchase_uuid_primary_key")
TABLES = ("games_purchase", "games_purchase_games")
PRESERVED_FIELDS = (
    "library_id",
    "platform_id",
    "related_game_id",
    "date_purchased",
    "date_refunded",
    "infinite",
    "price",
    "price_currency",
    "converted_price",
    "converted_currency",
    "needs_price_update",
    "num_purchases",
    "ownership_type",
    "type",
    "name",
    "created_at",
    "updated_at",
)


@pytest.fixture
def promotion_harness():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    assert WITH_PROMOTION in executor.loader.graph.nodes, (
        "the Purchase primary-key promotion migration is missing"
    )
    executor.migrate([BEFORE_PROMOTION])
    call_command("flush", interactive=False, verbosity=0)
    yield executor.loader.project_state([BEFORE_PROMOTION]).apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_promotion():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_PROMOTION])
    return executor.loader.project_state([WITH_PROMOTION]).apps


def seed_purchase(apps, *, username: str):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    Purchase = apps.get_model("games", "Purchase")
    user = User.objects.create(username=username)
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    games = [
        Game.objects.create(library_id=library.pk, name=f"{username} game {index}")
        for index in range(2)
    ]
    purchase = Purchase.objects.create(
        library_id=library.pk,
        date_purchased=date(2026, 8, 20),
        infinite=True,
        price=12.5,
        price_currency="USD",
        converted_price=49.5,
        converted_currency="EUR",
        needs_price_update=False,
        num_purchases=3,
        ownership_type="di",
        type="game",
        name="Preserved purchase",
    )
    Purchase.games.through.objects.bulk_create(
        [
            Purchase.games.through(purchase_id=purchase.pk, game_id=game.pk)
            for game in games
        ]
    )
    purchase.refresh_from_db()
    expected_price_per_game = purchase.converted_price / purchase.num_purchases
    assert purchase.price_per_game == expected_price_per_game
    values = Purchase.objects.values(*PRESERVED_FIELDS).get(pk=purchase.pk)
    through_rows = set(
        Purchase.games.through.objects.filter(purchase_id=purchase.pk).values_list(
            "id", "purchase__uuid", "game_id"
        )
    )
    return purchase.uuid, values, through_rows, expected_price_per_game


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


def raw_insert_purchase(model, *, identity=None, library_id):
    values = {
        "library_id": library_id,
        "date_purchased": date(2026, 8, 20),
        "price": 1,
        "price_currency": "USD",
    }
    instance = model(**values)
    fields = [
        field
        for field in model._meta.local_concrete_fields
        if not field.primary_key and not field.generated
    ]
    columns = [field.column for field in fields]
    params = [field.get_prep_value(field.pre_save(instance, True)) for field in fields]
    if identity is not None:
        columns.insert(0, "id")
        params.insert(0, identity)
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "games_purchase" ({", ".join(f"{column}" for column in columns)}) '
            f"VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id",
            params,
        )
        return uuid.UUID(str(cursor.fetchone()[0]))


def test_model_declares_uuidv7_primary_key_without_a_second_uuid_field():
    from games.models import Purchase

    assert isinstance(Purchase._meta.pk, UUIDv7Field)
    assert Purchase._meta.pk.name == "id"
    assert Purchase._meta.pk.primary_key is True
    assert Purchase._meta.pk.editable is False
    assert Purchase._meta.pk.serialize is False
    assert "uuid" not in {field.name for field in Purchase._meta.local_fields}


def test_forward_preserves_uuid_row_values_and_every_game_link(promotion_harness):
    purchase_uuid, expected_values, expected_through_rows, expected_price_per_game = (
        seed_purchase(promotion_harness, username="promotion-forward")
    )

    apps = migrate_to_promotion()
    Purchase = apps.get_model("games", "Purchase")
    migrated = Purchase.objects.get(pk=purchase_uuid)

    assert (
        Purchase.objects.values(*PRESERVED_FIELDS).get(pk=purchase_uuid)
        == expected_values
    )
    assert migrated.price_per_game == expected_price_per_game
    assert (
        set(
            Purchase.games.through.objects.filter(
                purchase_id=purchase_uuid
            ).values_list("id", "purchase_id", "game_id")
        )
        == expected_through_rows
    )
    assert isinstance(Purchase._meta.pk, UUIDv7Field)
    assert "uuid" not in {field.name for field in Purchase._meta.local_fields}


def test_forward_installs_purchase_and_through_physical_contract(promotion_harness):
    seed_purchase(promotion_harness, username="promotion-schema")
    migrate_to_promotion()

    assert table_columns("games_purchase").isdisjoint({"uuid"})
    assert column_property("games_purchase", "id", "domain_name") == "uuid_v7"
    assert primary_key_columns("games_purchase") == {("id",)}
    assert ("id",) not in non_primary_unique_columns("games_purchase")
    assert column_property("games_purchase", "id", "is_nullable") == "NO"
    assert "uuidv7()" in column_property("games_purchase", "id", "column_default")
    assert (
        column_property("games_purchase_games", "purchase_id", "domain_name")
        == "uuid_v7"
    )
    assert column_property("games_purchase_games", "purchase_id", "is_nullable") == "NO"
    assert foreign_key_targets("games_purchase_games") == {
        "game_id": ("games_game", "id"),
        "purchase_id": ("games_purchase", "id"),
    }
    assert ("purchase_id",) in indexed_column_sets("games_purchase_games")
    assert ("purchase_id", "game_id") in indexed_column_sets("games_purchase_games")


def test_promoted_purchase_default_and_domain_reject_bad_values(promotion_harness):
    apps = promotion_harness
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    user = User.objects.create(username="promotion-domain")
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    apps = migrate_to_promotion()
    Purchase = apps.get_model("games", "Purchase")

    generated = raw_insert_purchase(Purchase, library_id=library.pk)
    assert generated.version == 7
    with pytest.raises(IntegrityError), transaction.atomic():
        raw_insert_purchase(Purchase, identity=generated, library_id=library.pk)
    with pytest.raises(IntegrityError), transaction.atomic():
        raw_insert_purchase(Purchase, identity=uuid.uuid4(), library_id=library.pk)


def test_empty_reverse_restores_integer_purchase_and_through_relation(
    promotion_harness,
):
    migrate_to_promotion()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_PROMOTION])
    apps = executor.loader.project_state([BEFORE_PROMOTION]).apps
    Purchase = apps.get_model("games", "Purchase")

    assert isinstance(Purchase._meta.pk, models.BigAutoField)
    assert Purchase._meta.get_field("uuid").unique is True
    assert column_property("games_purchase", "id", "data_type") == "bigint"
    assert column_property("games_purchase", "id", "is_identity") == "YES"
    assert column_property("games_purchase", "uuid", "domain_name") == "uuid_v7"
    assert "uuidv7()" in column_property("games_purchase", "uuid", "column_default")
    assert primary_key_columns("games_purchase") == {("id",)}
    assert ("uuid",) in non_primary_unique_columns("games_purchase")
    assert (
        column_property("games_purchase_games", "purchase_id", "data_type") == "bigint"
    )
    assert foreign_key_targets("games_purchase_games")["purchase_id"] == (
        "games_purchase",
        "id",
    )
    assert ("purchase_id",) in indexed_column_sets("games_purchase_games")
    assert ("purchase_id", "game_id") in indexed_column_sets("games_purchase_games")


@pytest.mark.parametrize("populated_table", TABLES)
def test_populated_reverse_fails_before_mutation(promotion_harness, populated_table):
    seed_purchase(promotion_harness, username=f"reverse-{populated_table}")
    if populated_table == "games_purchase":
        promotion_harness.get_model(
            "games", "Purchase"
        ).games.through.objects.all().delete()
    migrate_to_promotion()
    before = {table: table_columns(table) for table in TABLES}

    with pytest.raises(RuntimeError, match="backup taken before"):
        MigrationExecutor(connection).migrate([BEFORE_PROMOTION])

    assert {table: table_columns(table) for table in TABLES} == before


def test_reverse_preflight_locks_purchase_and_through_together(
    promotion_harness, monkeypatch
):
    migrate_to_promotion()
    migration = importlib.import_module(
        "games.migrations.0015_purchase_uuid_primary_key"
    )
    connection.ensure_connection()
    assert connection.connection is not None
    connection_params = connection.get_connection_params()
    locks_acquired = threading.Event()
    probe_complete = threading.Event()

    def probe_writes():
        blocked = []
        try:
            assert locks_acquired.wait(timeout=5)
            with psycopg.connect(**connection_params) as concurrent:
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

    original_lock = migration.lock_purchase_tables

    def observed_lock(cursor):
        original_lock(cursor)
        locks_acquired.set()
        assert probe_complete.wait(timeout=5)

    monkeypatch.setattr(migration, "lock_purchase_tables", observed_lock)
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
    Purchase = apps.get_model("games", "Purchase")
    assert isinstance(Purchase._meta.pk, UUIDv7Field)
    assert column_property("games_purchase", "id", "domain_name") == "uuid_v7"
    assert (
        column_property("games_purchase_games", "purchase_id", "domain_name")
        == "uuid_v7"
    )
