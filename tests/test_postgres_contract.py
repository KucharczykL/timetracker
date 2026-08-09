from dataclasses import dataclass

import pytest

from timetracker.postgres_contract import (
    CATALOG_QUERY,
    PostgresContract,
    validate_postgres_collation_contract,
)


@dataclass
class RecordingCursor:
    row: tuple[object, ...] | None
    queries: list[str]

    def execute(self, query: str) -> None:
        self.queries.append(query)

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row


@dataclass
class RecordingConnection:
    row: tuple[object, ...] | None
    queries: list[str]

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self.row, self.queries)


def test_validate_postgres_collation_contract_returns_matching_snapshot():
    connection = RecordingConnection((170004, "UTF8", "b", "C.UTF-8"), [])

    assert validate_postgres_collation_contract(connection) == PostgresContract(
        170004, "UTF8", "b", "C.UTF-8"
    )
    assert connection.queries == [CATALOG_QUERY]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ((160010, "UTF8", "b", "C.UTF-8"), "major version 17, got 16"),
        ((170004, "LATIN1", "b", "C.UTF-8"), "encoding UTF8, got LATIN1"),
        ((170004, "UTF8", "c", "C.UTF-8"), "provider builtin, got libc"),
        ((170004, "UTF8", "i", "C.UTF-8"), "provider builtin, got icu"),
        ((170004, "UTF8", "b", "C"), "builtin locale C.UTF-8, got C"),
    ],
)
def test_validate_postgres_collation_contract_rejects_mismatches(
    row: tuple[object, ...], message: str
):
    with pytest.raises(ValueError, match=message):
        validate_postgres_collation_contract(RecordingConnection(row, []))


@pytest.mark.parametrize(
    "row",
    [
        None,
        ("170004", "UTF8", "b"),
        ("no", "UTF8", "b", "C.UTF-8"),
        (170004, None, "b", "C.UTF-8"),
        (170004, "UTF8", "x", "C.UTF-8"),
    ],
)
def test_validate_postgres_collation_contract_rejects_malformed_catalog_rows(
    row: tuple[object, ...] | None,
):
    with pytest.raises(ValueError, match="PostgreSQL collation contract"):
        validate_postgres_collation_contract(RecordingConnection(row, []))
