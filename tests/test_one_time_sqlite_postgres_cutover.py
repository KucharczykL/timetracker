import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "one_time_sqlite_postgres_cutover.py"
CONTRACT = (
    Path(__file__).parents[1] / "scripts" / "sqlite_postgres_source_contract.json"
)


@pytest.fixture(scope="module")
def cutover():
    spec = importlib.util.spec_from_file_location(
        "one_time_sqlite_postgres_cutover", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checked_in_source_contract_has_reviewed_fingerprints(cutover):
    contract = cutover.load_source_contract(CONTRACT)
    assert len(contract.migrations) == 128
    assert sum(app == "games" for app, _ in contract.migrations) == 91
    assert ("games", "0055_alter_session_game") in contract.migrations
    assert cutover.canonical_sha256(contract.migrations) == (
        "55da4e2e653aa762f69fd7d373973074bdf03a78a7722cddb7993df8d3de77b5"
    )
    assert cutover.canonical_sha256(contract.table_columns) == (
        "0552819be9424fc52986f50ecfe2c48985ebdfbcd865bbfdf430d8f0e2a1838a"
    )
    assert set(contract.table_columns) == set(contract.table_dispositions)


def test_source_contract_reports_added_and_missing_structure(cutover):
    expected = cutover.SourceContract(
        migrations=(("games", "0001_initial"),),
        table_columns={"games_game": ("id", "name")},
        table_dispositions={"games_game": "transfer"},
        required_empty_tables=(),
        schedule={
            "name": "Update converted prices",
            "func": "games.tasks.convert_prices",
        },
    )
    actual = cutover.SourceStructure(
        migrations=(("games", "0001_initial"), ("games", "9999_unknown")),
        table_columns={"games_game": ("id", "name", "unexpected")},
    )

    with pytest.raises(cutover.CutoverError) as exc_info:
        cutover.validate_source_structure(actual, expected)

    message = str(exc_info.value)
    assert "games.9999_unknown" in message
    assert "games_game" in message
    assert "unexpected" in message
