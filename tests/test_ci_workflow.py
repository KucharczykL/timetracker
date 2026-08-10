"""GitHub Actions database-service contract."""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parents[1] / ".github/workflows/build-docker.yml"


def test_test_job_uses_a_postgresql_17_service():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    test_job = workflow["jobs"]["test"]
    postgres = test_job["services"]["postgres"]

    assert postgres["image"] == "postgres:17"
    assert postgres["env"] == {
        "POSTGRES_DB": "timetracker",
        "POSTGRES_USER": "timetracker",
        "POSTGRES_PASSWORD": "timetracker",
        "POSTGRES_INITDB_ARGS": "--locale-provider=builtin --builtin-locale=C.UTF-8 --encoding=UTF8",
    }
    assert postgres["ports"] == ["5432:5432"]
    assert "pg_isready" in postgres["options"]
    assert (
        test_job["env"]["DATABASE_URL"]
        == "postgresql://timetracker:timetracker@127.0.0.1:5432/timetracker"
    )
