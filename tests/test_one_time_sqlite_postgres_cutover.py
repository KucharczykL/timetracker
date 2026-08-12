import importlib.util
import sqlite3
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

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


def test_extract_snapshot_rejects_path_traversal(cutover, monkeypatch, tmp_path):
    monkeypatch.setattr(cutover, "require_git_ignored_workspace", lambda path: None)
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../db.sqlite3", b"not safe")

    with pytest.raises(cutover.CutoverError, match="unsafe archive member"):
        cutover.extract_snapshot(archive, tmp_path / "workspace")


def test_extract_snapshot_keeps_database_and_sidecars_together(
    cutover, monkeypatch, tmp_path
):
    monkeypatch.setattr(cutover, "require_git_ignored_workspace", lambda path: None)
    archive = tmp_path / "snapshot.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("db.sqlite3", b"database")
        output.writestr("db.sqlite3-wal", b"wal")
        output.writestr("db.sqlite3-shm", b"shm")

    snapshot = cutover.extract_snapshot(archive, tmp_path / "workspace")

    assert snapshot.database.name == "db.sqlite3"
    assert snapshot.wal and snapshot.wal.name == "db.sqlite3-wal"
    assert snapshot.shm and snapshot.shm.name == "db.sqlite3-shm"
    assert snapshot.archive_sha256 == cutover.sha256_file(archive)


@pytest.mark.parametrize(
    "members, message",
    [
        ({"db.sqlite3-wal": b"wal"}, "db.sqlite3"),
        ({"nested/db.sqlite3": b"database"}, "unsafe archive member"),
    ],
)
def test_extract_snapshot_rejects_invalid_layout(
    cutover, monkeypatch, tmp_path, members, message
):
    monkeypatch.setattr(cutover, "require_git_ignored_workspace", lambda path: None)
    archive = tmp_path / "bad-layout.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name, value in members.items():
            output.writestr(name, value)

    with pytest.raises(cutover.CutoverError, match=message):
        cutover.extract_snapshot(archive, tmp_path / "workspace")


def test_extract_snapshot_rejects_duplicate_database_member(
    cutover, monkeypatch, tmp_path
):
    monkeypatch.setattr(cutover, "require_git_ignored_workspace", lambda path: None)
    archive = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("db.sqlite3", b"first")
        output.writestr("db.sqlite3", b"second")

    with pytest.raises(cutover.CutoverError, match="duplicate archive member"):
        cutover.extract_snapshot(archive, tmp_path / "workspace")


def test_workspace_must_be_git_ignored(cutover):
    workspace = Path(__file__).parents[1] / "not-ignored-cutover-workspace"

    with pytest.raises(cutover.CutoverError, match="Git-ignored"):
        cutover.require_git_ignored_workspace(workspace)


def test_source_uri_is_read_only_without_immutable(cutover, tmp_path):
    database = tmp_path / "db.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE example (id integer primary key)")

    uri = cutover.sqlite_read_only_uri(database)

    assert "mode=ro" in uri
    assert "immutable=1" not in uri


def test_source_structure_matches_contract_by_excluding_generated_columns(
    cutover, django_db_blocker, tmp_path
):
    database = tmp_path / "db.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE django_migrations "
            "(id integer primary key, app text, name text)"
        )
        connection.execute(
            "INSERT INTO django_migrations (app, name) VALUES ('games', '0001')"
        )
        connection.execute(
            "CREATE TABLE example ("
            "id integer primary key, base integer, "
            "derived integer GENERATED ALWAYS AS (base + 1) STORED)"
        )

    with django_db_blocker.unblock():
        source = cutover.configure_source_alias(database)
        try:
            structure = cutover.source_structure(source)
        finally:
            cutover.remove_source_alias(source)

    assert structure.table_columns["example"] == ("id", "base")


def test_source_validation_runs_integrity_and_migration_history_checks(
    cutover, monkeypatch
):
    squash = ("games", "0001_squashed_0036_alter_playevent_days_to_finish")
    structure = cutover.SourceStructure(
        migrations=(squash,),
        table_columns={"django_migrations": ("id", "app", "name")},
    )
    contract = cutover.SourceContract(
        migrations=(squash,),
        table_columns=structure.table_columns,
        table_dispositions={"django_migrations": "validate_only"},
        required_empty_tables=(),
        schedule={},
    )
    statements = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            statements.append(statement)

        def fetchone(self):
            return ("ok",)

    class Loader:
        checked = False

        def __init__(self, connection):
            self.connection = connection
            self.applied_migrations = {squash: object()}

        def check_consistent_history(self, connection):
            assert connection is source
            self.checked = True

    source = SimpleNamespace(cursor=lambda: Cursor())
    monkeypatch.setattr(cutover, "MigrationLoader", Loader)
    monkeypatch.setattr(cutover, "source_structure", lambda connection: structure)
    monkeypatch.setattr(
        cutover,
        "source_table_counts",
        lambda connection, tables: {"django_migrations": 1},
    )

    evidence = cutover.validate_source(source, contract)

    assert statements == ["PRAGMA quick_check"]
    assert evidence.quick_check == "ok"
    assert evidence.effective_squash_applied is True


def test_open_source_preserves_durable_files_but_allows_shm_change(
    cutover, monkeypatch, tmp_path
):
    monkeypatch.setattr(cutover, "require_git_ignored_workspace", lambda path: None)
    archive = tmp_path / "snapshot.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("db.sqlite3", b"database")
        output.writestr("db.sqlite3-wal", b"wal")
        output.writestr("db.sqlite3-shm", b"shm")
    connection = SimpleNamespace(close=lambda: None)
    evidence = SimpleNamespace()
    monkeypatch.setattr(cutover, "configure_source_alias", lambda path: connection)
    monkeypatch.setattr(cutover, "validate_source", lambda source, contract: evidence)
    monkeypatch.setattr(cutover, "remove_source_alias", lambda source: source.close())

    with cutover.open_validated_source(
        archive, tmp_path / "workspace", SimpleNamespace()
    ) as prepared:
        assert prepared.evidence is evidence
        assert prepared.snapshot.shm
        prepared.snapshot.shm.write_bytes(b"changed transient state")


def test_open_source_rejects_durable_file_changes(cutover, monkeypatch, tmp_path):
    monkeypatch.setattr(cutover, "require_git_ignored_workspace", lambda path: None)
    archive = tmp_path / "snapshot.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("db.sqlite3", b"database")
        output.writestr("db.sqlite3-wal", b"wal")
    connection = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(cutover, "configure_source_alias", lambda path: connection)
    monkeypatch.setattr(
        cutover, "validate_source", lambda source, contract: SimpleNamespace()
    )
    monkeypatch.setattr(cutover, "remove_source_alias", lambda source: source.close())

    with (
        pytest.raises(cutover.CutoverError, match="db.sqlite3-wal changed"),
        cutover.open_validated_source(
            archive, tmp_path / "workspace", SimpleNamespace()
        ) as prepared,
    ):
        assert prepared.snapshot.wal
        prepared.snapshot.wal.write_bytes(b"changed durable state")
