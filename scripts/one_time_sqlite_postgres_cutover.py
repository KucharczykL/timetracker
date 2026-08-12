from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import subprocess
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from django.db import connections
from django.db.migrations.loader import MigrationLoader

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper


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


SOURCE_ALIAS = "sqlite_source"
SQUASH_MIGRATION = (
    "games",
    "0001_squashed_0036_alter_playevent_days_to_finish",
)
SNAPSHOT_MEMBERS = {
    "db.sqlite3",
    "db.sqlite3-wal",
    "db.sqlite3-shm",
    "db.sqlite3-journal",
}
DURABLE_SNAPSHOT_MEMBERS = {
    "db.sqlite3",
    "db.sqlite3-wal",
    "db.sqlite3-journal",
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_git_ignored_workspace(workspace: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", str(workspace.resolve())],
        cwd=repository,
        check=False,
    )
    if result.returncode != 0:
        raise CutoverError(f"workspace must be Git-ignored: {workspace}")


def _safe_snapshot_destination(workspace: Path, member: zipfile.ZipInfo) -> Path:
    member_path = Path(member.filename)
    if (
        member.is_dir()
        or member_path.is_absolute()
        or len(member_path.parts) != 1
        or member_path.parts[0] in {".", ".."}
    ):
        raise CutoverError(f"unsafe archive member: {member.filename}")
    destination = (workspace / member_path).resolve()
    if not destination.is_relative_to(workspace.resolve()):
        raise CutoverError(f"unsafe archive member: {member.filename}")
    return destination


def extract_snapshot(archive: Path, workspace: Path) -> SnapshotFiles:
    archive = archive.resolve()
    workspace = workspace.resolve()
    require_git_ignored_workspace(workspace)
    if workspace.exists() and any(workspace.iterdir()):
        raise CutoverError(f"workspace must be empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)

    extracted: dict[str, Path] = {}
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            destination = _safe_snapshot_destination(workspace, member)
            name = member.filename
            if name not in SNAPSHOT_MEMBERS:
                raise CutoverError(f"unexpected archive member: {name}")
            if name in extracted:
                raise CutoverError(f"duplicate archive member: {name}")
            with (
                source.open(member) as input_file,
                destination.open("xb") as output_file,
            ):
                shutil.copyfileobj(input_file, output_file)
            extracted[name] = destination

    if "db.sqlite3" not in extracted:
        raise CutoverError("archive is missing db.sqlite3")
    durable_hashes = {
        name: sha256_file(path)
        for name, path in extracted.items()
        if name in DURABLE_SNAPSHOT_MEMBERS
    }
    return SnapshotFiles(
        archive=archive,
        database=extracted["db.sqlite3"],
        wal=extracted.get("db.sqlite3-wal"),
        shm=extracted.get("db.sqlite3-shm"),
        journal=extracted.get("db.sqlite3-journal"),
        archive_sha256=sha256_file(archive),
        durable_member_sha256=durable_hashes,
    )


def sqlite_read_only_uri(database: Path) -> str:
    path = quote(database.resolve().as_posix(), safe="/:")
    return f"file:{path}?mode=ro"


def configure_source_alias(database: Path) -> BaseDatabaseWrapper:
    connections.databases[SOURCE_ALIAS] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": sqlite_read_only_uri(database),
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {},
        "TIME_ZONE": None,
        "USER": "",
        "PASSWORD": "",
        "HOST": "",
        "PORT": "",
        "TEST": {
            "CHARSET": None,
            "COLLATION": None,
            "MIGRATE": True,
            "MIRROR": None,
            "NAME": None,
        },
    }
    return connections[SOURCE_ALIAS]


def remove_source_alias(connection: BaseDatabaseWrapper) -> None:
    connection.close()
    del connections[SOURCE_ALIAS]
    del connections.databases[SOURCE_ALIAS]


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


def source_structure(connection: BaseDatabaseWrapper) -> SourceStructure:
    with connection.cursor() as cursor:
        cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name")
        migrations = tuple(tuple(row) for row in cursor.fetchall())
        tables = sorted(connection.introspection.table_names(cursor))
        table_columns: dict[str, tuple[str, ...]] = {}
        for table in tables:
            cursor.execute(f"PRAGMA table_info({connection.ops.quote_name(table)})")
            table_columns[table] = tuple(str(row[1]) for row in cursor.fetchall())
    return SourceStructure(migrations=migrations, table_columns=table_columns)


def source_table_counts(
    connection: BaseDatabaseWrapper, tables: set[str]
) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in sorted(tables):
            cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table)}")
            row = cursor.fetchone()
            if row is None:
                raise CutoverError(f"could not count source table: {table}")
            counts[table] = int(row[0])
    return counts


