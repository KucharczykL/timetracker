import datetime
import uuid

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from games.models import Game, Platform, Purchase

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_FK_UUID = ("games", "0009_playhistory_game_uuid_fk")
WITH_FK_UUID = ("games", "0010_platform_fk_uuid")


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


def seed_platformed_rows(apps, *, username: str):
    """One library, two platforms, and games plus purchases spread across them —
    including one of each with no platform at all, which is the case ID-06's
    NOT NULL relations never exercised."""
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Platform = apps.get_model("games", "Platform")
    Game = apps.get_model("games", "Game")
    Purchase = apps.get_model("games", "Purchase")

    user = User.objects.create(username=username)
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    first = Platform.objects.create(name="Historic Platform 0")
    second = Platform.objects.create(name="Historic Platform 1")

    def purchase(platform_id):
        return Purchase.objects.create(
            library_id=library.pk,
            platform_id=platform_id,
            date_purchased=datetime.date(2026, 1, 1),
            price=10,
            price_currency="USD",
        )

    return {
        "library": library,
        "first": first,
        "second": second,
        # year_released is set because both of Game's unique indexes include
        # it, and a NULL never collides in a unique index - a platformless row
        # with no year is unconstrained by either guarantee.
        "game_on_first": Game.objects.create(
            library_id=library.pk,
            name="Game A",
            platform_id=first.pk,
            year_released=2020,
        ),
        "game_on_second": Game.objects.create(
            library_id=library.pk,
            name="Game B",
            platform_id=second.pk,
            year_released=2020,
        ),
        "platformless_game": Game.objects.create(
            library_id=library.pk, name="Game C", platform_id=None, year_released=2020
        ),
        "purchase_on_first": purchase(first.pk),
        "platformless_purchase": purchase(None),
    }


def column_type(table_name: str, column_name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT domain_name FROM information_schema.columns
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


def unique_index_definitions(table_name: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = %s", [table_name]
        )
        return [row[0] for row in cursor.fetchall() if "UNIQUE" in row[0]]


# --- Migration: forward -------------------------------------------------------


def test_forward_migration_repoints_game_and_purchase_to_platform_uuid(
    fk_uuid_harness, capsys
):
    apps = fk_uuid_harness
    seeded = seed_platformed_rows(apps, username="platform-fk-owner")

    new_apps = migrate_to_fk_uuid()
    NewPlatform = new_apps.get_model("games", "Platform")
    NewGame = new_apps.get_model("games", "Game")
    NewPurchase = new_apps.get_model("games", "Purchase")

    assert (
        NewGame.objects.get(pk=seeded["game_on_first"].pk).platform.name
        == "Historic Platform 0"
    )
    assert (
        NewGame.objects.get(pk=seeded["game_on_second"].pk).platform.name
        == "Historic Platform 1"
    )
    assert (
        NewPurchase.objects.get(pk=seeded["purchase_on_first"].pk).platform.name
        == "Historic Platform 0"
    )
    assert (
        NewGame.objects.get(pk=seeded["game_on_first"].pk).platform_id
        == NewPlatform.objects.get(pk=seeded["first"].pk).uuid
    )

    # The NULL set is unchanged: still NULL, and nothing else became NULL.
    assert NewGame.objects.get(pk=seeded["platformless_game"].pk).platform_id is None
    assert (
        NewPurchase.objects.get(pk=seeded["platformless_purchase"].pk).platform_id
        is None
    )
    assert NewGame.objects.filter(platform_id__isnull=True).count() == 1
    assert NewPurchase.objects.filter(platform_id__isnull=True).count() == 1

    assert column_type("games_game", "platform_id") == "uuid_v7"
    assert column_type("games_purchase", "platform_id") == "uuid_v7"
    assert foreign_key_target("games_game", "platform_id") == (
        "games_platform",
        "uuid",
    )
    assert foreign_key_target("games_purchase", "platform_id") == (
        "games_platform",
        "uuid",
    )

    output = capsys.readouterr().out
    assert "FK identity rewritten" in output
    assert "game_rows=3 game_platforms=2 game_nulls=1" in output
    assert "purchase_rows=2 purchase_platforms=1 purchase_nulls=1" in output
    assert "unmatched=0" in output


def test_forward_migration_keeps_games_uniqueness_guarantees(fk_uuid_harness):
    """Dropping the integer column would cascade both of Game's unique indexes
    away while Django's migration state still lists them — invisible to the
    state-based drift guard, and to every other test in the suite."""
    apps = fk_uuid_harness
    seeded = seed_platformed_rows(apps, username="platform-fk-constraints")

    new_apps = migrate_to_fk_uuid()
    NewGame = new_apps.get_model("games", "Game")

    definitions = unique_index_definitions("games_game")
    composite = [
        definition
        for definition in definitions
        if "library_id" in definition
        and "name" in definition
        and "platform_id" in definition
        and "year_released" in definition
    ]
    assert composite, definitions
    partial = [
        definition
        for definition in definitions
        if "unique_library_platformless_game_name_year" in definition
    ]
    assert partial, definitions

    # Enforced, not merely present.
    with pytest.raises(IntegrityError), transaction.atomic():
        NewGame.objects.create(
            library_id=seeded["library"].pk,
            name="Game A",
            year_released=2020,
            platform_id=NewGame.objects.get(pk=seeded["game_on_first"].pk).platform_id,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        NewGame.objects.create(
            library_id=seeded["library"].pk,
            name="Game C",
            year_released=2020,
            platform_id=None,
        )


# --- Migration: reverse -------------------------------------------------------


def test_reverse_migration_restores_the_original_integer_platform_id(fk_uuid_harness):
    apps = fk_uuid_harness
    seeded = seed_platformed_rows(apps, username="platform-fk-reverse")

    migrate_to_fk_uuid()

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_FK_UUID])
    reverted_apps = executor.loader.project_state([BEFORE_FK_UUID]).apps

    RevertedGame = reverted_apps.get_model("games", "Game")
    RevertedPurchase = reverted_apps.get_model("games", "Purchase")

    assert (
        RevertedGame.objects.get(pk=seeded["game_on_first"].pk).platform_id
        == seeded["first"].pk
    )
    assert (
        RevertedGame.objects.get(pk=seeded["game_on_second"].pk).platform_id
        == seeded["second"].pk
    )
    assert (
        RevertedPurchase.objects.get(pk=seeded["purchase_on_first"].pk).platform_id
        == seeded["first"].pk
    )
    # NULL survives the round trip in both directions.
    assert (
        RevertedGame.objects.get(pk=seeded["platformless_game"].pk).platform_id is None
    )
    assert (
        RevertedPurchase.objects.get(pk=seeded["platformless_purchase"].pk).platform_id
        is None
    )
    assert "platform_uuid" not in [
        field.name for field in RevertedGame._meta.get_fields()
    ]


