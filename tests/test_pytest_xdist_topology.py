"""Regression coverage for PostgreSQL pytest-xdist database isolation."""

import json
import os
from pathlib import Path

import pytest

from timetracker.pytest_topology import xdist_database_name

pytest_plugins = ("pytester",)


@pytest.mark.parametrize(
    ("base_name", "run_uid", "worker_id"),
    [
        ("test_timetracker", "run-a", "gw0"),
        ("test_timetracker", "run-a", "gw1"),
        ("test_" + "ž" * 80, "run-b", "gw0"),
    ],
)
def test_database_name_is_bounded_ascii(
    base_name: str, run_uid: str, worker_id: str
):
    name = xdist_database_name(base_name, run_uid, worker_id)

    assert name.startswith("test_")
    assert name.isascii()
    assert len(name) == 59
    assert len(name.encode()) <= 63


def test_database_name_changes_for_each_namespace_component():
    name = xdist_database_name("test_timetracker", "run-a", "gw0")

    assert name == xdist_database_name("test_timetracker", "run-a", "gw0")
    assert name != xdist_database_name("test_other", "run-a", "gw0")
    assert name != xdist_database_name("test_timetracker", "run-b", "gw0")
    assert name != xdist_database_name("test_timetracker", "run-a", "gw1")


def test_two_xdist_workers_receive_distinct_postgresql_test_databases(
    monkeypatch, pytester, tmp_path
):
    """The actual plugin must give xdist workers one database each."""
    from timetracker.database import database_settings_from_url

    configured_name = database_settings_from_url(os.environ["DATABASE_URL"])["NAME"]
    report_dir = tmp_path / "workers"
    report_dir.mkdir()
    monkeypatch.setenv("PG_XDIST_CONFIGURED_NAME", str(configured_name))
    monkeypatch.setenv("PG_XDIST_REPORT_DIR", str(report_dir))
    pytester.makepyfile(
        settings="""
import os

from timetracker.database import database_settings_from_url

SECRET_KEY = "pytest-xdist-topology"
INSTALLED_APPS = ["django.contrib.contenttypes"]
DATABASES = {"default": database_settings_from_url(os.environ["DATABASE_URL"])}
""",
        conftest='pytest_plugins = ("timetracker.pytest_topology",)',
        test_probe="""
import json
import os
from pathlib import Path

import pytest
from django.db import connection


@pytest.mark.django_db
def test_records_live_worker_database(worker_id, testrun_uid):
    record = {
        "worker_id": worker_id,
        "run_uid": testrun_uid,
        "vendor": connection.vendor,
        "configured_name": os.environ["PG_XDIST_CONFIGURED_NAME"],
        "live_name": connection.settings_dict["NAME"],
    }
    (Path(os.environ["PG_XDIST_REPORT_DIR"]) / f"{worker_id}.json").write_text(
        json.dumps(record)
    )
""",
    )

    result = pytester.runpytest_subprocess(
        "-n", "2", "--dist=each", "--testrunuid", "topology-run-a", "--ds=settings"
    )

    result.assert_outcomes(passed=2)
    records = [
        json.loads((report_dir / f"{worker_id}.json").read_text())
        for worker_id in ("gw0", "gw1")
    ]
    assert {record["worker_id"] for record in records} == {"gw0", "gw1"}
    assert {record["run_uid"] for record in records} == {"topology-run-a"}
    assert {record["vendor"] for record in records} == {"postgresql"}
    assert len({record["live_name"] for record in records}) == 2
    assert all(record["live_name"] != configured_name for record in records)
