import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db

BEFORE_DOMAIN = ("games", "0001_squashed_0036_alter_playevent_days_to_finish")
WITH_DOMAIN = ("games", "0002_uuid_v7_domain")


def domain_base_type() -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT base.typname
            FROM pg_type AS domain
            LEFT JOIN pg_type AS base ON base.oid = domain.typbasetype
            WHERE domain.typname = 'uuid_v7'
            """
        )
        row = cursor.fetchone()
    return None if row is None else row[0]


def test_uuid_v7_domain_uses_uuid_as_its_base_type():
    assert domain_base_type() == "uuid"


def test_uuid_v7_domain_accepts_v7_and_null():
    value = uuid.uuid7()
    with connection.cursor() as cursor:
        cursor.execute("SELECT %s::uuid_v7, NULL::uuid_v7", [value])
        stored, nullable = cursor.fetchone()
    assert uuid.UUID(str(stored)) == value
    assert nullable is None


def test_postgresql_uuidv7_timestamp_tracks_the_database_clock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT clock_timestamp(), uuid_extract_timestamp(uuidv7())")
        database_time, embedded_time = cursor.fetchone()
    assert abs(database_time - embedded_time) < timedelta(seconds=1)


@pytest.mark.parametrize(
    "value",
    [
        uuid.uuid1(),
        uuid.uuid4(),
        uuid.UUID(int=0),
        uuid.UUID(int=(1 << 128) - 1),
        uuid.UUID("00000000-0000-7000-0000-000000000000"),
    ],
)
def test_uuid_v7_domain_rejects_every_non_v7_or_non_rfc_value(value):
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT %s::uuid_v7", [value])


@pytest.mark.django_db(transaction=True)
def test_uuid_v7_domain_migration_reverses_and_reapplies():
    try:
        MigrationExecutor(connection).migrate([BEFORE_DOMAIN])
        assert domain_base_type() is None

        MigrationExecutor(connection).migrate([WITH_DOMAIN])
        assert domain_base_type() == "uuid"
    finally:
        MigrationExecutor(connection).migrate([WITH_DOMAIN])
