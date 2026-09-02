"""Fetch, restore, and verify a dump of the deployed database.

`docs/deployment.md` writes these commands out for an operator holding nothing
but a shell. Here they are the same commands with every blank already filled:
the host and the container come from configuration, the scratch database is
named and guarded, and the collation contract is applied where the restore
would otherwise inherit whatever `template1` happens to be.

Nothing here reads or writes the deployed database beyond one `pg_dump`, and
nothing restores into a database this checkout develops against.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ImproperlyConfigured

from timetracker.config import config
from timetracker.postgres_contract import REQUIRED_BUILTIN_LOCALE, REQUIRED_ENCODING

REPOSITORY = Path(__file__).parents[1]
CACHE = REPOSITORY / ".cache"
DEFAULT_DUMP_DIRECTORY = REPOSITORY / ".dumps"
DEFAULT_SCRATCH_DATABASE = "timetracker_restore_verify"
#: Dropping any of these breaks the cluster rather than a copy of a dump.
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1"})

#: `pg_dump` opens every session with an empty `search_path`, thus a function
#: that calls its helpers by bare name reaches nothing while the data loads:
#: `timetracker_temporal_is_valid` catches the lookup failure and the domain
#: answers that the value itself is invalid. `0017_temporal_value_domain` wrote
#: twelve such functions, and a dump carries the bodies as they were, thus
#: `0034` could not correct one.
#:
#: `ALTER FUNCTION` states reach and no body, so this loads a dump of any age
#: without choosing which generation of a body to write. It names no function
#: on purpose: the hazard belongs to whatever a domain CHECK or a generated
#: column reaches, which a name does not predict. An extension's functions are
#: its own business.
REACH_THE_HELPERS = r"""
DO $$
DECLARE
    function_row record;
    functions_reached integer := 0;
BEGIN
    FOR function_row IN
        SELECT candidate.oid::regprocedure AS signature
        FROM pg_proc AS candidate
        JOIN pg_namespace AS schema_entry ON schema_entry.oid = candidate.pronamespace
        WHERE schema_entry.nspname = 'public'
          AND candidate.prokind = 'f'
          AND NOT EXISTS (
              SELECT 1
              FROM unnest(coalesce(candidate.proconfig, '{}'::text[])) AS setting
              WHERE setting LIKE 'search\_path=%')
          AND NOT EXISTS (
              SELECT 1 FROM pg_depend
              WHERE objid = candidate.oid
                AND classid = 'pg_proc'::regclass
                AND deptype = 'e')
    LOOP
        EXECUTE format(
            'ALTER FUNCTION %s SET search_path = pg_catalog, public',
            function_row.signature);
        functions_reached := functions_reached + 1;
    END LOOP;
    RAISE NOTICE 'Gave % function(s) their own search_path.', functions_reached;
