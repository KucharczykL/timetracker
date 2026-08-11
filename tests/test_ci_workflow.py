"""GitHub Actions database-service contract."""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parents[1] / ".github/workflows/build-docker.yml"


def test_test_job_uses_a_postgresql_18_4_service():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    test_job = workflow["jobs"]["test"]
    postgres = test_job["services"]["postgres"]

    assert postgres["image"] == "postgres:18.4"
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


def test_test_job_smoke_tests_the_database_url_secret_as_the_image_user():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["test"]["steps"]
    smoke_test = next(
        step for step in steps if step.get("name") == "Smoke test database URL secret"
    )

    assert "docker build" in smoke_test["run"]
    assert "--user 1000:1000" in smoke_test["run"]
    assert (
        "DATABASE_URL__FILE=/run/secrets/timetracker_database_url" in smoke_test["run"]
    )
    assert "required_database_settings" in smoke_test["run"]


def test_test_job_verifies_an_isolated_postgresql_backup_restore():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["test"]["steps"]
    restore = next(
        step for step in steps if step.get("name") == "Verify PostgreSQL backup restore"
    )

    assert "${{ job.services.postgres.id }}" in restore["run"]
    assert "docker ps" not in restore["run"]
    assert "pg_dump" in restore["run"]
    assert "--format=custom" in restore["run"]
    assert "--no-owner" in restore["run"]
    assert "--no-privileges" in restore["run"]
    assert "timetracker_restore_verify" in restore["run"]
    assert "pg_restore" in restore["run"]
    assert "--exit-on-error" in restore["run"]
    assert "uv run --frozen python manage.py migrate\n" in restore["run"]
    assert "manage.py migrate --check" in restore["run"]
    assert "dropdb" in restore["run"]
    assert "trap" not in restore["run"]
