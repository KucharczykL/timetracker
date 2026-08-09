# PG-05: PostgreSQL Collation Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable read-only validator that accepts only PostgreSQL 17 databases using UTF8, the `builtin` locale provider, and `C.UTF-8`.

**Architecture:** A small Django- and driver-independent module queries the active connection's database catalog and validates one typed snapshot. Recording DB-API fakes cover it without PostgreSQL; #613 later owns live startup wiring.

**Tech Stack:** Python 3.14, typing protocols, pytest, Make, PostgreSQL 17 catalogs.

## Global Constraints

- Related issue: https://github.com/KucharczykL/timetracker/issues/607.
- Require major `17`, encoding `UTF8`, `datlocprovider = 'b'`, and `datlocale = 'C.UTF-8'`; reject libc and ICU, including libc `C.UTF-8`.
- Query the selected database with `current_database()`, never a configuration-supplied database name.
- Do not add `DATABASE_URL`, a driver, server harness, provisioning, a migration, data change, or mutation.
- #613 owns startup wiring; #614 development provisioning; #616 CI; #617 Compose; #618 backup/restore verification.
- Completion requires `make check`.

---

## File structure

- Create: `timetracker/postgres_contract.py` — DB-API protocols, snapshot, exception, catalog query, and validator.
- Create: `tests/test_postgres_contract.py` — recording fakes and contract coverage.
- Inspect only: `timetracker/settings.py`, `timetracker/config.py`, `pyproject.toml` — ensure no runtime or driver work leaks in.

### Task 1: Specify the contract with failing tests

**Files:**

- Create: `tests/test_postgres_contract.py`
- Create: `timetracker/postgres_contract.py`

**Interfaces:**

- Consumes: `PostgresConnection.cursor() -> PostgresCursor`; cursor implements `execute(query: str) -> object` and `fetchone() -> tuple[object, ...] | None`.
- Produces: `validate_postgres_collation_contract(connection: PostgresConnection) -> PostgresContract` and `PostgresContractViolation(ValueError)`.

- [ ] **Step 1: Write the matching-contract test and recording fakes**

```python
from dataclasses import dataclass

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
```

- [ ] **Step 2: Run it to verify the module is absent**

Run: `make test ARGS="tests/test_postgres_contract.py::test_validate_postgres_collation_contract_returns_matching_snapshot -v"`

Expected: collection fails because `timetracker.postgres_contract` does not exist.

- [ ] **Step 3: Add precise mismatch and malformed-row tests**

```python
import pytest


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
def test_validator_rejects_contract_mismatches(row, message):
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
def test_validator_rejects_malformed_catalog_rows(row):
    with pytest.raises(ValueError, match="PostgreSQL collation contract"):
        validate_postgres_collation_contract(RecordingConnection(row, []))
```

- [ ] **Step 4: Run the failure suite**

Run: `make test ARGS="tests/test_postgres_contract.py -v"`

Expected: collection fails; no real server, mutation, or driver is used.

### Task 2: Implement the driver-independent validator

**Files:**

- Create: `timetracker/postgres_contract.py`
- Test: `tests/test_postgres_contract.py`

**Interfaces:**

- Consumes: the Task 1 fake connection; #613/#614/#617/#618 may later use compatible real connections.
- Produces: `CATALOG_QUERY`, `PostgresContract`, `PostgresContractViolation`, and the validator function.

- [ ] **Step 1: Define constants and types**

```python
from dataclasses import dataclass
from typing import Protocol

REQUIRED_POSTGRES_MAJOR = 17
REQUIRED_ENCODING = "UTF8"
REQUIRED_LOCALE_PROVIDER = "b"
REQUIRED_BUILTIN_LOCALE = "C.UTF-8"


class PostgresCursor(Protocol):
    def execute(self, query: str) -> object: ...
    def fetchone(self) -> tuple[object, ...] | None: ...


class PostgresConnection(Protocol):
    def cursor(self) -> PostgresCursor: ...


@dataclass(frozen=True)
class PostgresContract:
    server_version_num: int
    encoding: str
    locale_provider: str
    locale: str


class PostgresContractViolation(ValueError):
    pass
```

- [ ] **Step 2: Query one catalog row and parse it defensively**

