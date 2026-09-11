"""A dump written before 0034 loads (#972).

Keep the generated column. A domain CHECK calls `is_valid`, thus reach for that
one function loads a plain column and then stops on a generated column, which
calls `timetracker_temporal_lower` directly. A fixture without a generated
column passes under that incorrect repair.

Keep both directions. Without the failing direction the module cannot show that
it loads a dump that refused before, and a repair that stopped working stays
unseen.
"""

import importlib.util
import os
import re
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parents[1]
TOOLING_PATH = REPOSITORY / "scripts" / "db_dump.py"
CLIENT_PROGRAMS = ("createdb", "dropdb", "psql", "pg_dump", "pg_restore")

#: One pair per xdist worker.
WORKER = os.environ.get("PYTEST_XDIST_WORKER", "master")
SOURCE_DATABASE = f"timetracker_dump972_source_{WORKER}"
TARGET_DATABASE = f"timetracker_dump972_target_{WORKER}"

#: A bare domain column beside generated columns.
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
    """Every row, as psql -At writes it."""
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


def _client_major(tooling, name: str) -> int:
    """The major version a client program reports."""
    finished = subprocess.run(
        [str(tooling.client_tool(name)), "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    found = re.search(r"(\d+)", finished.stdout)
    assert found, finished.stdout
    return int(found.group(1))


def _server_major(tooling) -> int:
    """The major version the server reports."""
    return (
        int(_rows(tooling, tooling.local_database_url(), "SHOW server_version_num")[0])
        // 10000
    )


@pytest.fixture(scope="module")
def tooling():
    """The tooling, or skip the module."""
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
    #: An older client than the server cannot do this.
    #:
    #: `client_tool` reads PATH first, so a machine holding PostgreSQL 16
    #: clients beside an 18 server fails on what the client cannot say —
    #: `createdb` has no `--builtin-locale` before 17, and `pg_dump`
    #: refuses a server newer than itself. Neither is what this module is
    #: about, so it steps aside rather than reporting the repair broken.
    server = _server_major(module)
    for name in CLIENT_PROGRAMS:
        client = _client_major(module, name)
        if client < server:
            pytest.skip(f"{name} is {client}, the server is {server}")
    return module


def _before_0034(domain_sql: str) -> str:
    """Undo both of the properties 0034 gave these functions.

    The migration that wrote them without either is gone, and no state the
    history still holds is missing them, so the shape under test is built by
    taking today's definitions and removing what was added. What each body
    computes is beside the point; these two properties are the whole report.

    Taking the search_path away is the failure: a body calls its helpers by
    bare name, and a restore sets no path to find them under. Widening the
    handler back to OTHERS is what made that failure unreadable -- a helper
    out of reach was answered for, so the domain called every value in the
    dump invalid rather than saying what it could not find.
    """
    stripped, reaches_removed = re.subn(
        r"^ *SET search_path TO .*\n", "", domain_sql, flags=re.MULTILINE
    )
    assert reaches_removed, "no function in the domain SQL states a search_path"
    widened, handlers_widened = re.subn(
        r"EXCEPTION WHEN raise_exception OR data_exception THEN",
        "EXCEPTION WHEN OTHERS THEN",
        stripped,
    )
    assert handlers_widened == 1, "is_valid no longer names the classes it answers for"
    return widened


@pytest.fixture(scope="module")
def pre_0034_dump(tooling, tmp_path_factory):
    """A schema whose functions carry no search_path."""
    domain_sql = _before_0034(
        import_module("games.migrations.0001_initial").CREATE_TEMPORAL_VALUE_DOMAIN
    )
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
    """Drop the target before and after."""
    database_url = tooling.local_database_url()
    maintenance = f"--maintenance-db={tooling.with_database(database_url, 'postgres')}"
    _drop(tooling, maintenance, TARGET_DATABASE)
    try:
        yield database_url
    finally:
        _drop(tooling, maintenance, TARGET_DATABASE)


def test_the_fixture_reproduces_the_reported_failure(tooling, pre_0034_dump, scratch):
    """One pg_restore still fails, as #972 reports."""
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
    """An is_valid-only repair stops here."""
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
