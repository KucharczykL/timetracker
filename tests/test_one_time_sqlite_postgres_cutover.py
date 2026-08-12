import importlib.util
import json
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


def test_transfer_models_match_the_approved_table_disposition(cutover):
    contract = cutover.load_source_contract(CONTRACT)
    assert {model._meta.db_table for model in cutover.transfer_models()} == {
        table
        for table, disposition in contract.table_dispositions.items()
        if disposition == "transfer" and table != "games_purchase_games"
    }


def test_transfer_models_exclude_regenerated_and_discarded_tables(cutover):
    denied = {
        "auth_permission",
        "django_content_type",
        "django_session",
        "django_admin_log",
        "django_q_task",
        "django_q_ormq",
        "django_q_schedule",
    }
    assert denied.isdisjoint(
        model._meta.db_table for model in cutover.transfer_models()
    )


def test_strip_generated_fields_removes_only_generated_values(cutover):
    record = {
        "model": "games.session",
        "pk": 7,
        "fields": {
            "timestamp_start": "2026-01-01T10:00:00Z",
            "duration_manual": "01:00:00",
            "duration_calculated": "02:00:00",
            "duration_total": "03:00:00",
        },
    }

    assert cutover.strip_generated_fields(record) == {
        "model": "games.session",
        "pk": 7,
        "fields": {
            "timestamp_start": "2026-01-01T10:00:00Z",
            "duration_manual": "01:00:00",
        },
    }


def test_strip_generated_fields_ignores_reverse_relation_descriptors(cutover):
    record = {"model": "games.game", "pk": 1, "fields": {"name": "Example"}}

    assert cutover.strip_generated_fields(record) == record


def test_purchase_count_validation_rejects_stored_link_drift(cutover, monkeypatch):
    monkeypatch.setattr(
        cutover,
        "purchase_count_mismatches",
        lambda alias: [(42, 3, 2)],
    )
    with pytest.raises(cutover.CutoverError, match=r"Purchase 42.*stored=3.*links=2"):
        cutover.validate_purchase_link_counts("sqlite_source")


def test_required_empty_validation_accumulates_all_nonempty_tables(
    cutover, monkeypatch
):
    contract = cutover.SourceContract(
        migrations=(),
        table_columns={name: ("id",) for name in ("a", "b", "c", "d")},
        table_dispositions={name: "require_empty" for name in ("a", "b", "c", "d")},
        required_empty_tables=("a", "b", "c", "d"),
        schedule={},
    )
    monkeypatch.setattr(
        cutover,
        "source_table_counts",
        lambda connection, tables: {
            name: index for index, name in enumerate(sorted(tables), 1)
        },
    )

    with pytest.raises(cutover.CutoverError) as exc_info:
        cutover.validate_required_empty_tables(SimpleNamespace(), contract)

    assert all(name in str(exc_info.value) for name in contract.required_empty_tables)


def test_nonempty_target_is_rejected_before_mutation(cutover, monkeypatch):
    connection = object()
    monkeypatch.setattr(cutover, "target_table_names", lambda _: ["valuable_table"])

    with pytest.raises(cutover.CutoverError, match="valuable_table"):
        cutover.require_initially_empty_target(connection)


