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
