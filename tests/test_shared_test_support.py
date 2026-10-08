"""Both suites share one test support."""

import sys
from importlib.machinery import PathFinder
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

HELPERS = sorted(
    path.stem
    for path in TESTS.glob("*.py")
    if not path.stem.startswith("test_") and path.stem != "conftest"
)


@pytest.mark.parametrize("name", HELPERS)
def test_a_helper_shadows_no_module(name):
    """``pythonpath`` puts tests/ first, for app code too."""
    elsewhere = [entry for entry in sys.path if Path(entry or ".").resolve() != TESTS]

    assert name not in sys.stdlib_module_names
    assert PathFinder.find_spec(name, elsewhere) is None


@pytest.mark.parametrize(
    "fixture",
    [
        "_fast_password_hashing",
        "_process_clock_off_the_calendar",
        "_reset_settings_caches",
        "_track_created_games",
        "chunk_queue",
        "unknown_icon_names_fail",
    ],
)
def test_the_shared_fixtures_apply(request, fixture):
    assert fixture in request.fixturenames
