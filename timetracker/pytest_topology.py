"""PostgreSQL test-database namespacing for pytest-xdist."""

from __future__ import annotations

import hashlib

import pytest
from django.conf import settings


def xdist_database_name(base_name: str, run_uid: str, worker_id: str) -> str:
    """Return a bounded ASCII PostgreSQL database name for one xdist worker."""
    base_hash = hashlib.sha256(base_name.encode()).hexdigest()[:12]
    run_hash = hashlib.sha256(run_uid.encode()).hexdigest()[:32]
    worker_hash = hashlib.sha256(worker_id.encode()).hexdigest()[:8]
    return f"test_{base_hash}_{run_hash}_{worker_hash}"


@pytest.fixture(scope="session")
def django_db_modify_db_settings_xdist_suffix(
    request: pytest.FixtureRequest,
    django_db_modify_db_settings_tox_suffix: None,  # noqa: ARG001
    testrun_uid: str,
    worker_id: str,
) -> None:
    """Give each xdist run and worker a distinct PostgreSQL test database."""
    if not hasattr(request.config, "workerinput"):
        return

    for database in settings.DATABASES.values():
        if database["ENGINE"] == "django.db.backends.sqlite3":
            continue
        test_name = database.setdefault("TEST", {}).get("NAME")
        if not test_name:
            test_name = f"test_{database['NAME']}"
        if test_name != ":memory:":
            database["TEST"]["NAME"] = xdist_database_name(
                test_name, testrun_uid, worker_id
            )