```python
CATALOG_QUERY = """
SELECT
    current_setting('server_version_num')::integer,
    pg_encoding_to_char(database.encoding),
    database.datlocprovider,
    database.datlocale
FROM pg_database AS database
WHERE database.datname = current_database()
""".strip()


def _read_contract(cursor: PostgresCursor) -> PostgresContract:
    cursor.execute(CATALOG_QUERY)
    row = cursor.fetchone()
    if not isinstance(row, tuple) or len(row) != 4:
        raise PostgresContractViolation(
            "PostgreSQL collation contract query returned an invalid row."
        )
    server_version_num, encoding, locale_provider, locale = row
    if not isinstance(server_version_num, int):
        raise PostgresContractViolation(
            "PostgreSQL collation contract returned a non-integer server version."
        )
    if not all(isinstance(value, str) for value in (encoding, locale_provider, locale)):
        raise PostgresContractViolation(
            "PostgreSQL collation contract returned non-text database metadata."
        )
    return PostgresContract(server_version_num, encoding, locale_provider, locale)
```

- [ ] **Step 3: Implement exact validation**

```python
_PROVIDER_LABELS = {"b": "builtin", "c": "libc", "i": "icu"}


def validate_postgres_collation_contract(
    connection: PostgresConnection,
) -> PostgresContract:
    contract = _read_contract(connection.cursor())
    actual_major = contract.server_version_num // 10_000
    if actual_major != REQUIRED_POSTGRES_MAJOR:
        raise PostgresContractViolation(
            f"PostgreSQL collation contract requires major version "
            f"{REQUIRED_POSTGRES_MAJOR}, got {actual_major} "
            f"(server_version_num={contract.server_version_num})."
        )
    if contract.encoding != REQUIRED_ENCODING:
        raise PostgresContractViolation(
            f"PostgreSQL collation contract requires encoding {REQUIRED_ENCODING}, "
            f"got {contract.encoding}."
        )
    if contract.locale_provider != REQUIRED_LOCALE_PROVIDER:
        provider = _PROVIDER_LABELS.get(
            contract.locale_provider, repr(contract.locale_provider)
        )
        raise PostgresContractViolation(
            f"PostgreSQL collation contract requires provider builtin, got {provider}."
        )
    if contract.locale != REQUIRED_BUILTIN_LOCALE:
        raise PostgresContractViolation(
            f"PostgreSQL collation contract requires builtin locale "
            f"{REQUIRED_BUILTIN_LOCALE}, got {contract.locale}."
        )
    return contract
```

- [ ] **Step 4: Run focused verification and commit**

Run: `make test ARGS="tests/test_postgres_contract.py -v"`

Run: `make lint`

Run: `make typecheck`

Run: `git add timetracker/postgres_contract.py tests/test_postgres_contract.py`

Run: `git commit -m "feat: validate PostgreSQL collation contract"`

Expected: tests, lint, and type checks pass; the commit contains only the module and its tests. If the Make target names differ, use the equivalent targets already declared in `Makefile`.

### Task 3: Verify scope and repository gate

**Files:**

- Inspect: `timetracker/postgres_contract.py`
- Inspect: `tests/test_postgres_contract.py`

**Interfaces:**

- Consumes: Task 2 commit.
- Produces: an issue-ready implementation that #613 can import without adopting PostgreSQL runtime behavior here.

- [ ] **Step 1: Review the implementation boundary**

Run: `git diff HEAD~1 -- timetracker/postgres_contract.py tests/test_postgres_contract.py`

Run: `git diff --check HEAD~1`

Run: `rg -n "DATABASE_URL|psycopg|CREATE DATABASE|migrations\." timetracker/postgres_contract.py tests/test_postgres_contract.py`

Expected: exactly one catalog `SELECT`, no commit or Django-settings import, and no matches from `rg`.

- [ ] **Step 2: Run focused and full verification**

Run: `make test ARGS="tests/test_postgres_contract.py -v"`

Run: `make check`

Expected: both pass; focused tests cover the exact good tuple, all four wrong contract properties, libc `C.UTF-8`, ICU, and malformed catalog rows.

- [ ] **Step 3: Confirm handoff metadata**

Run: `git status --short`

Run: `git log -1 --oneline`

Expected: clean worktree and the Task 2 commit at `HEAD`. The pull request must link the issue, say `Closes #607`, and state that #613 owns startup wiring.

## Spec coverage review

- Tasks 1–2 provide the standalone tested enforcement unit and exact catalog interface.
- Contract checks reject OS libc and ICU even if their locale spelling resembles `C.UTF-8`.
- Task 3 enforces the no-runtime/no-provisioning/no-data boundary and `make check` gate.
