"""Rebuilding a library's projections into shadow tables and swapping them in.

The models are declared under `isolate_apps("games")` and created with
`schema_editor`, and the rebuild is called with `apps=<model>._meta.apps`:
`isolate_apps` patches `Options.default_apps` and leaves the global registry
alone, so a rebuild reading `django.apps.apps` would discover zero tables here
and every assertion below would pass over nothing.

Isolation is not housekeeping either. An un-isolated `app_label = "games"`
model — or a process-cached twin of one — joins the registry
`games/identity_audit.py` reads, where `tests/test_uuid_identity_audit.py`
asserts set equality against a pinned list.
"""

import pytest
from django.db import connection
from django.test.utils import isolate_apps
from test_projection_targets import ENTRY_TABLE, SHELF_TABLE, declare_projection_models

from games.events.rebuild import (
    insertable_columns,
    projection_models,
    shadow_tables,
)
from games.events.targets import SHADOW_SUFFIX, ShadowTarget
from games.models import ProjectionModel


def create_tables(*models: type[ProjectionModel]) -> None:
    """The tables, for the length of the test.

    Nothing drops them: the test runs inside pytest-django's transaction, and
    PostgreSQL rolls DDL back with everything else.
    """
    with connection.schema_editor() as schema_editor:
        for model in models:
            schema_editor.create_model(model)


def shadow_of(table: str) -> str:
    return f'pg_temp."{table}{SHADOW_SUFFIX}"'


def relation_exists(relation: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [relation])
        return bool(cursor.fetchone()[0])


def index_count(relation: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_index WHERE indrelid = to_regclass(%s)",
            [relation],
        )
        return int(cursor.fetchone()[0])


def foreign_key_count(relation: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FROM pg_constraint
            WHERE conrelid = to_regclass(%s) AND contype = 'f'
            """,
            [relation],
        )
        return int(cursor.fetchone()[0])


def table_columns(relation: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT attname FROM pg_attribute
            WHERE attrelid = to_regclass(%s) AND attnum > 0 AND NOT attisdropped
            ORDER BY attnum
            """,
            [relation],
        )
        return [name for (name,) in cursor.fetchall()]


@pytest.mark.django_db
@isolate_apps("games")
def test_discovery_finds_the_projection_tables_in_the_given_registry():
    shelf, entry = declare_projection_models()

    assert set(projection_models(shelf._meta.apps)) == {shelf, entry}


@pytest.mark.django_db
@isolate_apps("games")
def test_discovery_passes_over_a_manufactured_twin():
    shelf, entry = declare_projection_models()
    ShadowTarget().model(shelf)

    #: A twin is a projection model and is in the registry, so only its
    #: `managed = False` keeps it from being rebuilt as a table of its own.
    assert set(projection_models(shelf._meta.apps)) == {shelf, entry}


def test_the_application_declares_no_projection_table_yet():
    """The honest answer for the current state: the families that own real
    projection tables are a later issue, and this one rebuilds none of them."""
    assert projection_models() == ()


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_table_exists_for_the_length_of_the_block():
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with shadow_tables([shelf, entry]):
        assert relation_exists(shadow_of(SHELF_TABLE))
        assert relation_exists(shadow_of(ENTRY_TABLE))

    assert not relation_exists(shadow_of(SHELF_TABLE))
    assert not relation_exists(shadow_of(ENTRY_TABLE))


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_table_is_dropped_when_the_block_raises():
    shelf, _ = declare_projection_models()
    create_tables(shelf)

    with (
        pytest.raises(RuntimeError, match="the family refused"),
        shadow_tables([shelf]),
    ):
        raise RuntimeError("the family refused")

    assert not relation_exists(shadow_of(SHELF_TABLE))


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_table_carries_the_live_columns_and_indexes():
    shelf, _ = declare_projection_models()
    create_tables(shelf)

    with shadow_tables([shelf]):
        assert table_columns(shadow_of(SHELF_TABLE)) == table_columns(
            f'"{SHELF_TABLE}"'
        )
        #: A family reads back rows it just wrote, at whatever selectivity the
        #: live table was designed for.
        assert index_count(shadow_of(SHELF_TABLE)) == index_count(f'"{SHELF_TABLE}"')
        assert index_count(shadow_of(SHELF_TABLE)) > 1


@pytest.mark.django_db
@isolate_apps("games")
def test_a_shadow_table_carries_no_foreign_key():
    shelf, entry = declare_projection_models()
    create_tables(shelf, entry)

    with shadow_tables([shelf, entry]):
        #: `LIKE ... INCLUDING ALL` leaves foreign keys behind, which is what
        #: lets the shadows be filled in any order: the reference that has to
        #: hold is the one in the live table after the swap.
        assert foreign_key_count(f'"{ENTRY_TABLE}"') == 2
        assert foreign_key_count(shadow_of(ENTRY_TABLE)) == 0


@pytest.mark.django_db
@isolate_apps("games")
def test_the_insertable_columns_are_the_tables_own_minus_the_generated_one():
    shelf, _ = declare_projection_models()
    create_tables(shelf)

    columns = table_columns(f'"{SHELF_TABLE}"')

    assert "played_minutes" in columns
    #: PostgreSQL refuses to be handed a generated column and recomputes it
    #: identically from the ones that are carried.
    assert insertable_columns(shelf) == tuple(
        column for column in columns if column != "played_minutes"
    )
