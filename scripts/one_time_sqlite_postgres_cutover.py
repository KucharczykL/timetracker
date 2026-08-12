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
