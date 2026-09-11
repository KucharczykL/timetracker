import uuid

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from games.api import api
from games.forms import GameForm, PlatformForm
from games.models import Game, Platform

pytestmark = pytest.mark.django_db(transaction=True)


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
