import uuid
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, connection, transaction
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


# --- Migration harness -------------------------------------------------------


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


@pytest.mark.untracked_games
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


def test_the_purchase_games_through_table_uses_promoted_relation_identities():
    assert column_type("games_purchase_games", "game_id") == "uuid_v7"
    assert column_type("games_purchase_games", "purchase_id") == "uuid_v7"
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
