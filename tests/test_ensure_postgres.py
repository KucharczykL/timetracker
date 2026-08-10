"""Unit tests for the disposable PostgreSQL development harness."""

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS_PATH = Path(__file__).parents[1] / "scripts" / "ensure_postgres.py"


@pytest.fixture
def harness():
    spec = importlib.util.spec_from_file_location("ensure_postgres", HARNESS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_explicit_database_url_is_preserved_without_provisioning(harness, monkeypatch):
    monkeypatch.delenv("TIMETRACKER_MANAGED_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://external.example/tracker")

    assert harness.explicit_database_url() == "postgresql://external.example/tracker"
    assert harness.makefile_contents("postgresql://external.example/tracker") == (
        "# DATABASE_URL was supplied explicitly; the harness did not alter it.\n"
    )


def test_generated_makefile_does_not_override_a_process_database_url(
    harness, monkeypatch
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TIMETRACKER_MANAGED_DATABASE_URL", raising=False)

    assert harness.makefile_contents("postgresql://timetracker@127.0.0.1/tracker") == (
        "ifeq ($(origin DATABASE_URL), undefined)\n"
        "export DATABASE_URL := postgresql://timetracker@127.0.0.1/tracker\n"
        "export TIMETRACKER_MANAGED_DATABASE_URL := 1\n"
        "endif\n"
    )


def test_explicit_database_url_uses_the_project_dotenv_configuration(
    harness, monkeypatch, tmp_path
):
    from timetracker import config as config_module

    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=postgresql://external.example/from-dotenv\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TIMETRACKER_MANAGED_DATABASE_URL", raising=False)
    monkeypatch.setenv("ENV_FILE", str(dotenv))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()

    try:
        assert (
            harness.explicit_database_url()
            == "postgresql://external.example/from-dotenv"
        )
    finally:
        config_module.reset_caches()


def test_managed_database_url_does_not_block_reprovisioning(harness, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://timetracker@127.0.0.1/tracker")
    monkeypatch.setenv("TIMETRACKER_MANAGED_DATABASE_URL", "1")

    assert harness.explicit_database_url() is None


def test_managed_database_url_yields_to_a_new_dotenv_url(
    harness, monkeypatch, tmp_path
):
    from timetracker import config as config_module

    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=postgresql://external.example/from-dotenv\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql://timetracker@127.0.0.1/tracker")
    monkeypatch.setenv("TIMETRACKER_MANAGED_DATABASE_URL", "1")
    monkeypatch.setenv("ENV_FILE", str(dotenv))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()

    try:
        assert (
            harness.explicit_database_url()
            == "postgresql://external.example/from-dotenv"
        )
    finally:
        config_module.reset_caches()


def test_path_tools_require_postgresql_17(harness, monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/tools/{name}")
    seen: list[Path] = []

    def required_major(postgres: Path) -> int:
        seen.append(postgres)
        return 17

    monkeypatch.setattr(harness, "postgres_major", required_major)

    tools = harness.path_tools()

    assert tools.initdb == Path("/tools") / harness.executable_name("initdb")
    assert seen == [tools.postgres]


def test_path_tools_reject_wrong_major(harness, monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/tools/{name}")
    monkeypatch.setattr(harness, "postgres_major", lambda postgres: 16)

    assert harness.path_tools() is None


def test_fallback_tools_reuse_an_extracted_nested_bin_directory(
    harness, monkeypatch, tmp_path
):
    monkeypatch.setattr(harness.platform, "system", lambda: "Linux")
    monkeypatch.setattr(harness.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(harness, "postgres_major", lambda postgres: 17)
    monkeypatch.setattr(
        harness.urllib.request,
        "urlretrieve",
        lambda *args: pytest.fail("must not download a second time"),
    )
    nested_bin = (
        tmp_path
        / "postgres-binaries"
        / harness.FALLBACK_VERSION
        / "postgresql-17.6.0-x86_64-unknown-linux-gnu"
        / "bin"
    )
    nested_bin.mkdir(parents=True)
    for name in harness.TOOL_NAMES:
        (nested_bin / harness.executable_name(name)).touch()

    tools = harness.fallback_tools(tmp_path)

    assert tools.initdb == nested_bin / harness.executable_name("initdb")


def test_redacted_url_hides_a_password(harness):
    assert harness.redact_url("postgresql://user:secret@127.0.0.1:5432/tracker") == (
        "postgresql://user:***@127.0.0.1:5432/tracker"
    )


def test_checksum_failure_does_not_extract_archive(harness, tmp_path):
    archive = tmp_path / "postgres.tar.gz"
    archive.write_bytes(b"not an archive")

    with pytest.raises(harness.HarnessError, match="SHA-256"):
        harness.verify_checksum(archive, "0" * 64)

    assert hashlib.sha256(archive.read_bytes()).hexdigest() != "0" * 64


def test_initdb_uses_the_required_collation_contract(harness, monkeypatch, tmp_path):
    commands: list[list[str]] = []
    monkeypatch.setattr(harness, "run", lambda args, **kwargs: commands.append(args))
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))

    harness.initialize_cluster(tools, tmp_path / "data")

    assert commands == [
        [
            str(tools.initdb),
            "-D",
            str(tmp_path / "data"),
            "--encoding=UTF8",
            "--locale-provider=builtin",
            "--builtin-locale=C.UTF-8",
            "--auth=trust",
        ]
    ]


def test_start_cluster_removes_stale_process_metadata(harness, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    stale_pid = data_dir / "postmaster.pid"
    stale_pid.write_text("12345\n")
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    commands: list[list[str]] = []
    monkeypatch.setattr(harness, "cluster_is_running", lambda *args: False)
    monkeypatch.setattr(harness, "run", lambda args, **kwargs: commands.append(args))

    harness.start_cluster(tools, data_dir, 5432)

    assert not stale_pid.exists()
    assert commands[0][:3] == [str(tools.pg_ctl), "-D", str(data_dir)]


def test_wait_for_ready_retries_until_postgres_accepts_connections(
    harness, monkeypatch, tmp_path
):
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    results = iter([1, 0])
    sleeps: list[float] = []
    monkeypatch.setattr(
        harness.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, next(results)),
    )
    monkeypatch.setattr(harness.time, "sleep", sleeps.append)

    harness.wait_for_ready(tools, 5432)

    assert sleeps == [0.2]


def test_ensure_reuses_existing_cluster_metadata(harness, monkeypatch, tmp_path):
    cache = tmp_path / ".cache"
    data_dir = cache / "postgres" / "data"
    data_dir.mkdir(parents=True)
    (cache / "postgres" / "port").write_text("5432\n")
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    started: list[int] = []
    monkeypatch.setattr(harness, "explicit_database_url", lambda: None)
    monkeypatch.setattr(harness, "path_tools", lambda: tools)
    monkeypatch.setattr(
        harness, "initialize_cluster", lambda *args: pytest.fail("init")
    )
    monkeypatch.setattr(harness, "choose_port", lambda: pytest.fail("new port"))
    monkeypatch.setattr(
        harness, "start_cluster", lambda _tools, _data_dir, port: started.append(port)
    )
    monkeypatch.setattr(harness, "wait_for_ready", lambda *args: None)
    monkeypatch.setattr(harness, "provision_database", lambda *args: None)
    monkeypatch.setattr(harness, "verify_contract", lambda *args: None)

    assert (
        harness.ensure(cache) == "postgresql://timetracker@127.0.0.1:5432/timetracker"
    )
    assert started == [5432]


def test_verify_contract_reads_the_provisioned_database_catalog(
    harness, monkeypatch, tmp_path
):
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    seen: list[list[str]] = []

    def fake_run(args, **kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout="170010|UTF8|b|C.UTF-8\n",
            stderr="",
        )

    monkeypatch.setattr(harness, "run", fake_run)

    contract = harness.verify_contract(tools, 5432)

    assert contract.locale == "C.UTF-8"
    assert seen[0] == [
        str(tools.psql),
        "-h",
        "127.0.0.1",
        "-p",
        "5432",
        "-U",
        "timetracker",
        "-d",
        "timetracker",
        "-At",
        "-F",
        "|",
        "-c",
        harness.CATALOG_QUERY,
    ]


def test_verify_contract_rejects_wrong_catalog_metadata(harness, monkeypatch, tmp_path):
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    monkeypatch.setattr(
        harness,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout="160010|UTF8|b|C.UTF-8\n", stderr=""
        ),
    )

    with pytest.raises(harness.HarnessError, match="major version 17"):
        harness.verify_contract(tools, 5432)