END
$$;
""".strip()

#: An exact partition of the dump: verified on the local database at 0040,
#: 68 + 49 + 157 = 274 entries, none in two sections and none in neither.
DUMP_SECTIONS = ("pre-data", "data", "post-data")


class DumpError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductionSource:
    """Where the deployed database is, and who reads it."""

    ssh_host: str
    container: str
    database: str
    role: str


def executable_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    stdout: IO[bytes] | None = None,
) -> None:
    subprocess.run(command, check=True, cwd=REPOSITORY, env=env, stdout=stdout)


def client_tool(name: str) -> Path:
    """Locate a PostgreSQL client program on PATH or in the managed cluster.

    `make ensure-postgres` downloads a pinned cluster when the machine has no
    PostgreSQL 18 of its own, and its `bin` directory holds these programs too.
    Finding it here is what makes the targets work outside the Nix shell.
    """
    if found := shutil.which(executable_name(name)):
        return Path(found)
    #: Both shapes the pinned archive extracts into, newest version first.
    patterns = ("postgres-binaries/*/bin", "postgres-binaries/*/*/bin")
    for directory in sorted(
        (path for pattern in patterns for path in CACHE.glob(pattern)), reverse=True
    ):
        candidate = directory / executable_name(name)
        if candidate.is_file():
            return candidate
    raise DumpError(
        f"{name} is not installed. Use the Nix development shell, install the "
        "PostgreSQL 18 client programs, or run `make ensure-postgres` first."
    )


def required_setting(name: str) -> str:
    try:
        return config(name)
    except ImproperlyConfigured as error:
        raise DumpError(
            f"{name} is not configured. Add it to .env; see .env.example and "
            "docs/configuration.md."
        ) from error


def production_source() -> ProductionSource:
    return ProductionSource(
        ssh_host=required_setting("PROD_SSH_HOST"),
        container=required_setting("PROD_DB_CONTAINER"),
        database=config("PROD_DB_NAME", default="timetracker"),
        role=config("PROD_DB_USER", default="timetracker"),
    )


def dump_directory() -> Path:
    return Path(config("DUMP_DIR", default=DEFAULT_DUMP_DIRECTORY, cast=Path))


def fetch_command(source: ProductionSource) -> list[str]:
    """One ssh invocation whose remote half is one quoted shell command."""
    remote = shlex.join(
        [
            "podman",
            "exec",
            source.container,
            "pg_dump",
            "--username",
            source.role,
            "--dbname",
            source.database,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
        ]
    )
    return ["ssh", source.ssh_host, remote]


def dump_path(directory: Path, day: date) -> Path:
    return directory / f"timetracker-{day.isoformat()}.dump"


def newest_dump(directory: Path) -> Path:
    dumps = sorted(directory.glob("*.dump"))
    if not dumps:
        raise DumpError(
            f"No dump is in {directory}. Run `make fetch-dump` first, or name "
            "one with DUMP=<path>."
        )
    #: Sorted by name, which the date in it makes the same as by age.
    return dumps[-1]


def _fetch_hint(error: Exception) -> str:
    """Name the likely cause of the one failure that reads as something else.

    A shell answers a missing program with 127, and the container runtime
    passes that back. The application container is the one whose name comes to
    mind, and it has no `pg_dump`.
    """
    if getattr(error, "returncode", None) != 127:
        return ""
    return (
        ". PROD_DB_CONTAINER must name the container running PostgreSQL, not "
        "the application container."
    )


def fetch(source: ProductionSource, destination: Path) -> Path:
    """Stream the deployed database into `destination`, whole or not at all."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    #: A dump written under its final name is a dump the next restore trusts,
    #: so an interrupted transfer must never hold that name.
    partial = destination.with_name(destination.name + ".part")
    try:
        with partial.open("wb") as sink:
            run(fetch_command(source), stdout=sink)
    except (subprocess.CalledProcessError, OSError) as error:
        partial.unlink(missing_ok=True)
        raise DumpError(
            f"Could not read the deployed database: {error}{_fetch_hint(error)}"
        ) from error
    partial.replace(destination)
    return destination


def with_database(database_url: str, database: str) -> str:
    parts = urlsplit(database_url)
    return urlunsplit(parts._replace(path=f"/{database}"))


def _guard_scratch_database(database: str, database_url: str) -> None:
    if database in PROTECTED_DATABASES:
        raise DumpError(
            f"{database} is a maintenance database of the cluster itself. "
            "Name a scratch database instead."
        )
    if database == urlsplit(database_url).path.lstrip("/"):
        raise DumpError(
            f"{database} is the database this checkout develops against. "
            "Name a scratch database instead."
        )


def _load_section(dump: Path, *, scratch_url: str, section: str) -> None:
    """Load one section of the dump into the scratch database."""
    run(
        [
            str(client_tool("pg_restore")),
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            f"--section={section}",
            f"--dbname={scratch_url}",
            str(dump),
        ]
    )


def _reach_the_helpers(scratch_url: str) -> None:
    """Give every function the dump created a `search_path` of its own.

    `psql` answers a failed script with 0 unless `ON_ERROR_STOP` says
    otherwise, and `run` reads that as success, thus without the flag a refused
    repair would surface as the original domain error one section later.
    `--no-owner` means the restoring role owns every function the load created,
    which is what `ALTER FUNCTION` asks for.
    """
    run(
        [
            str(client_tool("psql")),
            "-X",
            "--set=ON_ERROR_STOP=1",
            f"--dbname={scratch_url}",
            f"--command={REACH_THE_HELPERS}",
        ]
    )


