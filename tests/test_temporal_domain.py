from datetime import date

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db

BEFORE_TEMPORAL = ("games", "0016_library_config_uuid_primary_key")
WITH_TEMPORAL = ("games", "0017_temporal_value_domain")

PUBLIC_FUNCTIONS = {
    "timetracker_temporal_is_valid": ("boolean", "i"),
    "timetracker_temporal_lower": ("date", "i"),
    "timetracker_temporal_upper": ("date", "i"),
    "timetracker_temporal_kind": ("text", "i"),
    "timetracker_temporal_precision": ("text", "i"),
    "timetracker_temporal_start_kind": ("text", "i"),
    "timetracker_temporal_end_kind": ("text", "i"),
    "timetracker_temporal_start_precision": ("text", "i"),
    "timetracker_temporal_end_precision": ("text", "i"),
}


def temporal_domain_base_type() -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT base.typname
            FROM pg_type AS domain
            LEFT JOIN pg_type AS base ON base.oid = domain.typbasetype
            WHERE domain.typname = 'temporal_value'
            """
        )
        row = cursor.fetchone()
    return None if row is None else row[0]


def temporal_projection(value):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                timetracker_temporal_lower(%s),
                timetracker_temporal_upper(%s),
                timetracker_temporal_kind(%s),
                timetracker_temporal_precision(%s),
                timetracker_temporal_start_kind(%s),
                timetracker_temporal_end_kind(%s),
                timetracker_temporal_start_precision(%s),
                timetracker_temporal_end_precision(%s)
            """,
            [value] * 8,
        )
        return cursor.fetchone()


def test_temporal_domain_uses_fixed_varchar_and_named_constraint():
    assert temporal_domain_base_type() == "varchar"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conname
            FROM pg_constraint AS c
            JOIN pg_type AS t ON t.oid = c.contypid
            WHERE t.typname = 'temporal_value'
            """
        )
        assert cursor.fetchall() == [("temporal_value_valid",)]


def test_temporal_functions_have_stable_return_types_and_are_immutable():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.proname, pg_catalog.format_type(p.prorettype, NULL), p.provolatile
            FROM pg_proc AS p
            WHERE p.proname = ANY(%s)
            ORDER BY p.proname
            """,
            [list(PUBLIC_FUNCTIONS)],
        )
        actual = {
            name: (return_type, volatility) for name, return_type, volatility in cursor
        }

    assert actual == PUBLIC_FUNCTIONS


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        (None, (None, None, "unknown", None, None, None, None, None)),
        (
            "2024-02-29",
            (
                date(2024, 2, 29),
                date(2024, 2, 29),
                "atomic",
                "day",
                None,
                None,
                None,
                None,
            ),
        ),
        (
            "2023-02",
            (
                date(2023, 2, 1),
                date(2023, 2, 28),
                "atomic",
                "month",
                None,
                None,
                None,
                None,
            ),
        ),
        (
            "2024",
            (
                date(2024, 1, 1),
                date(2024, 12, 31),
                "atomic",
                "year",
                None,
                None,
                None,
                None,
            ),
        ),
        (
            "199X",
            (
                date(1990, 1, 1),
                date(1999, 12, 31),
                "atomic",
                "decade",
                None,
                None,
                None,
                None,
            ),
        ),
        (
            "1999/2001-03",
            (
                date(1999, 1, 1),
                date(2001, 3, 31),
                "range",
                None,
                "known",
                "known",
                "year",
                "month",
            ),
        ),
        (
            "../2001-03",
            (None, date(2001, 3, 31), "range", None, "open", "known", None, "month"),
        ),
        (
            "1999/..",
            (date(1999, 1, 1), None, "range", None, "known", "open", "year", None),
        ),
        (
            "/2001-03",
            (None, date(2001, 3, 31), "range", None, "unknown", "known", None, "month"),
        ),
        (
            "1999/",
            (date(1999, 1, 1), None, "range", None, "known", "unknown", "year", None),
        ),
    ],
)
def test_temporal_sql_projection_preserves_supported_values(canonical, expected):
    assert temporal_projection(canonical) == expected


@pytest.mark.parametrize(
    "canonical",
    [
        "",
        " 2024",
        "2023-02-29",
        "2024-13",
        "2024/2023",
        "../..",
        "../",
        "/..",
        "/",
        "2024?",
        "2001-21",
        "[2020,2021]",
        "2004-XX",
        "0000",
        "000X",
        "-1985",
        "10000",
        "2024-01-01T12:00:00",
        "٢٠٢٤-٠٢",
        "２０２４",
    ],
)
def test_temporal_domain_rejects_invalid_or_unsupported_raw_values(canonical):
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT %s::temporal_value", [canonical])


def test_temporal_domain_accepts_null_and_canonical_scalar():
    with connection.cursor() as cursor:
        cursor.execute("SELECT NULL::temporal_value, %s::temporal_value", ["2024-02"])
        assert cursor.fetchone() == (None, "2024-02")


def test_temporal_projection_is_independent_of_datestyle_and_timezone():
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL DateStyle = 'SQL, DMY'")
        cursor.execute("SET LOCAL TimeZone = 'Pacific/Auckland'")
        assert temporal_projection("2024-02") == (
            date(2024, 2, 1),
            date(2024, 2, 29),
            "atomic",
            "month",
            None,
            None,
            None,
            None,
        )


@pytest.mark.django_db(transaction=True)
def test_temporal_domain_migration_reverses_and_reapplies():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        MigrationExecutor(connection).migrate([BEFORE_TEMPORAL])
        assert temporal_domain_base_type() is None

        MigrationExecutor(connection).migrate([WITH_TEMPORAL])
        assert temporal_domain_base_type() == "varchar"
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)
