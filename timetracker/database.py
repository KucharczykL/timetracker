"""PostgreSQL database configuration and connection validation."""

import os
from collections.abc import Mapping
from urllib.parse import parse_qsl, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured

from timetracker.config import config
from timetracker.postgres_contract import (
    PostgresContractViolation,
    validate_postgres_collation_contract,
)


def _invalid_database_url(detail: str) -> ImproperlyConfigured:
    return ImproperlyConfigured(
        "DATABASE_URL must be a PostgreSQL URL such as "
        "postgresql://user:password@127.0.0.1:5432/timetracker "
        f"({detail})."
    )


def database_settings_from_url(url: str) -> dict[str, object]:
    """Translate one PostgreSQL URL into Django's database settings mapping."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise _invalid_database_url(str(exc)) from exc

    if parsed.scheme not in {"postgres", "postgresql"}:
        raise _invalid_database_url("the scheme must be postgres or postgresql")
    if not parsed.hostname:
        raise _invalid_database_url("a host is required")
    if parsed.fragment:
        raise _invalid_database_url("fragments are not supported")
    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name or "/" in database_name:
        raise _invalid_database_url("exactly one database name is required")

    options: Mapping[str, str] = dict(parse_qsl(parsed.query, keep_blank_values=True))
    settings: dict[str, object] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": database_name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname,
        "PORT": port or "",
        "OPTIONS": dict(options),
    }
    return settings


def required_database_settings() -> dict[str, object]:
    """Read the required deployment database URL with a useful boot error."""
    try:
        if os.environ.get("TIMETRACKER_MANAGED_DATABASE_URL") == "1":
            url = config(
                "DATABASE_URL", default=None, include_environment=False
            ) or config("DATABASE_URL", allow_file=True)
        else:
            url = config("DATABASE_URL", allow_file=True)
    except ImproperlyConfigured as exc:
        raise ImproperlyConfigured(
            "DATABASE_URL is required. Run make init (or make ensure-postgres) "
            "for the disposable development database, or set a PostgreSQL URL."
        ) from exc
    return database_settings_from_url(url)


def validate_default_connection(
    *, sender: object, connection: object, **_: object
) -> None:
    """Reject an opened default connection outside the supported PostgreSQL contract."""
    if getattr(connection, "alias", None) != "default":
        return
    try:
        validate_postgres_collation_contract(connection)  # type: ignore[arg-type]
    except PostgresContractViolation as exc:
        raise ImproperlyConfigured(
            f"PostgreSQL database contract violation: {exc}"
        ) from exc
