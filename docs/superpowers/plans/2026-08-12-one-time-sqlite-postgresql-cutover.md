# One-time SQLite-to-PostgreSQL Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, test, rehearse, and execute the one-time offline transfer of the known production SQLite database into a new empty PostgreSQL database.

**Architecture:** A tracked Python script uses a command-scoped read-only Django SQLite alias, Django migration/serialization machinery, and the configured PostgreSQL `default` connection. A tracked JSON contract describes the exact known source migration/schema shape; the script transfers only explicitly classified durable models, suppresses the Purchase M2M mutation signal during load, and emits a private reconciliation report. The script and its tests remain tracked through production cutover and are deleted by the later compatibility-cleanup issue.

**Tech Stack:** Python 3.14, Django 6, Python `sqlite3`/`zipfile`/`hashlib`/`json`, PostgreSQL 18.4, psycopg 3, pytest/pytest-django, GNU Make.

## Global Constraints

- The migration is offline. Stop Timetracker and Django-Q before taking the final archive.
- The source archive, extracted database/sidecars, serialized fixture, and run reports stay under the ignored `.cache/sqlite-postgres-cutover/` tree and are never committed.
- The tracked script is `scripts/one_time_sqlite_postgres_cutover.py`; the tracked source contract is `scripts/sqlite_postgres_source_contract.json`.
- The source connection is a non-default SQLite alias opened with `mode=ro`; do not add SQLite to runtime settings and do not use `immutable=1` because the source may contain committed WAL data.
- The target is `DATABASE_URL` and must have zero tables before the script starts. Never merge, resume, truncate a pre-existing database, or retry in place.
- The exact known source contract is 128 migration rows, 91 `games` migration rows ending in `games.0055_alter_session_game`, migration fingerprint `55da4e2e653aa762f69fd7d373973074bdf03a78a7722cddb7993df8d3de77b5`, and table/ordered-column fingerprint `0552819be9424fc52986f50ecfe2c48985ebdfbcd865bbfdf430d8f0e2a1838a`.
- Preserve only the source tables classified `transfer`; regenerate content types/permissions; require the four auth group/permission relation tables to stay empty; discard admin logs, sessions, queue/task history; recreate only `games.tasks.convert_prices` through `schedule_convert_prices`.
- Generated fields are never inserted: `Session.duration_calculated`, `Session.duration_total`, `Purchase.price_per_game`, and `PlayEvent.days_to_finish` are recalculated by PostgreSQL and reconciled by primary key.
- Disconnect only `games.signals.update_num_purchases` for `Purchase.games.through` during fixture load and reconnect it in `finally` on success and failure.
- Rollback before reopening writes is discarding PostgreSQL and restarting the old release with the untouched SQLite archive. After reopening writes, repair forward.
- Keep the Makefile's default `PYTEST_WORKERS`. On Windows Codex desktop, launch `make check`, `make check-fast`, and test targets through a managed hidden process and wait for the final log and exit status.
- Do not modify or stage the existing untracked `.pnpm-store/` directory.

## File Structure

- Create `scripts/one_time_sqlite_postgres_cutover.py`: CLI, archive/source validation, transfer orchestration, target safety, serialization/loading, reconciliation, reporting, and smoke checks.
- Create `scripts/sqlite_postgres_source_contract.json`: exact non-private migration pairs, source table columns, table dispositions, required-empty tables, and expected schedule identity derived from the supplied production copy.
- Create `tests/test_one_time_sqlite_postgres_cutover.py`: focused unit/PostgreSQL tests for every safety boundary and data transformation.
- Modify `docs/superpowers/specs/2026-08-11-one-time-sqlite-postgresql-cutover-design.md` only if real rehearsal evidence disproves an approved assumption; do not silently weaken reconciliation in code.
- Create private run outputs only under `.cache/sqlite-postgres-cutover/`; these are execution evidence, not repository files.

---

### Task 1: Freeze and validate the exact source contract

**Files:**
- Create: `scripts/sqlite_postgres_source_contract.json`
- Create: `scripts/one_time_sqlite_postgres_cutover.py`
- Create: `tests/test_one_time_sqlite_postgres_cutover.py`

**Interfaces:**
- Consumes: supplied archive `C:\Users\lukas\git\timetracker-prod-copy-2026.08.11.19.14.zip` only to generate non-private structure metadata.
- Produces: `CutoverError`; `canonical_sha256(value: object) -> str`; `load_source_contract(path: Path) -> SourceContract`; `source_structure(connection: BaseDatabaseWrapper) -> SourceStructure`; `validate_source_structure(actual: SourceStructure, expected: SourceContract) -> None`.

- [ ] **Step 1: Write contract-validation tests that fail before the script exists**

```python
import importlib.util
import json
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
```

- [ ] **Step 2: Run the focused tests and verify the expected import failure**