def validate_source(
    connection: BaseDatabaseWrapper, contract: SourceContract
) -> SourceEvidence:
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA quick_check")
        row = cursor.fetchone()
    quick_check = "" if row is None else str(row[0])
    if quick_check != "ok":
        raise CutoverError(f"SQLite PRAGMA quick_check failed: {quick_check}")

    loader = MigrationLoader(connection)
    loader.check_consistent_history(connection)
    effective_squash_applied = SQUASH_MIGRATION in loader.applied_migrations
    if not effective_squash_applied:
        raise CutoverError(
            "source does not have the expected squashed migration effectively applied"
        )

    structure = source_structure(connection)
    validate_source_structure(structure, contract)
    return SourceEvidence(
        structure=structure,
        table_counts=source_table_counts(connection, set(structure.table_columns)),
        quick_check=quick_check,
        effective_squash_applied=effective_squash_applied,
    )


def _validate_snapshot_unchanged(snapshot: SnapshotFiles) -> None:
    mismatches: list[str] = []
    if sha256_file(snapshot.archive) != snapshot.archive_sha256:
        mismatches.append(f"{snapshot.archive.name} changed")
    paths = {
        "db.sqlite3": snapshot.database,
        "db.sqlite3-wal": snapshot.wal,
        "db.sqlite3-journal": snapshot.journal,
    }
    for name, expected_hash in snapshot.durable_member_sha256.items():
        path = paths[name]
        if path is None or not path.exists() or sha256_file(path) != expected_hash:
            mismatches.append(f"{name} changed")
    if mismatches:
        raise CutoverError("durable source snapshot changed: " + ", ".join(mismatches))


@contextmanager
def open_validated_source(
    archive: Path, workspace: Path, contract: SourceContract
) -> Iterator[PreparedSource]:
    snapshot = extract_snapshot(archive, workspace)
    connection = configure_source_alias(snapshot.database)
    try:
        evidence = validate_source(connection, contract)
        yield PreparedSource(
            snapshot=snapshot,
            evidence=evidence,
            connection=connection,
        )
    finally:
        remove_source_alias(connection)
        _validate_snapshot_unchanged(snapshot)


def _migration_name(migration: tuple[str, str]) -> str:
    return ".".join(migration)


def validate_source_structure(
    actual: SourceStructure, expected: SourceContract
) -> None:
    mismatches: list[str] = []

    actual_migrations = set(actual.migrations)
    expected_migrations = set(expected.migrations)
    added_migrations = sorted(actual_migrations - expected_migrations)
    missing_migrations = sorted(expected_migrations - actual_migrations)
    if added_migrations:
        mismatches.append(
            "unexpected migrations: "
            + ", ".join(_migration_name(item) for item in added_migrations)
        )
    if missing_migrations:
        mismatches.append(
            "missing migrations: "
            + ", ".join(_migration_name(item) for item in missing_migrations)
        )

    actual_tables = set(actual.table_columns)
    expected_tables = set(expected.table_columns)
    disposition_tables = set(expected.table_dispositions)
    added_tables = sorted(actual_tables - expected_tables)
    missing_tables = sorted(expected_tables - actual_tables)
    if added_tables:
        mismatches.append("unexpected tables: " + ", ".join(added_tables))
    if missing_tables:
        mismatches.append("missing tables: " + ", ".join(missing_tables))

    missing_dispositions = sorted(actual_tables - disposition_tables)
    stale_dispositions = sorted(disposition_tables - actual_tables)
    if missing_dispositions:
        mismatches.append(
            "tables without dispositions: " + ", ".join(missing_dispositions)
        )
    if stale_dispositions:
        mismatches.append(
            "dispositions without source tables: " + ", ".join(stale_dispositions)
        )

    for table in sorted(actual_tables & expected_tables):
        actual_columns = actual.table_columns[table]
        expected_columns = expected.table_columns[table]
        if actual_columns == expected_columns:
            continue
        added_columns = sorted(set(actual_columns) - set(expected_columns))
        missing_columns = sorted(set(expected_columns) - set(actual_columns))
        details = [
            f"expected ordered columns {expected_columns!r}",
            f"found {actual_columns!r}",
        ]
        if added_columns:
            details.append("unexpected " + ", ".join(added_columns))
        if missing_columns:
            details.append("missing " + ", ".join(missing_columns))
        mismatches.append(f"table {table}: " + "; ".join(details))

    if mismatches:
        raise CutoverError("source structure mismatch:\n- " + "\n- ".join(mismatches))
