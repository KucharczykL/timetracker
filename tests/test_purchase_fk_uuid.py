import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_FK_UUID = ("games", "0011_session_fk_uuid")
WITH_FK_UUID = ("games", "0012_purchase_related_game_uuid")


# --- Migration harness -------------------------------------------------------


@pytest.fixture
def fk_uuid_harness():
    # Migrating down to BEFORE_FK_UUID unapplies every later migration too, so
    # the restore target is the graph's leaf nodes rather than WITH_FK_UUID,
    # which would strand this worker's shared database behind head for every
    # later test that reuses it.
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_FK_UUID])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_FK_UUID]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_fk_uuid():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_FK_UUID])
    return executor.loader.project_state([WITH_FK_UUID]).apps


def seed_historic_world(apps, *, username: str):
    """One library, three games and four purchases, on the pre-cutover schema.

    Two purchases anchor an add-on to a base game; two carry no base game at
    all, which is the nullable half of the invariant the migration must
    preserve.
    """
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    Purchase = apps.get_model("games", "Purchase")

    user = User.objects.create(username=username)
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    games = [
        Game.objects.create(library_id=library.pk, name=f"Historic Game {index}")
        for index in range(3)
    ]
    purchased_on = timezone.now().date()
    purchases = [
        Purchase.objects.create(
            library_id=library.pk,
            date_purchased=purchased_on,
            price=10.0,
            price_currency="USD",
            type="game",
            related_game_id=None,
        ),
        Purchase.objects.create(
            library_id=library.pk,
            date_purchased=purchased_on,
            price=10.0,
            price_currency="USD",
            type="dlc",
            name="First Expansion",
            related_game_id=games[0].pk,
        ),
        Purchase.objects.create(
            library_id=library.pk,
            date_purchased=purchased_on,
            price=10.0,
            price_currency="USD",
            type="season_pass",
            name="Second Season",
            related_game_id=games[2].pk,
        ),
        Purchase.objects.create(
            library_id=library.pk,
            date_purchased=purchased_on,
            price=10.0,
            price_currency="USD",
            type="game",
            related_game_id=None,
        ),
    ]
    return library, games, purchases


def column_type(table_name: str, column_name: str) -> str:
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
    assert row is not None, f"{table_name}.{column_name} does not exist"
    return row[0]


def foreign_key_target(table_name: str, column_name: str) -> tuple[str, str] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints AS constraint_row
            JOIN information_schema.key_column_usage AS key_usage
                ON key_usage.constraint_name = constraint_row.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = constraint_row.constraint_name
            WHERE constraint_row.table_name = %s
                AND constraint_row.constraint_type = 'FOREIGN KEY'
                AND key_usage.column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    return tuple(row) if row is not None else None


# --- Migration: forward -------------------------------------------------------


def test_forward_migration_repoints_the_related_game_relation(fk_uuid_harness, capsys):
    apps = fk_uuid_harness
    _, games, purchases = seed_historic_world(apps, username="purchase-fk-owner")
    Purchase = apps.get_model("games", "Purchase")
    # Comparing by target name is the only comparison that stays meaningful
    # across the type change.
    before = dict(Purchase.objects.values_list("pk", "related_game__name"))

    new_apps = migrate_to_fk_uuid()
    NewGame = new_apps.get_model("games", "Game")
    NewPurchase = new_apps.get_model("games", "Purchase")

    after = dict(NewPurchase.objects.values_list("pk", "related_game__name"))
    assert after == before
    assert sum(1 for name in after.values() if name is None) == 2

    migrated = NewPurchase.objects.get(pk=purchases[1].pk)
    assert migrated.related_game.name == "Historic Game 0"
    assert migrated.related_game_id == NewGame.objects.get(pk=games[0].pk).uuid

    assert column_type("games_purchase", "related_game_id") == "uuid_v7"
    assert foreign_key_target("games_purchase", "related_game_id") == (
        "games_game",
        "uuid",
    )

    output = capsys.readouterr().out
    assert "FK identity rewritten" in output
    assert "purchase_rows=4 purchase_related_games=2" in output
    assert "purchase_related_game_nulls=2" in output
    assert "unmatched=0" in output


# --- Migration: reverse -------------------------------------------------------


def test_reverse_migration_restores_the_original_integer_ids(fk_uuid_harness):
    apps = fk_uuid_harness
    seed_historic_world(apps, username="purchase-fk-reverse-owner")
    Purchase = apps.get_model("games", "Purchase")
    before = dict(Purchase.objects.values_list("pk", "related_game_id"))

    migrate_to_fk_uuid()

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_FK_UUID])
    reverted_apps = executor.loader.project_state([BEFORE_FK_UUID]).apps
    RevertedPurchase = reverted_apps.get_model("games", "Purchase")

    after = dict(RevertedPurchase.objects.values_list("pk", "related_game_id"))
    assert after == before
    assert sum(1 for value in after.values() if value is None) == 2
    assert column_type("games_purchase", "related_game_id") == "bigint"
    assert "related_game_uuid" not in [
        field.name for field in RevertedPurchase._meta.get_fields()
    ]