Run via the Windows hidden-process procedure:

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -x -v"
```

Expected: FAIL because `scripts/one_time_sqlite_postgres_cutover.py` and the contract do not exist.

- [ ] **Step 3: Generate and review the non-private contract JSON from the supplied copy**

Create an ignored `.cache/sqlite-postgres-cutover/generate_contract.py` with this extraction body, run it against the already extracted snapshot copy, inspect its output, then use `apply_patch` to add that exact output as `scripts/sqlite_postgres_source_contract.json`:

```python
import json
import pathlib
import sqlite3


database = pathlib.Path(".cache/sqlite-cutover-review-20260811/db.sqlite3").resolve()
connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
migrations = connection.execute(
    "SELECT app, name FROM django_migrations ORDER BY app, name"
).fetchall()
tables = [
    row[0]
    for row in connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
]
table_columns = {
    table: [
        row[1]
        for row in connection.execute(
            f'PRAGMA table_info("{table.replace(chr(34), chr(34) * 2)}")'
        )
    ]
    for table in tables
}
dispositions = {
    "auth_group": "require_empty",
    "auth_group_permissions": "require_empty",
    "auth_permission": "regenerate",
    "auth_user": "transfer",
    "auth_user_groups": "require_empty",
    "auth_user_user_permissions": "require_empty",
    "django_admin_log": "discard",
    "django_content_type": "regenerate",
    "django_migrations": "validate_only",
    "django_q_ormq": "discard",
    "django_q_schedule": "recreate",
    "django_q_task": "discard",
    "django_session": "discard",
    "games_device": "transfer",
    "games_exchangerate": "transfer",
    "games_filterpreset": "transfer",
    "games_game": "transfer",
    "games_gamestatuschange": "transfer",
    "games_platform": "transfer",
    "games_playevent": "transfer",
    "games_purchase": "transfer",
    "games_purchase_games": "transfer",
    "games_session": "transfer",
    "games_sitesetting": "transfer",
    "games_userpreferences": "transfer",
}
contract = {
    "migrations": migrations,
    "table_columns": table_columns,
    "table_dispositions": dispositions,
    "required_empty_tables": [
        "auth_group",
        "auth_group_permissions",
        "auth_user_groups",
        "auth_user_user_permissions",
    ],
    "schedule": {
        "func": "games.tasks.convert_prices",
        "name": "Update converted prices",
    },
}
assert len(migrations) == 128
assert len(table_columns) == 25
assert set(table_columns) == set(dispositions)
print(json.dumps(contract, indent=2, ensure_ascii=False))
connection.close()
```

Verify the generated contract produces both approved SHA-256 fingerprints before staging. Do not include row values, usernames, notes, timestamps, credentials, or schedule arguments.

- [ ] **Step 4: Implement immutable contract types and structural comparison**

Add the following foundations to the script:

```python
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any


class CutoverError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class SourceContract:
    migrations: tuple[tuple[str, str], ...]
    table_columns: dict[str, tuple[str, ...]]
    table_dispositions: dict[str, str]
    required_empty_tables: tuple[str, ...]
    schedule: dict[str, str]


@dataclasses.dataclass(frozen=True)
class SourceStructure:
    migrations: tuple[tuple[str, str], ...]
    table_columns: dict[str, tuple[str, ...]]


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_source_contract(path: Path) -> SourceContract:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SourceContract(
        migrations=tuple(tuple(item) for item in raw["migrations"]),
        table_columns={
            key: tuple(value) for key, value in raw["table_columns"].items()
        },
        table_dispositions=dict(raw["table_dispositions"]),
        required_empty_tables=tuple(raw["required_empty_tables"]),
        schedule=dict(raw["schedule"]),
    )
```

`validate_source_structure()` must compare sets and ordered columns, accumulate all migration/table/column differences, verify the disposition covers the exact source table set, and raise one `CutoverError` containing every structural mismatch.

- [ ] **Step 5: Run the focused tests and the static gates**

Run via managed hidden processes:

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -x -v"
make lint
make format-check
make typecheck
```

Expected: all pass; the contract fingerprints equal the approved values.

- [ ] **Step 6: Commit the exact source contract**

```text
git add scripts/sqlite_postgres_source_contract.json scripts/one_time_sqlite_postgres_cutover.py tests/test_one_time_sqlite_postgres_cutover.py
git commit -m "test: freeze SQLite production contract"
```

---

### Task 2: Validate and preserve the archived SQLite snapshot

**Files:**
- Modify: `scripts/one_time_sqlite_postgres_cutover.py`
- Modify: `tests/test_one_time_sqlite_postgres_cutover.py`

**Interfaces:**
- Consumes: `SourceContract` from Task 1; ZIP path and ignored workspace path from CLI.
- Produces: `SnapshotFiles`; `SourceEvidence`; `PreparedSource`; `sha256_file(path: Path) -> str`; `extract_snapshot(archive: Path, workspace: Path) -> SnapshotFiles`; `configure_source_alias(database: Path) -> BaseDatabaseWrapper`; `validate_source(connection, contract) -> SourceEvidence`; `open_validated_source(archive: Path, workspace: Path, contract: SourceContract) -> Iterator[PreparedSource]` as a context manager.

