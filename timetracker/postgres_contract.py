"""Read-only validation of Timetracker's PostgreSQL database contract."""

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
    """The connected database does not meet the required PostgreSQL contract."""


CATALOG_QUERY = """
SELECT
    current_setting('server_version_num')::integer,
    pg_encoding_to_char(database.encoding),
    database.datlocprovider,
    database.datlocale
FROM pg_database AS database
WHERE database.datname = current_database()
""".strip()

_PROVIDER_LABELS = {"b": "builtin", "c": "libc", "i": "icu"}


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
    if (
        not isinstance(encoding, str)
        or not isinstance(locale_provider, str)
        or not isinstance(locale, str)
    ):
        raise PostgresContractViolation(
            "PostgreSQL collation contract returned non-text database metadata."
        )
    return PostgresContract(server_version_num, encoding, locale_provider, locale)


def validate_postgres_collation_contract(
    connection: PostgresConnection,
) -> PostgresContract:
    """Return the matching connected-database contract or raise a clear error."""
    contract = _read_contract(connection.cursor())
    actual_major = contract.server_version_num // 10_000
    if actual_major != REQUIRED_POSTGRES_MAJOR:
        raise PostgresContractViolation(
            "PostgreSQL collation contract requires major version "
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
            "PostgreSQL collation contract requires builtin locale "
            f"{REQUIRED_BUILTIN_LOCALE}, got {contract.locale}."
        )
    return contract
