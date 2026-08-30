from datetime import date

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from timetracker.temporal import TemporalValue, TemporalValueParseError

pytestmark = pytest.mark.django_db

BEFORE_TEMPORAL = ("games", "0016_library_config_uuid_primary_key")
WITH_TEMPORAL = ("games", "0017_temporal_value_domain")

PUBLIC_FUNCTIONS_AT_0017 = {
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
PRIVATE_FUNCTIONS_AT_0017 = {
    "_timetracker_temporal_atom_lower": ("date", "i"),
    "_timetracker_temporal_atom_upper": ("date", "i"),
    "_timetracker_temporal_atom_precision": ("text", "i"),
}
FUNCTIONS_AT_0017 = PUBLIC_FUNCTIONS_AT_0017 | PRIVATE_FUNCTIONS_AT_0017
PUBLIC_QUALIFIER_FUNCTIONS = {
    "timetracker_temporal_qualifier": ("text", "i"),
    "timetracker_temporal_start_qualifier": ("text", "i"),
    "timetracker_temporal_end_qualifier": ("text", "i"),
}
PRIVATE_QUALIFIER_FUNCTIONS = {
    "_timetracker_temporal_atom_qualifier": ("text", "i"),
    "_timetracker_temporal_atom_unqualified": ("text", "i"),
}
QUALIFIER_FUNCTIONS = PUBLIC_QUALIFIER_FUNCTIONS | PRIVATE_QUALIFIER_FUNCTIONS
PUBLIC_FUNCTIONS = PUBLIC_FUNCTIONS_AT_0017 | PUBLIC_QUALIFIER_FUNCTIONS
ALL_FUNCTIONS = FUNCTIONS_AT_0017 | QUALIFIER_FUNCTIONS
SEARCH_PATH = "pg_catalog, public"


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


def temporal_qualifier_projection(value):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                timetracker_temporal_qualifier(%s),
                timetracker_temporal_start_qualifier(%s),
                timetracker_temporal_end_qualifier(%s)
            """,
            [value] * 3,
        )
        return cursor.fetchone()


def temporal_function_metadata(functions):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.proname, pg_catalog.format_type(p.prorettype, NULL), p.provolatile
            FROM pg_proc AS p
            WHERE p.pronamespace = current_schema()::regnamespace
              AND p.proname = ANY(%s)
            ORDER BY p.proname
            """,
            [list(functions)],
        )
        return {
            name: (return_type, volatility) for name, return_type, volatility in cursor
        }


def temporal_function_settings():
    """Every temporal function the schema holds, found by name rather than list."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.proname, p.proconfig
            FROM pg_proc AS p
            WHERE p.pronamespace = current_schema()::regnamespace
              AND p.proname ~ '^_?timetracker_temporal_'
            """
        )
        return dict(cursor)


def python_projection(canonical):
    value = TemporalValue.parse(canonical)
    start = value.start
    end = value.end
    return (
        value.lower_bound,
        value.upper_bound,
        value.kind.value,
        None if value.precision is None else value.precision.value,
        None if start is None else start.kind.value,
        None if end is None else end.kind.value,
        None if start is None or start.precision is None else start.precision.value,
        None if end is None or end.precision is None else end.precision.value,
        None if value.qualifier is None else value.qualifier.value,
        None if start is None or start.qualifier is None else start.qualifier.value,
        None if end is None or end.qualifier is None else end.qualifier.value,
    )


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
    assert temporal_function_metadata(ALL_FUNCTIONS) == ALL_FUNCTIONS


def test_temporal_functions_carry_the_search_path_their_bodies_need():
    """Every body calls its helpers by bare name, and a restore supplies none."""
    settings = temporal_function_settings()

    assert set(settings) == set(ALL_FUNCTIONS)
    assert settings == {name: [f"search_path={SEARCH_PATH}"] for name in ALL_FUNCTIONS}


def test_temporal_domain_accepts_a_value_under_the_search_path_a_dump_sets():
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL search_path = ''")
        cursor.execute("SELECT %s::public.temporal_value", ["2024-02"])
        assert cursor.fetchone() == ("2024-02",)


def test_temporal_domain_rejects_a_value_under_the_search_path_a_dump_sets():
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("SET LOCAL search_path = ''")
        cursor.execute("SELECT %s::public.temporal_value", ["2024-13"])


