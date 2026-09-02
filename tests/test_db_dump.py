"""Unit tests for the deployed-database dump, restore, and verify tooling."""

import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

TOOLING_PATH = Path(__file__).parents[1] / "scripts" / "db_dump.py"
LOCAL_URL = "postgresql://timetracker@127.0.0.1:33831/timetracker"


@pytest.fixture
def tooling():
    spec = importlib.util.spec_from_file_location("db_dump", TOOLING_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def isolated_configuration(monkeypatch, tmp_path):
    """Read configuration from nothing, so a real .env cannot decide a test."""
    from timetracker import config as config_module

    for name in (
        "PROD_SSH_HOST",
        "PROD_DB_CONTAINER",
        "PROD_DB_NAME",
        "PROD_DB_USER",
        "DUMP_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()
    yield monkeypatch
    config_module.reset_caches()


def _source(tooling):
    return tooling.ProductionSource(
        ssh_host="tracker.example",
        container="timetracker-db",
        database="timetracker",
        role="timetracker",
    )


def test_the_fetch_command_runs_pg_dump_inside_the_container_over_ssh(tooling):
    command = tooling.fetch_command(_source(tooling))

    assert command[:2] == ["ssh", "tracker.example"]
    assert command[2:] == [
        (
            "podman exec timetracker-db pg_dump --username timetracker "
            "--dbname timetracker --format=custom --no-owner --no-privileges"
        )
    ]


def test_a_container_name_needing_quotes_stays_one_argument(tooling):
    source = tooling.ProductionSource(
        ssh_host="tracker.example",
        container="a container",
        database="timetracker",
        role="timetracker",
    )

    assert "'a container'" in tooling.fetch_command(source)[2]


def test_the_production_source_reads_its_names_from_configuration(
    tooling, isolated_configuration
):
    isolated_configuration.setenv("PROD_SSH_HOST", "tracker.example")
    isolated_configuration.setenv("PROD_DB_CONTAINER", "timetracker-db")

    source = tooling.production_source()

    assert source.ssh_host == "tracker.example"
    assert source.container == "timetracker-db"
    #: Both name the deployment's defaults, so only the two above are required.
    assert (source.database, source.role) == ("timetracker", "timetracker")


def test_a_missing_ssh_host_names_the_setting_to_add(tooling, isolated_configuration):
    isolated_configuration.setenv("PROD_DB_CONTAINER", "timetracker-db")

    with pytest.raises(tooling.DumpError, match="PROD_SSH_HOST"):
        tooling.production_source()


def test_a_dump_is_named_for_the_day_it_was_fetched(tooling, tmp_path):
    assert tooling.dump_path(tmp_path, date(2026, 8, 28)) == (
        tmp_path / "timetracker-2026-08-28.dump"
    )


def test_a_finished_transfer_replaces_the_partial_file(tooling, monkeypatch, tmp_path):
    destination = tmp_path / "dumps" / "timetracker-2026-08-28.dump"

    def write_archive(command, **kwargs):
        kwargs["stdout"].write(b"PGDMP")

    monkeypatch.setattr(tooling, "run", write_archive)

    assert tooling.fetch(_source(tooling), destination) == destination
    assert destination.read_bytes() == b"PGDMP"
    assert list(destination.parent.iterdir()) == [destination]


def test_a_failed_transfer_leaves_no_dump_behind(tooling, monkeypatch, tmp_path):
    """A truncated transfer must not be mistaken for a dump on the next restore."""
    destination = tmp_path / "timetracker-2026-08-28.dump"

    def fail_midway(command, **kwargs):
        kwargs["stdout"].write(b"PGD")
        raise subprocess.CalledProcessError(255, command)

    monkeypatch.setattr(tooling, "run", fail_midway)

    with pytest.raises(tooling.DumpError, match="deployed database"):
        tooling.fetch(_source(tooling), destination)

    assert list(tmp_path.iterdir()) == []


def test_a_container_without_pg_dump_names_the_likely_mistake(
    tooling, monkeypatch, tmp_path
):
    """127 is a missing program, and the application container is the one
    whose name comes to mind."""

    def command_not_found(command, **kwargs):
        raise subprocess.CalledProcessError(127, command)

    monkeypatch.setattr(tooling, "run", command_not_found)

    with pytest.raises(tooling.DumpError, match="not the application container"):
        tooling.fetch(_source(tooling), tmp_path / "timetracker.dump")


def test_the_newest_dump_is_used_when_none_is_named(tooling, tmp_path):
    older = tmp_path / "timetracker-2026-08-01.dump"
    newer = tmp_path / "timetracker-2026-08-28.dump"
    for dump in (older, newer):
        dump.write_bytes(b"PGDMP")

    assert tooling.newest_dump(tmp_path) == newer


def test_an_empty_dump_directory_says_which_target_fills_it(tooling, tmp_path):
    with pytest.raises(tooling.DumpError, match="make fetch-dump"):
        tooling.newest_dump(tmp_path)


def test_restore_refuses_the_database_this_checkout_develops_against(
    tooling, monkeypatch, tmp_path
):
    dump = tmp_path / "timetracker.dump"
    dump.write_bytes(b"PGDMP")
    monkeypatch.setattr(
        tooling, "run", lambda *args, **kwargs: pytest.fail("must not touch the server")
    )

    with pytest.raises(tooling.DumpError, match="develops against"):
        tooling.restore(dump, database="timetracker", database_url=LOCAL_URL)


def test_restore_refuses_a_maintenance_database(tooling, monkeypatch, tmp_path):
    dump = tmp_path / "timetracker.dump"
    dump.write_bytes(b"PGDMP")
    monkeypatch.setattr(
        tooling, "run", lambda *args, **kwargs: pytest.fail("must not touch the server")
    )

    with pytest.raises(tooling.DumpError, match="postgres"):
        tooling.restore(dump, database="postgres", database_url=LOCAL_URL)


def _recorded_restore(tooling, monkeypatch, tmp_path, **overrides):
    dump = tmp_path / "timetracker.dump"
    dump.write_bytes(b"PGDMP")
    commands: list[list[str]] = []
    monkeypatch.setattr(tooling, "client_tool", lambda name: Path("/tools") / name)
    monkeypatch.setattr(
        tooling, "run", lambda command, **kwargs: commands.append(command)
    )
    url = tooling.restore(
        dump,
        database="timetracker_restore_verify",
        database_url=LOCAL_URL,
        **overrides,
    )
    return commands, url


def test_restore_creates_the_scratch_database_under_the_collation_contract(
    tooling, monkeypatch, tmp_path
):
    commands, url = _recorded_restore(tooling, monkeypatch, tmp_path)

    maintenance = "--maintenance-db=postgresql://timetracker@127.0.0.1:33831/postgres"
    #: The scratch database is disposable by definition, so an earlier
    #: inspection copy is replaced rather than standing in the way.
    assert commands[0] == [
        "/tools/dropdb",
        maintenance,
        "--if-exists",
        "timetracker_restore_verify",
    ]
    assert commands[1] == [
        "/tools/createdb",
        maintenance,
        "--template=template0",
        "--encoding=UTF8",
        "--locale-provider=builtin",
        "--builtin-locale=C.UTF-8",
        "timetracker_restore_verify",
    ]
    assert url == (
        "postgresql://timetracker@127.0.0.1:33831/timetracker_restore_verify"
    )


def _section_command(url: str, dump: str, section: str) -> list[str]:
    return [
        "/tools/pg_restore",
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        f"--section={section}",
        f"--dbname={url}",
        dump,
    ]


def test_restore_loads_each_section_with_the_documented_flags(
    tooling, monkeypatch, tmp_path
):
    commands, url = _recorded_restore(tooling, monkeypatch, tmp_path)
    dump = str(tmp_path / "timetracker.dump")

    assert commands[2] == _section_command(url, dump, "pre-data")
    assert commands[4] == _section_command(url, dump, "data")
    assert commands[5] == _section_command(url, dump, "post-data")
    assert len(commands) == 6


def test_the_repair_runs_between_the_schema_and_the_data(
    tooling, monkeypatch, tmp_path
):
    """After the data section is too late: the COPY is what fails."""
    commands, url = _recorded_restore(tooling, monkeypatch, tmp_path)

    assert commands[3] == [
        "/tools/psql",
        "-X",
        "--set=ON_ERROR_STOP=1",
        f"--dbname={url}",
        f"--command={tooling.REACH_THE_HELPERS}",
    ]


def test_a_refused_repair_stops_the_restore(tooling, monkeypatch, tmp_path):
    """psql answers a failed script with 0 unless ON_ERROR_STOP says otherwise.

    `run` uses `check=True`, so without the flag the operator would meet
    the original domain error one section later, with nothing saying the
    repair never ran.
    """
    commands, _ = _recorded_restore(tooling, monkeypatch, tmp_path)

    assert "--set=ON_ERROR_STOP=1" in commands[3]
    #: -X skips the operator's ~/.psqlrc, one more blank this module fills.
    assert "-X" in commands[3]


def test_the_repair_names_no_function(tooling):
    """A name test would miss whatever a later migration adds.

    The hazard belongs to any public function a domain CHECK or a
    generated column reaches during a load, and the name does not
    predict that.
    """
    block = tooling.REACH_THE_HELPERS

    assert "timetracker_temporal" not in block
    #: ALTER FUNCTION refuses an aggregate or a procedure.
    assert "prokind = 'f'" in block
    #: An extension's functions are its own business.
    assert "deptype = 'e'" in block
    #: Unescaped, LIKE would read the underscore as a wildcard.
    assert r"search\_path=%" in block


def test_verify_drops_the_scratch_database_only_after_migrations_apply(
    tooling, monkeypatch, tmp_path
):
    dump = tmp_path / "timetracker.dump"
    dump.write_bytes(b"PGDMP")
    scratch = "postgresql://timetracker@127.0.0.1:33831/timetracker_restore_verify"
    commands: list[list[str]] = []
    monkeypatch.setattr(tooling, "client_tool", lambda name: Path("/tools") / name)
    monkeypatch.setattr(tooling, "restore", lambda *args, **kwargs: scratch)

    def fail_migrating(command, **kwargs):
        commands.append(command)
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(tooling, "run", fail_migrating)

    with pytest.raises(tooling.DumpError, match="timetracker_restore_verify"):
        tooling.verify(
            dump, database="timetracker_restore_verify", database_url=LOCAL_URL
        )

    assert [command[-1] for command in commands] == ["migrate"]


def test_verify_drops_the_scratch_database_when_migrations_apply(
    tooling, monkeypatch, tmp_path
):
    dump = tmp_path / "timetracker.dump"
    dump.write_bytes(b"PGDMP")
    commands: list[list[str]] = []
    monkeypatch.setattr(tooling, "client_tool", lambda name: Path("/tools") / name)
    monkeypatch.setattr(
        tooling,
        "restore",
        lambda *args, **kwargs: (
            "postgresql://timetracker@127.0.0.1:33831/timetracker_restore_verify"
        ),
    )
    monkeypatch.setattr(
        tooling, "run", lambda command, **kwargs: commands.append(command)
    )

    tooling.verify(dump, database="timetracker_restore_verify", database_url=LOCAL_URL)

    assert commands[-1] == [
        "/tools/dropdb",
        "--maintenance-db=postgresql://timetracker@127.0.0.1:33831/postgres",
        "--if-exists",
        "timetracker_restore_verify",
    ]


def test_verify_keeps_the_scratch_database_when_asked(tooling, monkeypatch, tmp_path):
    dump = tmp_path / "timetracker.dump"
    dump.write_bytes(b"PGDMP")
    commands: list[list[str]] = []
    monkeypatch.setattr(tooling, "client_tool", lambda name: Path("/tools") / name)
    monkeypatch.setattr(
        tooling,
        "restore",
        lambda *args, **kwargs: (
            "postgresql://timetracker@127.0.0.1:33831/timetracker_restore_verify"
        ),
    )
    monkeypatch.setattr(
        tooling, "run", lambda command, **kwargs: commands.append(command)
    )

    tooling.verify(
        dump,
        database="timetracker_restore_verify",
        database_url=LOCAL_URL,
        keep=True,
    )

    assert [command[-1] for command in commands] == ["migrate"]


def test_migrations_run_against_the_restored_copy_alone(tooling, monkeypatch, tmp_path):
    dump = tmp_path / "timetracker.dump"
    dump.write_bytes(b"PGDMP")
    scratch = "postgresql://timetracker@127.0.0.1:33831/timetracker_restore_verify"
    environments: list[dict[str, str]] = []
    monkeypatch.setattr(tooling, "client_tool", lambda name: Path("/tools") / name)
    monkeypatch.setattr(tooling, "restore", lambda *args, **kwargs: scratch)
    monkeypatch.setattr(
        tooling,
        "run",
        lambda command, **kwargs: environments.append(kwargs.get("env") or {}),
    )

    tooling.verify(dump, database="timetracker_restore_verify", database_url=LOCAL_URL)

    assert environments[0]["DATABASE_URL"] == scratch


def test_client_tool_falls_back_to_the_managed_cluster_binaries(
    tooling, monkeypatch, tmp_path
):
    """A machine without PostgreSQL on PATH still has the downloaded cluster."""
    cached = tmp_path / "postgres-binaries" / "18.4.0" / "nested" / "bin"
    cached.mkdir(parents=True)
    (cached / tooling.executable_name("pg_restore")).touch()
    monkeypatch.setattr(tooling.shutil, "which", lambda name: None)
    monkeypatch.setattr(tooling, "CACHE", tmp_path)

    assert tooling.client_tool("pg_restore") == (
        cached / tooling.executable_name("pg_restore")
    )


def test_a_missing_client_tool_names_the_way_out(tooling, monkeypatch, tmp_path):
    monkeypatch.setattr(tooling.shutil, "which", lambda name: None)
    monkeypatch.setattr(tooling, "CACHE", tmp_path)

    with pytest.raises(tooling.DumpError, match="pg_restore"):
        tooling.client_tool("pg_restore")
