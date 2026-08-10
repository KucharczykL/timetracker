"""Regression coverage for pytest-django's PostgreSQL xdist database topology."""

import json
import os
import uuid
from pathlib import Path

pytest_plugins = ("pytester",)


def test_two_xdist_workers_receive_distinct_postgresql_test_databases(
    monkeypatch, pytester, tmp_path
):
    """Each xdist worker must use a disposable PostgreSQL database of its own."""
    from timetracker.database import database_settings_from_url

    configured_name = database_settings_from_url(os.environ["DATABASE_URL"])["NAME"]
    test_name = f"test_pg_xdist_probe_{uuid.uuid4().hex}"
    report_path = tmp_path / "workers.jsonl"
    monkeypatch.setenv("PG_XDIST_CONFIGURED_NAME", str(configured_name))
    monkeypatch.setenv("PG_XDIST_REPORT", str(report_path))
    monkeypatch.setenv("PG_XDIST_TEST_NAME", test_name)
    pytester.makepyfile(
        settings="""
import os

from timetracker.database import database_settings_from_url

SECRET_KEY = "pytest-xdist-topology"
INSTALLED_APPS = ["django.contrib.contenttypes"]
database = database_settings_from_url(os.environ["DATABASE_URL"])
database["TEST"] = {"NAME": os.environ["PG_XDIST_TEST_NAME"]}
DATABASES = {"default": database}
""",
        conftest="""
import os


def pytest_configure(config):
    worker = getattr(config, "workerinput", {}).get("workerid", "controller")
    os.environ["PYTEST_XDIST_WORKER"] = worker
""",
        test_probe="""
import json
import os
from pathlib import Path

import pytest
from django.db import connection


@pytest.mark.django_db
def test_records_live_worker_database():
    record = {
        "worker_id": os.environ["PYTEST_XDIST_WORKER"],
        "vendor": connection.vendor,
        "configured_name": os.environ["PG_XDIST_CONFIGURED_NAME"],
        "live_name": connection.settings_dict["NAME"],
    }
    with Path(os.environ["PG_XDIST_REPORT"]).open("a") as report:
        report.write(json.dumps(record) + "\\n")
""",
    )

    result = pytester.runpytest_subprocess("-n", "2", "--dist=each", "--ds=settings")

    result.assert_outcomes(passed=2)
    records = [json.loads(line) for line in report_path.read_text().splitlines()]
    assert {record["worker_id"] for record in records} == {"gw0", "gw1"}
    assert {record["vendor"] for record in records} == {"postgresql"}
    assert {record["live_name"] for record in records} == {
        f"{test_name}_gw0",
        f"{test_name}_gw1",
    }
    assert {record["configured_name"] for record in records} == {configured_name}
    assert all(record["live_name"] != configured_name for record in records)
