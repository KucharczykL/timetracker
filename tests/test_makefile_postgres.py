"""Tests for the Make-managed PostgreSQL lifecycle boundary."""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make")


def run_make(
    tmp_path: Path, *goals: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    assert MAKE is not None
    generated = tmp_path / "postgres.mk"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = "postgresql://external.invalid/timetracker"
    environment.pop("TIMETRACKER_MANAGED_DATABASE_URL", None)
    result = subprocess.run(
        [
            MAKE,
            "--no-print-directory",
            "--dry-run",
            f"POSTGRES_MK={generated.as_posix()}",
            *goals,
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    return result, generated


def test_stop_postgres_does_not_remake_generated_include(tmp_path):
    result, generated = run_make(tmp_path, "stop-postgres")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "scripts/ensure_postgres.py --stop" in output
    assert "--makefile" not in output
    assert not generated.exists()


def test_stop_postgres_rejects_mixed_make_goals_before_remaking_include(tmp_path):
    result, generated = run_make(tmp_path, "stop-postgres", "ensure-postgres")

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "stop-postgres must be invoked alone" in output
    assert "--makefile" not in output
    assert not generated.exists()
