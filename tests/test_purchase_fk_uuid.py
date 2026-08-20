import uuid
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.forms import PurchaseForm
from games.models import Game, Purchase

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)

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


# --- Live ORM behaviour -------------------------------------------------------


def _purchase(library, **overrides) -> Purchase:
    fields = {
        "library": library,
        "date_purchased": timezone.now().date(),
        "price": 10.0,
        "price_currency": "USD",
        "ownership_type": Purchase.DIGITAL,
        "type": Purchase.GAME,
    }
    return Purchase.objects.create(**{**fields, **overrides})


@pytest.fixture
def base_game(owned_library):
    return Game.objects.create(library=owned_library, name="Base")


@pytest.fixture
def other_game(owned_library):
    return Game.objects.create(library=owned_library, name="Other")


@pytest.fixture
def dlc_purchase(owned_library, base_game):
    return _purchase(
        owned_library,
        type=Purchase.DLC,
        name="Expansion",
        related_game=base_game,
    )


def test_related_game_attname_reads_back_as_the_games_identity(base_game, dlc_purchase):
    assert dlc_purchase.related_game_id == base_game.pk


def test_purchase_filters_by_related_instance_and_by_integer_id(
    base_game, dlc_purchase
):
    assert Purchase.objects.filter(related_game=base_game).count() == 1
    assert Purchase.objects.filter(related_game__id=base_game.id).count() == 1


def test_addon_purchases_reverse_accessor_reaches_the_purchase(base_game, dlc_purchase):
    assert list(base_game.addon_purchases.all()) == [dlc_purchase]


def test_deleting_the_base_game_clears_the_link_without_deleting_the_purchase(
    base_game, dlc_purchase
):
    base_game.delete()
    dlc_purchase.refresh_from_db()
    assert dlc_purchase.related_game_id is None
    assert Purchase.objects.filter(pk=dlc_purchase.pk).exists()


def test_database_rejects_a_purchase_naming_a_game_uuid_no_game_owns(owned_library):
    # bulk_create, not save(): save() runs clean(), which dereferences
    # self.related_game and would raise in Python before PostgreSQL sees the row.
    orphan = Purchase(
        library=owned_library,
        date_purchased=timezone.now().date(),
        price_currency="USD",
        type=Purchase.DLC,
        name="Orphan",
    )
    orphan.related_game_id = uuid.uuid4()
    with pytest.raises(IntegrityError), transaction.atomic():
        Purchase.objects.bulk_create([orphan])


# --- Form identity ------------------------------------------------------------


def test_purchaseform_preselects_the_base_game_by_integer_id(
    owned_user, owned_library, base_game, dlc_purchase
):
    form = PurchaseForm(
        instance=dlc_purchase,
        library=owned_library,
        user=owned_user,
        presentation=PRESENTATION,
    )
    assert form["related_game"].value() == base_game.id


def test_purchaseform_posting_an_identity_saves_the_right_base_game(
    owned_user, owned_library, base_game, other_game, dlc_purchase
):
    form = PurchaseForm(
        {
            "games": [other_game.id],
            "date_purchased": "2026-01-01",
            "price": "1",
            "price_currency": "USD",
            "ownership_type": Purchase.DIGITAL,
            "type": Purchase.DLC,
            "related_game": str(base_game.id),
            "name": "Expansion",
        },
        instance=dlc_purchase,
        library=owned_library,
        user=owned_user,
        presentation=PRESENTATION,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.related_game_id == base_game.pk


# --- Deferred many-to-many ----------------------------------------------------


def test_the_purchase_games_through_table_is_half_converted():
    """The many-to-many link converts one column per promoted target.

    Django cannot point an auto-created intermediary at a non-primary-key
    field, so each half of this table moves when its own target's uuid becomes
    the primary key. `game_id` moved with the catalog; `purchase_id` is still
    integer and moves when Purchase is promoted. Rewrite this test then; do not
    delete it now.
    """
    assert column_type("games_purchase_games", "game_id") == "uuid_v7"
    assert column_type("games_purchase_games", "purchase_id") == "bigint"
    assert foreign_key_target("games_purchase_games", "game_id") == (
        "games_game",
        "id",
    )
    assert foreign_key_target("games_purchase_games", "purchase_id") == (
        "games_purchase",
        "id",
    )


def test_the_purchase_games_pair_is_still_unique(owned_library, base_game):
    purchase = _purchase(owned_library)
    purchase.games.add(base_game)
    # Through the through model directly: a second .add() is silently filtered
    # by _get_missing_target_ids and would prove nothing.
    through = Purchase.games.through
    with pytest.raises(IntegrityError), transaction.atomic():
        through.objects.create(purchase_id=purchase.pk, game_id=base_game.pk)
