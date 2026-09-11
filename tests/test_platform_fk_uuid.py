"""Every relation that names a Platform reads back that Platform's identity."""

import datetime
import uuid

import pytest
from django.db import IntegrityError, transaction

from games.models import Game, Platform, Purchase

pytestmark = pytest.mark.django_db(transaction=True)


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
