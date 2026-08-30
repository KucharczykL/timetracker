"""PostgreSQL database configuration and connection validation."""

import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from urllib.parse import parse_qsl, unquote, urlsplit

from django.core.exceptions import ImproperlyConfigured

from timetracker.config import config
from timetracker.postgres_contract import (
    PostgresContractViolation,
    observe_valid_postgres_connection,
)

CLOCK_SKEW_TOLERANCE_MS = 1_000
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClockSkewMeasurement:
    estimated_skew_ms: float
    round_trip_ms: float
    outside_tolerance: bool


def measure_clock_skew(
    database_time_ms: float,
    started_wall_ms: float,
    finished_wall_ms: float,
    round_trip_ms: float,
) -> ClockSkewMeasurement:
    """Compare a database timestamp with the wall-clock interval around its query."""
    lower = min(started_wall_ms, finished_wall_ms) - CLOCK_SKEW_TOLERANCE_MS
    upper = max(started_wall_ms, finished_wall_ms) + CLOCK_SKEW_TOLERANCE_MS
    midpoint = (started_wall_ms + finished_wall_ms) / 2
    return ClockSkewMeasurement(
        estimated_skew_ms=database_time_ms - midpoint,
        round_trip_ms=round_trip_ms,
        outside_tolerance=not lower <= database_time_ms <= upper,
    )


class ClockSkewWarningState:
    def __init__(self) -> None:
        self._active = False
        self._lock = Lock()

    def observe(self, is_skewed: bool) -> bool:
        """Return whether a new skew episode should emit a warning."""
        with self._lock:
            if not is_skewed:
                self._active = False
                return False
            if self._active:
                return False
            self._active = True
            return True


_clock_skew_warnings = ClockSkewWarningState()


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
    settings = database_settings_from_url(url)
    #: Only iterator() reads it, so only Django's.
    #: Beside ENGINE: OPTIONS holds driver arguments.
    settings["DISABLE_SERVER_SIDE_CURSORS"] = config(
        "DISABLE_SERVER_SIDE_CURSORS", default=False, cast=bool
    )
    return settings


def validate_default_connection(
    *, sender: object, connection: object, **_: object
) -> None:
    """Reject an opened default connection outside the supported PostgreSQL contract."""
    if getattr(connection, "alias", None) != "default":
        return

    started_wall_ms = time.time_ns() / 1_000_000
    started_monotonic_ns = time.monotonic_ns()
    try:
        observation = observe_valid_postgres_connection(connection)  # type: ignore[arg-type]
    except PostgresContractViolation as exc:
        raise ImproperlyConfigured(
            f"PostgreSQL database contract violation: {exc}"
        ) from exc
    finished_wall_ms = time.time_ns() / 1_000_000
    round_trip_ms = (time.monotonic_ns() - started_monotonic_ns) / 1_000_000

    measurement = measure_clock_skew(
        observation.database_time_ms,
        started_wall_ms,
        finished_wall_ms,
        round_trip_ms,
    )
    if _clock_skew_warnings.observe(measurement.outside_tolerance):
        logger.warning(
            "PostgreSQL clock skew exceeds tolerance: "
            "estimated_skew_ms=%+.1f round_trip_ms=%.1f tolerance_ms=%d",
            measurement.estimated_skew_ms,
            measurement.round_trip_ms,
            CLOCK_SKEW_TOLERANCE_MS,
        )