- [ ] **Step 1: Write failing archive and read-only source tests**

```python
import sqlite3
import zipfile


def test_extract_snapshot_rejects_path_traversal(cutover, tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../db.sqlite3", b"not safe")

    with pytest.raises(cutover.CutoverError, match="unsafe archive member"):
        cutover.extract_snapshot(archive, tmp_path / "workspace")


def test_extract_snapshot_keeps_database_and_sidecars_together(cutover, tmp_path):
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


def test_source_uri_is_read_only_without_immutable(cutover, tmp_path):
    database = tmp_path / "db.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE example (id integer primary key)")

    uri = cutover.sqlite_read_only_uri(database)

    assert "mode=ro" in uri
    assert "immutable=1" not in uri
```

Also add tests that reject an archive without `db.sqlite3`, reject unexpected duplicate/nested database members, require the workspace to be Git-ignored, run `PRAGMA quick_check`, call `MigrationLoader.check_consistent_history()`, and prove database/WAL hashes are unchanged after validation while allowing the transient SHM file to change.

- [ ] **Step 2: Run the new tests and verify they fail on missing functions**

Run via a managed hidden process:

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -k 'snapshot or source_uri or source_validation' -x -v"
```

Expected: FAIL because archive/source helpers are absent.

- [ ] **Step 3: Implement safe extraction, hashing, alias lifecycle, and source evidence**

Implement these immutable records:

```python
@dataclasses.dataclass(frozen=True)
class SnapshotFiles:
    archive: Path
    database: Path
    wal: Path | None
    shm: Path | None
    journal: Path | None
    archive_sha256: str
    durable_member_sha256: dict[str, str]


@dataclasses.dataclass(frozen=True)
class SourceEvidence:
    structure: SourceStructure
    table_counts: dict[str, int]
    quick_check: str
    effective_squash_applied: bool


@dataclasses.dataclass(frozen=True)
class PreparedSource:
    snapshot: SnapshotFiles
    evidence: SourceEvidence
    connection: BaseDatabaseWrapper
```

Use `zipfile.ZipFile.infolist()` and accept only top-level `db.sqlite3`, optional `db.sqlite3-wal`, optional `db.sqlite3-shm`, and optional `db.sqlite3-journal`. Resolve every output path and require it remains under the workspace before extraction. Hash the archive, database, WAL, and journal; list but do not immutability-hash SHM.

Register `connections.databases["sqlite_source"]` with the complete Django settings dictionary and `NAME=f"file:{database.as_posix()}?mode=ro"`. `open_validated_source()` extracts, opens, and validates the source, yields `PreparedSource`, then in `finally` closes/deletes the alias and re-hashes the archive/database/WAL/journal to prove durable source contents did not change. `validate_source()` must run `PRAGMA quick_check`, build `MigrationLoader(source)`, call `check_consistent_history(source)`, require the squash key in `loader.applied_migrations`, compute exact structure/count evidence, and call `validate_source_structure()`.

- [ ] **Step 4: Run focused tests and formatting**

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -k 'snapshot or source_uri or source_validation' -x -v"
make lint
make format-check
make typecheck
```

Expected: all pass.

- [ ] **Step 5: Commit source safety**

```text
git add scripts/one_time_sqlite_postgres_cutover.py tests/test_one_time_sqlite_postgres_cutover.py
git commit -m "feat: validate SQLite cutover snapshot"
```

---

### Task 3: Serialize only approved durable data

**Files:**
- Modify: `scripts/one_time_sqlite_postgres_cutover.py`
- Modify: `tests/test_one_time_sqlite_postgres_cutover.py`

**Interfaces:**
- Consumes: validated `sqlite_source` alias and `SourceContract.table_dispositions`.
- Produces: `TRANSFER_MODEL_LABELS`; `transfer_models() -> tuple[type[Model], ...]`; `validate_required_empty_tables(connection, contract) -> None`; `validate_purchase_link_counts(alias: str) -> None`; `write_transfer_fixture(alias: str, path: Path) -> FixtureEvidence`.

- [ ] **Step 1: Write failing disposition, Purchase-count, and generated-field tests**

```python
def test_transfer_models_match_the_approved_table_disposition(cutover):
    contract = cutover.load_source_contract(CONTRACT)
    assert {model._meta.db_table for model in cutover.transfer_models()} == {
        table
        for table, disposition in contract.table_dispositions.items()
        if disposition == "transfer" and table != "games_purchase_games"
    }


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


def test_purchase_count_validation_rejects_stored_link_drift(cutover, monkeypatch):
    monkeypatch.setattr(
        cutover,
        "purchase_count_mismatches",
        lambda alias: [(42, 3, 2)],
    )
    with pytest.raises(cutover.CutoverError, match=r"Purchase 42.*stored=3.*links=2"):
        cutover.validate_purchase_link_counts("sqlite_source")
```

