"""A dump written before migration 0034 loads through `restore()` (#972).

`0017_temporal_value_domain` created twelve functions that call their helpers
by bare name and carry no `search_path` of their own. A dump opens every
session with an empty one, so during a load those calls reach nothing:
`timetracker_temporal_is_valid` catches the lookup failure and the domain
answers that the value is invalid.

The fixture is the smallest schema that tells a working repair from a broken
one. A domain CHECK routes through `is_valid`, so reach for that one function
loads a plain column and then stops on a generated column, which calls
`timetracker_temporal_lower` directly. A fixture with no generated column
passes under the wrong repair, which is the repair `docs/deployment.md` used
to teach.

There is no expression index here. One cannot be built while its function is
unset, so no dump this tool must load carries one, and a fixture holding one
would prove something about a database that cannot exist.
"""

import importlib.util
import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parents[1]
TOOLING_PATH = REPOSITORY / "scripts" / "db_dump.py"
CLIENT_PROGRAMS = ("createdb", "dropdb", "psql", "pg_dump", "pg_restore")

#: Each xdist worker gets its own pair, and both are dropped in a finally.
WORKER = os.environ.get("PYTEST_XDIST_WORKER", "master")
SOURCE_DATABASE = f"timetracker_dump972_source_{WORKER}"
TARGET_DATABASE = f"timetracker_dump972_target_{WORKER}"

#: `games_game` holds a bare domain column; `games_release` holds generated
#: columns over the same domain, which is the pair that tells a whole repair
#: from a partial one. The CHECK is written inline by `pg_dump`, so it first
#: runs during the COPY beside them.
PROBE_SCHEMA = """
CREATE TABLE probe_game (
    id integer PRIMARY KEY,
    original_release_date temporal_value
);

CREATE TABLE probe_release (
    id integer PRIMARY KEY,
    release_date temporal_value,
    release_date_lower date GENERATED ALWAYS AS (
        timetracker_temporal_lower(release_date::text)) STORED,
    release_date_precision text GENERATED ALWAYS AS (
        timetracker_temporal_precision(release_date::text)) STORED,
    CONSTRAINT probe_release_is_atomic
        CHECK (timetracker_temporal_kind(release_date::text) = 'atomic')
);

INSERT INTO probe_game (id, original_release_date)
    VALUES (1, '2026'), (2, '1984-05'), (3, '199X');
INSERT INTO probe_release (id, release_date)
    VALUES (1, '2026'), (2, '199X');
"""

DOMAIN_REFUSAL = "violates check constraint"


def _apply(tooling, database_url: str, statements: str) -> None:
    tooling.run(
        [
            str(tooling.client_tool("psql")),
            "-X",
            "--set=ON_ERROR_STOP=1",
            "--quiet",
            f"--dbname={database_url}",
            f"--command={statements}",
        ]
    )


def _drop(tooling, maintenance: str, database: str) -> None:
    tooling.run(
        [str(tooling.client_tool("dropdb")), maintenance, "--if-exists", database]
    )


def _create(tooling, maintenance: str, database: str) -> None:
    tooling.run(
        [
            str(tooling.client_tool("createdb")),
            maintenance,
            "--template=template0",
            f"--encoding={tooling.REQUIRED_ENCODING}",
            "--locale-provider=builtin",
            f"--builtin-locale={tooling.REQUIRED_BUILTIN_LOCALE}",
            database,
        ]
    )