def restore(dump: Path, *, database: str, database_url: str) -> str:
    """Load `dump` into a freshly created scratch database, and return its URL."""
    if not dump.is_file():
        raise DumpError(f"No dump is at {dump}.")
    _guard_scratch_database(database, database_url)
    maintenance = f"--maintenance-db={with_database(database_url, 'postgres')}"
    scratch_url = with_database(database_url, database)
    #: A scratch database is disposable by definition: an earlier copy left for
    #: inspection is replaced rather than standing in the way of this restore.
    run([str(client_tool("dropdb")), maintenance, "--if-exists", database])
    run(
        [
            str(client_tool("createdb")),
            maintenance,
            #: template0, so the copy carries the contract below rather than
            #: whatever template1 on this machine was created with.
            "--template=template0",
            f"--encoding={REQUIRED_ENCODING}",
            "--locale-provider=builtin",
            f"--builtin-locale={REQUIRED_BUILTIN_LOCALE}",
            database,
        ]
    )
    #: The functions get their reach between the schema and the data: the
    #: domain check and the generated columns first run during the COPY, and
    #: each pg_restore opens its own session under the empty search_path the
    #: dump sets. ALTER FUNCTION is what carries the setting across that
    #: boundary.
    _load_section(dump, scratch_url=scratch_url, section=DUMP_SECTIONS[0])
    _reach_the_helpers(scratch_url)
    for section in DUMP_SECTIONS[1:]:
        _load_section(dump, scratch_url=scratch_url, section=section)
    return scratch_url


def verify(dump: Path, *, database: str, database_url: str, keep: bool = False) -> None:
    """Restore `dump`, migrate the copy, and drop it only if both succeeded."""
    scratch_url = restore(dump, database=database, database_url=database_url)
    environment = {**os.environ, "DATABASE_URL": scratch_url}
    #: TIMETRACKER_MANAGED_DATABASE_URL would tell the harness to ignore the
    #: URL above and reprovision the development database instead.
    environment.pop("TIMETRACKER_MANAGED_DATABASE_URL", None)
    try:
        run(
            [sys.executable, str(REPOSITORY / "manage.py"), "migrate"],
            env=environment,
        )
    except subprocess.CalledProcessError as error:
        raise DumpError(
            f"Migrating the restored copy failed. Database {database} is left "
            f"for inspection: {with_database(database_url, database)}"
        ) from error
    if keep:
        print(f"==> Restored copy kept: {scratch_url}", file=sys.stderr)
        return
    run(
        [
            str(client_tool("dropdb")),
            f"--maintenance-db={with_database(database_url, 'postgres')}",
            "--if-exists",
            database,
        ]
    )
    print(f"==> {dump} restores and migrates cleanly.", file=sys.stderr)


def local_database_url() -> str:
    try:
        return config("DATABASE_URL")
    except ImproperlyConfigured as error:
        raise DumpError(
            "DATABASE_URL is not set. Run this through make, which provisions "
            "the development cluster and exports it."
        ) from error


def _resolve_dump(named: Path | None) -> Path:
    return named if named is not None else newest_dump(dump_directory())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    fetch_parser = operations.add_parser("fetch", help="copy the deployed database")
    fetch_parser.add_argument("--output", type=Path)
    for name, help_text in (
        ("restore", "load a dump into a scratch database"),
        ("verify", "restore a dump, migrate it, and drop it on success"),
    ):
        operation_parser = operations.add_parser(name, help=help_text)
        operation_parser.add_argument("--dump", type=Path)
        operation_parser.add_argument("--database", default=DEFAULT_SCRATCH_DATABASE)
        if name == "verify":
            operation_parser.add_argument("--keep", action="store_true")
    arguments = parser.parse_args()

    try:
        if arguments.operation == "fetch":
            #: This machine's date, which is the one naming a file by day means.
            today = datetime.now().astimezone().date()
            destination = arguments.output or dump_path(dump_directory(), today)
            written = fetch(production_source(), destination)
            print(f"==> Dump written to {written}", file=sys.stderr)
            return
        database_url = local_database_url()
        dump = _resolve_dump(arguments.dump)
        if arguments.operation == "restore":
            scratch_url = restore(
                dump, database=arguments.database, database_url=database_url
            )
            print(f"==> {dump} restored. Use it with:", file=sys.stderr)
            print(f"DATABASE_URL={scratch_url}")
            return
        verify(
            dump,
            database=arguments.database,
            database_url=database_url,
            keep=arguments.keep,
        )
    except (DumpError, subprocess.CalledProcessError, OSError) as error:
        raise SystemExit(f"{arguments.operation}-dump: {error}") from error


if __name__ == "__main__":
    main()