Add a test that `auth_permission`, `django_content_type`, sessions, admin logs, and Django-Q models never appear in the fixture; add a test that all four required-empty source tables produce one accumulated failure when nonempty.

- [ ] **Step 2: Run the tests and verify the behavior is absent**

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -k 'transfer or generated or purchase_count or required_empty' -x -v"
```

Expected: FAIL on missing transfer helpers.

- [ ] **Step 3: Implement the explicit model allowlist and JSON fixture writer**

Use this exact ordered model-label tuple so foreign-key and M2M targets precede dependents:

```python
TRANSFER_MODEL_LABELS = (
    "auth.user",
    "games.platform",
    "games.device",
    "games.game",
    "games.exchangerate",
    "games.gamestatuschange",
    "games.playevent",
    "games.purchase",
    "games.session",
    "games.filterpreset",
    "games.sitesetting",
    "games.userpreferences",
)
```

For each label, resolve `apps.get_model(label)`, use `_base_manager.using(alias).order_by(pk.attname)`, call `serializers.serialize("json", queryset)`, parse the model's records, remove fields for which `model._meta.get_field(name).generated` is true, and append them to one JSON array. Write with UTF-8 and `ensure_ascii=False`. The Purchase serializer carries `games_purchase_games` links through its `games` M2M field; do not serialize the autogenerated through model separately.

Return:

```python
@dataclasses.dataclass(frozen=True)
class FixtureEvidence:
    path: Path
    sha256: str
    model_counts: dict[str, int]
```

- [ ] **Step 4: Run focused tests and static checks**

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -k 'transfer or generated or purchase_count or required_empty' -x -v"
make lint
make format-check
make typecheck
```

Expected: all pass.

- [ ] **Step 5: Commit the bounded export**

```text
git add scripts/one_time_sqlite_postgres_cutover.py tests/test_one_time_sqlite_postgres_cutover.py
git commit -m "feat: serialize approved SQLite data"
```

---

### Task 4: Enforce an empty target and load without mutation

**Files:**
- Modify: `scripts/one_time_sqlite_postgres_cutover.py`
- Modify: `tests/test_one_time_sqlite_postgres_cutover.py`

**Interfaces:**
- Consumes: `FixtureEvidence` from Task 3 and the PostgreSQL `default` connection.
- Produces: `require_initially_empty_target(connection) -> None`; `migrate_target() -> None`; `clear_transfer_targets(models) -> None`; `load_transfer_fixture(path: Path) -> None`; `reset_transfer_sequences(models) -> None`; `recreate_schedule(contract) -> None`.

- [ ] **Step 1: Write failing target-safety and receiver-restoration tests**

```python
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


def test_fixture_load_reconnects_receiver_after_failure(cutover, tmp_path, monkeypatch):
    from django.db.models.signals import m2m_changed
    from games.models import Purchase
    from games.signals import update_num_purchases

    fixture = tmp_path / "bad.json"
    fixture.write_text("not json", encoding="utf-8")

    with pytest.raises(Exception):
        cutover.load_transfer_fixture(fixture)

    assert m2m_changed.disconnect(update_num_purchases, sender=Purchase.games.through)
    m2m_changed.connect(update_num_purchases, sender=Purchase.games.through)
```

Also test that migration/clearing never runs after the initial-empty check fails, target-generated permissions/content types survive clearing, transferred tables are cleared, sequence SQL includes `games_purchase_games`, constraints are checked after load, and schedule recreation calls `schedule_convert_prices` then finds exactly the configured name/function.

- [ ] **Step 2: Run the target/load tests and verify they fail**

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -k 'target or fixture_load or receiver or sequence or schedule' -x -v"
```

Expected: FAIL because target/load functions are missing.

- [ ] **Step 3: Implement target initialization and bounded clearing**

`require_initially_empty_target()` must use `connection.introspection.table_names()` and raise before calling `migrate`. `migrate_target()` calls:

```python
call_command("migrate", database="default", interactive=False, verbosity=1)
```

After migration, verify `django_migrations`, content types, permissions, and the seeded `games_exchangerate` table exist. Clear only transfer targets, using quoted table names in this child-to-parent order: `games_userpreferences`, `games_sitesetting`, `games_filterpreset`, `games_session`, `games_purchase_games`, `games_purchase`, `games_playevent`, `games_gamestatuschange`, `games_game`, `games_exchangerate`, `games_device`, `games_platform`, `auth_user`. Never delete from `django_migrations`, `django_content_type`, or `auth_permission`. Run `connection.check_constraints()` afterward.

- [ ] **Step 4: Implement signal-safe fixture loading, constraints, sequences, and schedule**

Use the exact receiver lifecycle:

```python
disconnected = m2m_changed.disconnect(
    update_num_purchases,
    sender=Purchase.games.through,
)
if not disconnected:
    raise CutoverError("Purchase M2M receiver was not connected before load")