# --- ORM behavior (current schema) -------------------------------------------


@pytest.fixture
def platform():
    return Platform.objects.create(name="Platform Identity Subject")


@pytest.fixture
def game(owned_library, platform):
    return Game.objects.create(
        library=owned_library, name="Platform FK Subject", platform=platform
    )


def make_purchase(library, platform):
    return Purchase.objects.create(
        library=library,
        platform=platform,
        date_purchased=datetime.date(2026, 1, 1),
        price=10,
        price_currency="USD",
    )


def test_game_platform_id_reads_back_as_the_platforms_identity(game, platform):
    assert game.platform_id == platform.pk


def test_purchase_platform_id_reads_back_as_the_platforms_identity(
    owned_library, platform
):
    assert make_purchase(owned_library, platform).platform_id == platform.pk


def test_filters_by_platform_instance_and_integer_id(game, owned_library, platform):
    other = Platform.objects.create(name="Other Platform")
    Game.objects.create(library=owned_library, name="Elsewhere", platform=other)

    assert list(Game.objects.filter(platform=platform)) == [game]
    assert list(Game.objects.filter(platform__id=platform.id)) == [game]


def test_filters_platformless_rows_by_isnull(owned_library, platform):
    platformless = Game.objects.create(
        library=owned_library, name="Homebrew", platform=None
    )
    Game.objects.create(library=owned_library, name="Retail", platform=platform)
    assert list(Game.objects.filter(platform__isnull=True)) == [platformless]


def test_platform_reverse_accessors_expose_games_and_purchases(
    game, owned_library, platform
):
    purchase = make_purchase(owned_library, platform)
    assert list(platform.game_set.all()) == [game]
    assert list(platform.purchase_set.all()) == [purchase]


def test_deleting_a_platform_nulls_both_relations(game, owned_library, platform):
    purchase = make_purchase(owned_library, platform)
    platform.delete()
    game.refresh_from_db()
    purchase.refresh_from_db()
    assert game.platform_id is None
    assert purchase.platform_id is None


def test_database_rejects_a_game_referencing_a_uuid_no_platform_owns(owned_library):
    # bulk_create, not create: Game.save() calls clean(), which dereferences
    # self.platform and raises Platform.DoesNotExist before the insert is ever
    # attempted. The foreign key constraint is what this asserts, so the model's
    # own guard has to be stepped around to reach it.
    with pytest.raises(IntegrityError), transaction.atomic():
        Game.objects.bulk_create(
            [Game(library=owned_library, name="Dangling", platform_id=uuid.uuid7())]
        )


def test_database_rejects_a_purchase_referencing_a_uuid_no_platform_owns(
    owned_library,
):
    with pytest.raises(IntegrityError), transaction.atomic():
        Purchase.objects.bulk_create(
            [
                Purchase(
                    library=owned_library,
                    platform_id=uuid.uuid7(),
                    date_purchased=datetime.date(2026, 1, 1),
                    price=10,
                    price_currency="USD",
                )
            ]
        )