def test_a_helper_out_of_reach_is_reported_rather_than_read_as_invalid_data():
    """The handler that hid this defect once now lets it through."""
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER FUNCTION public.timetracker_temporal_is_valid(text) "
            "RESET search_path"
        )
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("SET LOCAL search_path = ''")
        cursor.execute("SELECT public.timetracker_temporal_is_valid('2024-02')")


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
        None,
        "0001-01-01",
        "9999-12-31",
        "1900-02",
        "2000-02",
        "0010",
        "9999",
        "001X",
        "999X",
        "2020/2020-01",
        "2020-02/2020-02-01",
        "199X/2001-03-04",
        "../2001-03",
        "/2001-03",
        "1999/..",
        "1999/",
        "1984~",
        "1984-06?",
        "1984-06-11%",
        "198X~",
        "1984~/1986~",
        "1984/1986~",
        "1984?/..",
        "../1986%",
        "1984%/",
    ],
)
def test_temporal_sql_projection_matches_python_contract(canonical):
    assert temporal_projection(canonical) + temporal_qualifier_projection(
        canonical
    ) == python_projection(canonical)


@pytest.mark.parametrize(
    "canonical",
    [
        "",
        " 2024",
        "2023-02-29",
        "2024-13",
        "2024-00",
        "2024-00-01",
        "2024-01-00",
        "2024/2023",
        "2024/2025/2026",
        "../..",
        "../",
        "/..",
        "/",
        "2024??",
        "2024?~",
        "2024~~",
        "?2024",
        "2024-?02",
        "~/2025",
        "1984/%",
        "..?/2025",
        "2001-21~",
        "0000~",
        "10000~",
        "2004-XX~",
        "?",
        "~",
        "%",
        "2001-21",
        "[2020,2021]",
        "2004-XX",
        "1985-04-XX",
        "2004-XX/2005",
        "0000",
        "0000-01",
        "0000-01-01",
        "000X",
        "-1985",
        "10000",
        "10000-01",
        "10000-01-01",
        "2024/10000-01",
        "2024-01-01T12:00:00",
        "٢٠٢٤-٠٢",
        "２０２４",
        "2024‐02",
        "2024⁄02",
    ],
)
def test_temporal_domain_rejects_invalid_or_unsupported_raw_values(canonical):
    with pytest.raises(TemporalValueParseError):
        TemporalValue.parse(canonical)
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


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        (None, (None, None, None)),
        ("1984", (None, None, None)),
        ("1984~", ("approximate", None, None)),
        ("1984-06?", ("uncertain", None, None)),
        ("1984-06-11%", ("both", None, None)),
        ("198X~", ("approximate", None, None)),
        ("1984/1986", (None, None, None)),
        ("1984~/1986~", (None, "approximate", "approximate")),
        ("1984/1986~", (None, None, "approximate")),
        ("1984?/..", (None, "uncertain", None)),
        ("../1986%", (None, None, "both")),
    ],
)
def test_temporal_sql_reads_the_qualifier_of_each_position(canonical, expected):
    assert temporal_qualifier_projection(canonical) == expected


@pytest.mark.parametrize(
    "canonical", ["1984", "1984-06", "1984-06-11", "198X", "1984/1986"]
)
def test_a_qualifier_does_not_move_the_bounds_it_is_written_beside(canonical):
    for symbol in ("?", "~", "%"):
        qualified = canonical.replace("/", f"{symbol}/") + symbol
        assert temporal_projection(qualified) == temporal_projection(canonical)


@pytest.mark.django_db(transaction=True)
def test_temporal_domain_migration_reverses_and_reapplies():
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        MigrationExecutor(connection).migrate([BEFORE_TEMPORAL])
        assert temporal_domain_base_type() is None
        assert temporal_function_metadata(ALL_FUNCTIONS) == {}

        MigrationExecutor(connection).migrate([WITH_TEMPORAL])
        assert temporal_domain_base_type() == "varchar"
        assert temporal_function_metadata(FUNCTIONS_AT_0017) == FUNCTIONS_AT_0017
        assert temporal_function_metadata(QUALIFIER_FUNCTIONS) == {}
        assert temporal_projection("1984") == (
            date(1984, 1, 1),
            date(1984, 12, 31),
            "atomic",
            "year",
            None,
            None,
            None,
            None,
        )
        with (
            pytest.raises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT %s::temporal_value", ["1984~"])
    finally:
        MigrationExecutor(connection).migrate(leaf_nodes)


@pytest.mark.parametrize("canonical", ["1984~", "1984?/1986%"])
def test_an_event_time_stores_a_qualifier_it_projects_no_column_for(canonical):
    """The domain is one constraint. Widening it reaches every column that uses it."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT %s::public.temporal_value", [canonical])
        assert cursor.fetchone() == (canonical,)