try:
    with fixture_path.open(encoding="utf-8") as fixture:
        for deserialized in serializers.deserialize("json", fixture, using="default"):
            deserialized.save(save_m2m=True, using="default")
finally:
    m2m_changed.connect(update_num_purchases, sender=Purchase.games.through)
```

Wrap loading in `transaction.atomic(using="default")` and `constraint_checks_disabled()`, then call `connection.check_constraints()` before committing. Reset sequences with `connection.ops.sequence_reset_sql(no_style(), [*transfer_models(), Purchase.games.through])`. Recreate the schedule with `call_command("schedule_convert_prices")` and require exactly one `Schedule` row whose `name` and `func` match the contract.

- [ ] **Step 5: Run focused tests and static checks**

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -k 'target or fixture_load or receiver or sequence or schedule' -x -v"
make lint
make format-check
make typecheck
```

Expected: all pass.

- [ ] **Step 6: Commit the target load path**

```text
git add scripts/one_time_sqlite_postgres_cutover.py tests/test_one_time_sqlite_postgres_cutover.py
git commit -m "feat: load SQLite data into empty PostgreSQL"
```

---

### Task 5: Reconcile all transferred data and emit private evidence

**Files:**
- Modify: `scripts/one_time_sqlite_postgres_cutover.py`
- Modify: `tests/test_one_time_sqlite_postgres_cutover.py`

**Interfaces:**
- Consumes: populated `sqlite_source` and PostgreSQL `default`, `SourceEvidence`, `FixtureEvidence`, contract, and Git metadata.
- Produces: `model_digest(model, alias: str, exclude_generated: bool) -> str`; `generated_values(alias: str) -> dict[str, dict[int, object]]`; `aggregate_evidence(alias: str) -> dict[str, object]`; `sequence_evidence(connection, models) -> dict[str, object]`; `run_smoke_checks() -> dict[str, int]`; `build_report(...) -> dict[str, object]`; `write_report(report, path: Path) -> None`.

- [ ] **Step 1: Write failing digest, generated-value, privacy, and smoke tests**

```python
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
```

Add tests that canonical digests ignore only generated fields; JSON dict keys are ordered; datetimes, dates, durations, booleans, nulls, floats, text, and foreign keys normalize identically; generated comparisons report model/PK/field without values; sequence evidence calculates the next value correctly from `last_value/is_called`; report writing refuses a path outside the ignored workspace; and `git rev-parse HEAD:<script>` equals `git hash-object <script>` before orchestration begins.