@pytest.mark.django_db(transaction=True)
def test_fixture_load_preserves_purchase_count_and_updated_at(cutover, tmp_path):
    from datetime import date

    from django.core import serializers
    from django.db.models.signals import m2m_changed

    from games.models import Game, Purchase
    from games.signals import update_num_purchases

    game = Game.objects.create(name="Cutover fixture")
    purchase = Purchase.objects.create(
        date_purchased=date(2026, 8, 12),
        price=10,
        price_currency="EUR",
        num_purchases=1,
    )
    purchase.games.add(game)
    purchase.refresh_from_db()
    purchase.updated_at = purchase.updated_at.replace(
        microsecond=(purchase.updated_at.microsecond // 1000) * 1000
    )
    Purchase.objects.filter(pk=purchase.pk).update(updated_at=purchase.updated_at)
    purchase_pk = purchase.pk
    original_updated_at = purchase.updated_at
    fixture = tmp_path / "fixture.json"
    fixture.write_text(serializers.serialize("json", [purchase]), encoding="utf-8")
    purchase.delete()

    cutover.load_transfer_fixture(fixture)

    restored = Purchase.objects.get(pk=purchase_pk)
    assert restored.num_purchases == 1
    assert restored.updated_at == original_updated_at
    assert m2m_changed.disconnect(update_num_purchases, sender=Purchase.games.through)
    m2m_changed.connect(update_num_purchases, sender=Purchase.games.through)


@pytest.mark.django_db(transaction=True)
def test_fixture_load_reconnects_receiver_after_failure(cutover, tmp_path):
    from django.db.models.signals import m2m_changed

    from games.models import Purchase
    from games.signals import update_num_purchases

    fixture = tmp_path / "bad.json"
    fixture.write_text("not json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        cutover.load_transfer_fixture(fixture)

    assert m2m_changed.disconnect(update_num_purchases, sender=Purchase.games.through)
    m2m_changed.connect(update_num_purchases, sender=Purchase.games.through)


def test_clear_order_excludes_generated_target_tables(cutover):
    assert "django_content_type" not in cutover.TRANSFER_CLEAR_ORDER
    assert "auth_permission" not in cutover.TRANSFER_CLEAR_ORDER
    assert "django_migrations" not in cutover.TRANSFER_CLEAR_ORDER
    assert "games_purchase_games" in cutover.TRANSFER_CLEAR_ORDER


def test_sequence_reset_includes_purchase_through_table(cutover, monkeypatch):
    captured = {}

    def sequence_reset_sql(style, models):
        captured["tables"] = [model._meta.db_table for model in models]
        return []

    connection = SimpleNamespace(
        ops=SimpleNamespace(sequence_reset_sql=sequence_reset_sql),
        cursor=lambda: pytest.fail("no SQL expected from fake sequence backend"),
    )

    cutover.reset_transfer_sequences(connection, cutover.transfer_models())

    assert "games_purchase_games" in captured["tables"]


def test_report_contains_evidence_not_private_values(cutover):
    report = cutover.build_report(
        source_archive_sha256="a" * 64,
        source_members={"db.sqlite3": "b" * 64},
        git_commit="abc123",
        script_blob="def456",
        source_counts={"games_game": 856},
        discarded_counts={"django_session": 166},
        model_digests={"games.game": "c" * 64},
        generated_results={
            "games.Session.duration_total": {"count": 2767, "match": True}
        },
        aggregate_results={"session_count": 2767},
        sequence_results={"games_game": {"max_pk": 856, "next_pk": 857}},
        smoke_results={"games:list_games": 200},
        schedule_result={
            "name": "Update converted prices",
            "func": "games.tasks.convert_prices",
        },
    )
    encoded = json.dumps(report)
    assert "notes" not in encoded
    assert "password" not in encoded
    assert report["git"]["script_blob"] == "def456"


def test_normalize_orders_dicts_and_tags_database_values(cutover):
    from datetime import UTC, date, datetime, timedelta
    from decimal import Decimal

    normalized = cutover.normalize(
        {
            "z": None,
            "a": [
                1.5,
                Decimal("2.50"),
                datetime(2026, 8, 12, 10, tzinfo=UTC),
                date(2026, 8, 12),
                timedelta(seconds=3),
                True,
            ],
        }
    )

    assert list(normalized) == ["a", "z"]
    assert normalized["a"][0] == {"float": float.hex(1.5)}
    assert normalized["a"][1] == {"decimal": "2.50"}
    assert normalized["a"][4] == {"microseconds": 3_000_000}


@pytest.mark.django_db
def test_smoke_checks_cover_migrated_read_surfaces(cutover, django_user_model):
    django_user_model.objects.create_user(username="cutover-smoke", password="unused")
    results = cutover.run_smoke_checks()
    assert set(results) == {
        "games:index",
        "games:list_games",
        "games:list_sessions",
        "games:list_purchases",
        "games:list_playevents",
        "games:list_statuschanges",
        "games:settings",
        "games:stats_alltime",
        "games:game_filter",
    }
    assert set(results.values()) == {200}