def _rows(tooling, database_url: str, query: str) -> list[str]:
    """Every row of a query, as psql's `-At` writes it."""
    finished = subprocess.run(
        [
            str(tooling.client_tool("psql")),
            "-X",
            "-At",
            f"--dbname={database_url}",
            f"--command={query}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return finished.stdout.split()


@pytest.fixture(scope="module")
def tooling():
    """`scripts/db_dump.py`, skipping the module if a client program is absent."""
    specification = importlib.util.spec_from_file_location(
        "db_dump_roundtrip", TOOLING_PATH
    )
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    for name in CLIENT_PROGRAMS:
        try:
            module.client_tool(name)
        except module.DumpError as absent:
            pytest.skip(str(absent))
    return module


@pytest.fixture(scope="module")
def pre_0034_dump(tooling, tmp_path_factory):
    """A dump of a schema whose functions carry no `search_path`.

    The domain SQL is read from the frozen migration rather than migrated to.
    The migration is the historical record, and the record is the thing under
    test; reaching the same state by migrating costs eighteen nodes and an
    INSERT satisfying `games_game` as of 0018.
    """
    domain_sql = import_module(
        "games.migrations.0017_temporal_value_domain"
    ).CREATE_TEMPORAL_VALUE_DOMAIN
    database_url = tooling.local_database_url()
    maintenance = f"--maintenance-db={tooling.with_database(database_url, 'postgres')}"
    source_url = tooling.with_database(database_url, SOURCE_DATABASE)
    dump = tmp_path_factory.mktemp("dump972") / "pre-0034.dump"
    _drop(tooling, maintenance, SOURCE_DATABASE)
    try:
        _create(tooling, maintenance, SOURCE_DATABASE)
        _apply(tooling, source_url, domain_sql)
        _apply(tooling, source_url, PROBE_SCHEMA)
        tooling.run(
            [
                str(tooling.client_tool("pg_dump")),
                source_url,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                f"--file={dump}",
            ]
        )
        yield dump
    finally:
        _drop(tooling, maintenance, SOURCE_DATABASE)


@pytest.fixture
def scratch(tooling):
    """Drop the target before and after, whatever the test did to it."""
    database_url = tooling.local_database_url()
    maintenance = f"--maintenance-db={tooling.with_database(database_url, 'postgres')}"
    _drop(tooling, maintenance, TARGET_DATABASE)
    try:
        yield database_url
    finally:
        _drop(tooling, maintenance, TARGET_DATABASE)


def test_the_fixture_reproduces_the_reported_failure(tooling, pre_0034_dump, scratch):
    """One pg_restore still fails, which is what #972 reports.

    Without this the passing test below could not show that it loads a dump
    that used to refuse, and a repair that had stopped working would go
    unnoticed.
    """
    maintenance = f"--maintenance-db={tooling.with_database(scratch, 'postgres')}"
    _create(tooling, maintenance, TARGET_DATABASE)

    finished = subprocess.run(
        [
            str(tooling.client_tool("pg_restore")),
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            f"--dbname={tooling.with_database(scratch, TARGET_DATABASE)}",
            str(pre_0034_dump),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert finished.returncode != 0
    assert DOMAIN_REFUSAL in finished.stderr
    assert "temporal_value" in finished.stderr


def test_restore_loads_a_dump_written_before_0034(tooling, pre_0034_dump, scratch):
    scratch_url = tooling.restore(
        pre_0034_dump, database=TARGET_DATABASE, database_url=scratch
    )

    assert _rows(tooling, scratch_url, "SELECT count(*) FROM probe_game") == ["3"]
    assert _rows(tooling, scratch_url, "SELECT count(*) FROM probe_release") == ["2"]


def test_the_generated_columns_hold_their_computed_values(
    tooling, pre_0034_dump, scratch
):
    """A repair reaching `is_valid` alone loads the plain column and stops here."""
    scratch_url = tooling.restore(
        pre_0034_dump, database=TARGET_DATABASE, database_url=scratch
    )

    assert _rows(
        tooling,
        scratch_url,
        "SELECT release_date_lower, release_date_precision"
        " FROM probe_release ORDER BY id",
    ) == ["2026-01-01|year", "1990-01-01|decade"]


def test_every_function_in_the_copy_carries_its_own_reach(
    tooling, pre_0034_dump, scratch
):
    scratch_url = tooling.restore(
        pre_0034_dump, database=TARGET_DATABASE, database_url=scratch
    )

    assert _rows(
        tooling,
        scratch_url,
        "SELECT count(*) FROM pg_proc AS candidate"
        " JOIN pg_namespace AS schema_entry"
        " ON schema_entry.oid = candidate.pronamespace"
        " WHERE schema_entry.nspname = 'public'"
        " AND candidate.prokind = 'f' AND candidate.proconfig IS NULL",
    ) == ["0"]
