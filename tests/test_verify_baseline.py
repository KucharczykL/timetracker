"""Unit tests for the schema differ that gates the migration baseline."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
TOOLING_PATH = SCRIPTS / "verify_baseline.py"


@pytest.fixture
def tooling(monkeypatch):
    #: The module imports `db_dump` by bare name, which resolves when the
    #: script runs from its own directory and not when a test imports it.
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("verify_baseline", TOOLING_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_catalog_is_asked_for(tooling):
    queries = tooling.catalog_queries("games")

    assert set(queries) == set(tooling.CATALOG_QUERIES) | {tooling.HISTORY_CATALOG}


def test_the_history_reads_last(tooling):
    """The report ends on the history rather than on a sequence."""
    assert list(tooling.catalog_queries("games"))[-1] == tooling.HISTORY_CATALOG


def test_the_history_is_scoped_to_the_named_app(tooling):
    queries = tooling.catalog_queries("other_app")

    assert "app = 'other_app'" in queries[tooling.HISTORY_CATALOG]


def test_a_label_that_is_not_an_identifier_is_refused(tooling):
    """The label is interpolated, so its shape is checked first."""
    with pytest.raises(tooling.DumpError):
        tooling.catalog_queries("games'; DROP TABLE django_migrations; --")


def test_a_missing_normalize_file_is_refused_before_the_restore(tooling):
    """A mistyped path would otherwise cost a restore and compare as drift."""
    with pytest.raises(tooling.DumpError, match="is not a file"):
        tooling.verify(
            Path("unused.dump"),
            database_url="postgresql://timetracker@127.0.0.1:1/timetracker",
            normalize=Path("no-such-file.sql"),
        )


@pytest.mark.parametrize(
    "write",
    [
        {"migrate": True},
        {"record": "0001_squashed"},
        {"normalize": "statements"},
    ],
    ids=["migrate", "record", "normalize"],
)
def test_each_database_is_round_tripped_before_the_compare(
    tooling, monkeypatch, tmp_path, write
):
    """Later writes take the trip too."""
    calls = []

    def restore(dump, *, database, database_url):
        calls.append(("restore", database))
        return database

    def manage(*arguments, database_url):
        calls.append(("manage", arguments[0], database_url))

    def apply_sql(statements, *, database_url):
        calls.append(("apply_sql", database_url))

    def create_database(database, database_url):
        calls.append(("create", database))
        return database

    def round_trip(url, *, database, database_url):
        calls.append(("round_trip", database))
        return f"{database}-tripped"

    def compare(deployed_url, fresh_url, *, app):
        calls.append(("compare", deployed_url, fresh_url))
        return []

    monkeypatch.setattr(tooling.db_dump, "restore", restore)
    monkeypatch.setattr(tooling, "manage", manage)
    monkeypatch.setattr(tooling, "apply_sql", apply_sql)
    monkeypatch.setattr(tooling, "create_database", create_database)
    monkeypatch.setattr(tooling, "round_trip", round_trip)
    monkeypatch.setattr(tooling, "compare", compare)
    monkeypatch.setattr(tooling, "drop_database", lambda database, url: None)
    if "normalize" in write:
        statements = tmp_path / "cutover.sql"
        statements.write_text("SELECT 1;")
        write = {"normalize": statements}

    tooling.verify(Path("x.dump"), database_url="unused", **write)

    deployed, fresh = tooling.DEPLOYED_DATABASE, tooling.FRESH_DATABASE
    trips = [call for call in calls if call[0] == "round_trip"]
    assert sorted(trips) == sorted([("round_trip", deployed), ("round_trip", fresh)])
    deployed_writes = [
        index
        for index, call in enumerate(calls)
        if call[0] in {"manage", "apply_sql"} and deployed in call
    ]
    assert max(deployed_writes) < calls.index(("round_trip", deployed))
    assert calls.index(("manage", "migrate", fresh)) < calls.index(
        ("round_trip", fresh)
    )
    assert calls[-1] == ("compare", f"{deployed}-tripped", f"{fresh}-tripped")
