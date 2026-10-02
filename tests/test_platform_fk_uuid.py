"""Every relation that names a Platform reads back that Platform's identity."""

import uuid

import pytest
from django.db import IntegrityError, transaction

from games.models import Game, Platform

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


def test_game_platform_id_reads_back_as_the_platforms_identity(game, platform):
    assert game.platform_id == platform.pk


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


def test_platform_reverse_accessor_exposes_games(game, platform):
    assert list(platform.game_set.all()) == [game]


def test_deleting_a_platform_nulls_the_relation(game, platform):
    platform.delete()
    game.refresh_from_db()
    assert game.platform_id is None


def test_database_rejects_a_game_referencing_a_uuid_no_platform_owns(owned_library):
    # bulk_create, not create: Game.save() calls clean(), which dereferences
    # self.platform and raises Platform.DoesNotExist before the insert is ever
    # attempted. The foreign key constraint is what this asserts, so the model's
    # own guard has to be stepped around to reach it.
    with pytest.raises(IntegrityError), transaction.atomic():
        Game.objects.bulk_create(
            [Game(library=owned_library, name="Dangling", platform_id=uuid.uuid7())]
        )