- [ ] **Step 2: Run reconciliation tests and verify they fail**

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -k 'digest or generated or aggregate or report or smoke or git_blob' -x -v"
```

Expected: FAIL on missing reconciliation/report functions.

- [ ] **Step 3: Implement canonical reconciliation**

Build per-model canonical records from Django field values, ordered by primary key and field name. Normalize with these tagged representations before JSON hashing:

```python
def normalize(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"float": value.hex()}
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, datetime):
        return {"datetime": value.astimezone(UTC).isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, timedelta):
        return {"microseconds": value // timedelta(microseconds=1)}
    if isinstance(value, dict):
        return {key: normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    raise TypeError(f"Unsupported cutover value type: {type(value).__name__}")
```

For FKs use the concrete `attname` ID, not related objects. Hash M2M endpoint pairs separately. Compare source/target counts, PK sets, nongenerated digests, and M2M pairs. Compare each generated field by primary key after normalization. Accumulate every mismatch and raise one `CutoverError` without including field values.

Aggregate evidence must include session count, calculated/manual/total duration sums, per-Game stored playtime digest, Purchase count and price/converted-price sums, Purchase link count, status-history count, user count, filter-preset count, and site-setting count.

- [ ] **Step 4: Implement sequence, smoke, Git identity, and private report output**

For each transferred AutoField table plus `games_purchase_games`, obtain its serial sequence with `pg_get_serial_sequence`, read `last_value` and `is_called`, and report the computed next value. Require next value greater than maximum PK.

`run_smoke_checks()` force-logs in the transferred user with Django `Client`, uses `HTTP_HOST="localhost"`, and GETs:

```python
paths = {
    "games:index": reverse("games:index"),
    "games:list_games": reverse("games:list_games"),
    "games:list_sessions": reverse("games:list_sessions"),
    "games:list_purchases": reverse("games:list_purchases"),
    "games:list_playevents": reverse("games:list_playevents"),
    "games:list_statuschanges": reverse("games:list_statuschanges"),
    "games:settings": reverse("games:settings"),
    "games:stats_alltime": reverse("games:stats_alltime"),
    "games:game_filter": reverse("games:filter_builder", args=["game"]),
}
```

Require every response to be 200, then call `client.logout()` so the smoke-test session is removed. The report stores hashes/counts/results only. Before running, require the script's current blob to equal `git rev-parse HEAD:scripts/one_time_sqlite_postgres_cutover.py`; record both the full commit and blob IDs.

- [ ] **Step 5: Run focused tests and static checks**

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -k 'digest or generated or aggregate or report or smoke or git_blob' -x -v"
make lint
make format-check
make typecheck
```

Expected: all pass.

- [ ] **Step 6: Commit reconciliation and reporting**

```text
git add scripts/one_time_sqlite_postgres_cutover.py tests/test_one_time_sqlite_postgres_cutover.py
git commit -m "feat: reconcile PostgreSQL cutover"
```

---

### Task 6: Wire the CLI and prove orchestration boundaries

**Files:**
- Modify: `scripts/one_time_sqlite_postgres_cutover.py`
- Modify: `tests/test_one_time_sqlite_postgres_cutover.py`

**Interfaces:**
- Consumes: all Tasks 1–5 interfaces.
- Produces: `parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace`; `run_cutover(source_archive: Path, workspace: Path, report_path: Path) -> dict[str, object]`; `main() -> int`.

- [ ] **Step 1: Write failing CLI and stage-order tests**

```python
def test_cli_requires_explicit_archive_workspace_and_report(cutover):
    with pytest.raises(SystemExit):
        cutover.parse_args([])

    args = cutover.parse_args(
        [
            "--source-archive",
            "snapshot.zip",
            "--workspace",
            ".cache/sqlite-postgres-cutover/rehearsal-1",
            "--report",
            ".cache/sqlite-postgres-cutover/rehearsal-1/report.json",
        ]
    )
    assert args.source_archive == Path("snapshot.zip")


def test_orchestration_checks_empty_target_before_migrate(
    cutover, monkeypatch, tmp_path
):
    from contextlib import contextmanager

    calls = []
    monkeypatch.setattr(cutover, "verify_git_identity", lambda: calls.append("git"))
    monkeypatch.setattr(cutover, "require_ignored_workspace", lambda *args: None)

    @contextmanager
    def source(*args):
        calls.append("source")
        yield object()

    monkeypatch.setattr(cutover, "open_validated_source", source)
    monkeypatch.setattr(
        cutover,
        "require_initially_empty_target",
        lambda *args: (_ for _ in ()).throw(cutover.CutoverError("nonempty")),
    )
    monkeypatch.setattr(cutover, "migrate_target", lambda: calls.append("migrate"))

    with pytest.raises(cutover.CutoverError, match="nonempty"):
        cutover.run_cutover(Path("snapshot.zip"), tmp_path, tmp_path / "report.json")

    assert calls == ["git", "source"]
```

Add a complete mocked stage-order test asserting: Git identity → ignored-workspace check → source context validation → empty target → migrate → disposition checks → fixture export → bounded clear → load → sequence reset → schedule recreation → reconciliation/smoke → report → source-context exit/re-hash. Add tests that `main()` returns nonzero with one concise `ERROR:` line and no traceback for `CutoverError`, while unexpected exceptions retain a traceback.

- [ ] **Step 2: Run CLI tests and verify they fail**

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -k 'cli or orchestration or main' -x -v"
```

Expected: FAIL because CLI/orchestration is absent.

- [ ] **Step 3: Implement the linear CLI**

Use this exact interface:

```text
uv run --frozen python scripts/one_time_sqlite_postgres_cutover.py \
  --source-archive C:\path\snapshot.zip \
  --workspace .cache\sqlite-postgres-cutover\rehearsal-1 \
  --report .cache\sqlite-postgres-cutover\rehearsal-1\report.json
```

`DATABASE_URL` remains the sole target selector. Print one stage heading before each mutation or verification and a final line containing report path, source archive hash, Git commit, script blob, and PASS. Never print serialized objects or private field values. Do not add resume, dry-run, force, skip-validation, or cleanup flags.

- [ ] **Step 4: Run the complete focused file and the fast gate**

Run through managed hidden processes:

```text
make test-fast ARGS="tests/test_one_time_sqlite_postgres_cutover.py -x -v"
make check-fast
```

Expected: all focused tests and the fast repository gate pass with the Makefile-selected worker count.

- [ ] **Step 5: Commit the executable cutover script**

```text
git add scripts/one_time_sqlite_postgres_cutover.py tests/test_one_time_sqlite_postgres_cutover.py
git commit -m "feat: add one-time SQLite cutover"
```

Record this commit as the candidate rehearsal commit. Do not modify the script after a successful dress rehearsal without restarting both clean rehearsals.

---

### Task 7: Rehearse twice against the supplied production copy

**Files:**
- Private create: `.cache/sqlite-postgres-cutover/rehearsal-1/`
- Private create: `.cache/sqlite-postgres-cutover/rehearsal-2/`
- Private create: `.cache/sqlite-postgres-cutover/nonempty-refusal/`
- Modify only if evidence requires it: script, tests, source contract, and approved design specification.

**Interfaces:**
- Consumes: candidate tracked script commit and supplied production ZIP.
- Produces: two private PASS reports with equal deterministic evidence and one private nonempty-target refusal log.

- [ ] **Step 1: Confirm private paths and source archive identity**

```text
git check-ignore -v .cache/sqlite-postgres-cutover/rehearsal-1/probe
git status --short
Get-FileHash -Algorithm SHA256 -LiteralPath C:\Users\lukas\git\timetracker-prod-copy-2026.08.11.19.14.zip
```

Expected: `.cache/` is ignored; only the known user-owned `.pnpm-store/` may be untracked; archive SHA-256 is `49B2952F71FEC4DF42A7BC3C1142C9554D7DF0E53DD293CF9532126D318B1777`.

- [ ] **Step 2: Create rehearsal database 1 with the PostgreSQL-18 contract**

Run `make ensure-postgres`, then use the PostgreSQL 18 client selected/provisioned by that harness to connect to its `postgres` maintenance database and execute:

```sql
CREATE DATABASE timetracker_cutover_rehearsal_1
  OWNER timetracker
  ENCODING 'UTF8'
  LOCALE_PROVIDER builtin
  BUILTIN_LOCALE 'C.UTF-8'
  TEMPLATE template0;
```

Set an explicit `DATABASE_URL` by replacing only the final database name in the harness URL, for example `postgresql://timetracker@127.0.0.1:1738/timetracker_cutover_rehearsal_1`; clear `TIMETRACKER_MANAGED_DATABASE_URL` so settings do not substitute the managed default. Verify `SELECT count(*) FROM information_schema.tables WHERE table_schema='public';` returns zero before invoking the script.

On Windows, run database/tool commands and the script through managed hidden processes so the final exit status and log are retained.

- [ ] **Step 3: Run rehearsal 1**

```text
uv run --frozen python scripts/one_time_sqlite_postgres_cutover.py --source-archive C:\Users\lukas\git\timetracker-prod-copy-2026.08.11.19.14.zip --workspace .cache\sqlite-postgres-cutover\rehearsal-1 --report .cache\sqlite-postgres-cutover\rehearsal-1\report.json
```

Expected: exit 0 and PASS report. If it fails, preserve the target and private report/log, diagnose the exact mismatch, amend the approved spec if behavior changes, add a failing regression test, implement the smallest correction, and restart Task 7 from a new empty rehearsal-1 database.

- [ ] **Step 4: Prove nonempty-target refusal does not mutate the successful target**

Record table counts and report digest from rehearsal 1. Point a new invocation/workspace at the already migrated rehearsal-1 database.

Expected: nonzero exit naming existing tables before `migrate` or any delete/load operation. Re-run counts/digests and require them unchanged.

- [ ] **Step 5: Create a separately empty rehearsal database 2 and rerun the same Git commit**

Create `timetracker_cutover_rehearsal_2` with the same SQL and PostgreSQL contract, point the explicit URL at that database, and run:

```text
uv run --frozen python scripts/one_time_sqlite_postgres_cutover.py --source-archive C:\Users\lukas\git\timetracker-prod-copy-2026.08.11.19.14.zip --workspace .cache\sqlite-postgres-cutover\rehearsal-2 --report .cache\sqlite-postgres-cutover\rehearsal-2\report.json
```

Expected: exit 0; report Git commit/blob equal rehearsal 1; archive/member hashes, fingerprints, transferred/discarded counts, model/M2M digests, generated results, aggregate results, and schedule identity equal rehearsal 1. Timestamps and target identifiers may differ.

- [ ] **Step 6: Run the full repository gate**

Run `make check` via a managed hidden process and wait for its final log and exit status.

Expected: lint, format, mypy, TypeScript, asset generation checks, migration drift, Vitest, pytest, and E2E all pass with the Makefile's default Windows worker count.

- [ ] **Step 7: Commit only evidence-backed code/spec corrections, if any**

If rehearsal required no changes, do not create an empty commit. If it required changes, commit each regression and restart both rehearsals from new empty databases; the new HEAD becomes the only candidate final-cutover commit.

---

### Task 8: Consolidate GitHub issues around the proven one-time cutover

**Files:**
- No repository file changes unless issue links in the spec require correction.

**Interfaces:**
- Consumes: approved design and two successful rehearsal reports.
- Produces: one accurate cutover issue (#621), superseded issues closed as not planned, and one post-cutover cleanup issue (#628).

- [ ] **Step 1: Rewrite #621 around the proven imperative procedure**

Set #621's outcome to the tracked script, exact production fingerprint, two rehearsals, final frozen-snapshot execution, and reconciliation evidence. Link the committed design and implementation plan. State that the script is temporary and removed by #628.

- [ ] **Step 2: Close superseded transfer-tool issues**

Close #622, #623, #624, #625, #626, and #810 as `not_planned` with one concise comment: superseded by the approved one-time cutover in #621; link #621 and the design.

- [ ] **Step 3: Audit and close #627 if its runtime switch is already complete**

Evidence required before closure:

```text
timetracker/database.py rejects non-PostgreSQL DATABASE_URL values
timetracker/settings.py obtains default DATABASES from required_database_settings()
deployment/CI/dev paths use PostgreSQL 18
```

If all hold, close #627 as completed by the already-merged PostgreSQL-only runtime work. If any does not hold, keep #627 open and name the exact remaining runtime action; do not absorb it into the data copy script.

- [ ] **Step 4: Rescope #628 and absorb #809**

#628 becomes the single post-cutover cleanup issue. Its acceptance includes removal of:

- `scripts/one_time_sqlite_postgres_cutover.py`;
- `scripts/sqlite_postgres_source_contract.json`;
- `tests/test_one_time_sqlite_postgres_cutover.py`;
- SQLite runtime/expression compatibility no longer needed by PostgreSQL; and
- the baseline migration's `replaces` list owned by #809.

Close #809 as `not_planned`, superseded by #628.

- [ ] **Step 5: Update #600's checklist**

Replace the obsolete #621–#628/#809/#810 sequence with #621 followed by #628, while leaving later ownership, UUID, and catalog groups unchanged.

---

### Task 9: Execute the final offline cutover

**Files:**
- Private create: `.cache/sqlite-postgres-cutover/final/`
- No tracked file changes during execution.

**Interfaces:**
- Consumes: final frozen SQLite ZIP, exact successful rehearsal Git commit, operator-created empty PostgreSQL database.
- Produces: private final PASS report and a running PostgreSQL-backed production deployment.

- [ ] **Step 1: Freeze SQLite production**

Stop the web application and Django-Q worker. Confirm no process has the SQLite database open for writes. Archive `db.sqlite3` together with existing `db.sqlite3-wal`, `db.sqlite3-shm`, or `db.sqlite3-journal` sidecars. Do not checkpoint, vacuum, migrate, or otherwise alter the source.

- [ ] **Step 2: Confirm the final source still satisfies the rehearsed contract**

Record archive/member SHA-256 hashes. Check out the successful rehearsal commit. Run the script only far enough to perform its normal source validation as part of the full invocation; if migration/schema fingerprints or required-empty tables differ, stop and return to design review. Do not add a bypass.

- [ ] **Step 3: Create the final empty PostgreSQL database**

Create a new database satisfying PostgreSQL 18, UTF-8, builtin locale provider, and `C.UTF-8`. Set production `DATABASE_URL` to it for the cutover process. Independently verify it contains zero tables.

- [ ] **Step 4: Run the tracked dress-rehearsed script unchanged**

```text
uv run --frozen python scripts/one_time_sqlite_postgres_cutover.py --source-archive C:\path\to\final-snapshot.zip --workspace .cache\sqlite-postgres-cutover\final --report .cache\sqlite-postgres-cutover\final\report.json
```

Expected: exit 0; final report records the exact rehearsal commit/blob and every reconciliation/smoke/schedule check passes.

- [ ] **Step 5: Run private-mode production smoke checks**

Start the app and Django-Q against PostgreSQL without reopening public writes. Verify login, Game list/detail, Session list, Purchase list/detail, settings, filters, all-time statistics, and one read-only API request. Confirm the recreated `Update converted prices` schedule is present exactly once and Django-Q starts without replaying old task history.

- [ ] **Step 6: Reopen writes and record the irreversible boundary**

Reopen Timetracker, record the timestamp, deployed Git commit, PostgreSQL database identity, final source archive SHA-256, and final report path in the private operator record. From this point PostgreSQL is the sole source of truth and defects are fixed forward.

- [ ] **Step 7: Preserve rollback artifacts offline**

Retain the untouched final SQLite archive and old deployable release offline until deliberately archived. Do not retain the serialized fixture longer than needed for cutover investigation.

- [ ] **Step 8: Close #621 and unblock #628**

Post a non-private summary containing only commit IDs, database versions, model/link counts, hash identifiers, PASS status, and cutover time. Close #621. Begin #628 only after this closure; do not remove the tracked script earlier.

---

## Plan Completion Gate

The plan is complete only when:

- every focused test and `make check` passes with normal worker configuration;
- two same-commit rehearsals against separate empty PostgreSQL targets produce equal deterministic evidence;
- a nonempty target is refused without mutation;
- the final frozen snapshot matches the exact source contract and passes unchanged code;
- production reopens on PostgreSQL and the irreversible boundary is recorded;
- private artifacts remain ignored/untracked; and
- #621 is closed, superseded issues are consolidated, and #628 owns deletion of the temporary tracked machinery.
