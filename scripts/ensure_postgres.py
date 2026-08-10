"""Provision the ignored PostgreSQL 17 development cluster used by Make."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ImproperlyConfigured

from timetracker.config import config
from timetracker.postgres_contract import (
    CATALOG_QUERY,
    REQUIRED_BUILTIN_LOCALE,
    REQUIRED_ENCODING,
    REQUIRED_LOCALE_PROVIDER,
    REQUIRED_POSTGRES_MAJOR,
    PostgresContract,
)

REQUIRED_MAJOR = 17
TOOL_NAMES = (
    "initdb",
    "pg_ctl",
    "pg_isready",
    "psql",
    "createuser",
    "createdb",
    "postgres",
)
FALLBACK_VERSION = "17.6.0"
FALLBACKS = {
    ("Linux", "x86_64"): (
        "postgresql-17.6.0-x86_64-unknown-linux-gnu.tar.gz",
        "19dbf09f0fc33255ff7596fc3ceb7696647286dd15fdf60f3f65c583aae6ad5d",
    ),
    ("Darwin", "arm64"): (
        "postgresql-17.6.0-aarch64-apple-darwin.tar.gz",
        "4d39534c9359ce04a6b1781111579e425d95c7ae2c8abe3ddfd6808b6ad19a5b",
    ),
    ("Darwin", "x86_64"): (
        "postgresql-17.6.0-x86_64-apple-darwin.tar.gz",
        "3ec4c5e8887d21e3cb7e899a27a0d64811feda90b946c2571a457d00dd8ee752",
    ),
    ("Windows", "AMD64"): (
        "postgresql-17.6.0-x86_64-pc-windows-msvc.tar.gz",
        "92d8de275fa9b5f831280fb6124401cdfe8137ff34002dfc352f2cf4126805ef",
    ),
}


class HarnessError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tools:
    initdb: Path
    pg_ctl: Path
    pg_isready: Path
    psql: Path
    createuser: Path
    createdb: Path
    postgres: Path


def executable_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, capture_output=capture)


def postgres_major(postgres: Path) -> int:
    result = run([str(postgres), "--version"], capture=True)
    match = re.search(r"PostgreSQL\)?\s+(\d+)", result.stdout)
    if not match:
        raise HarnessError(f"Could not determine PostgreSQL version from {postgres}.")
    return int(match.group(1))


def _tools_from_directory(directory: Path) -> Tools | None:
    paths = [directory / executable_name(name) for name in TOOL_NAMES]
    if not all(path.is_file() for path in paths):
        return None
    tools = Tools(*paths)
    return tools if postgres_major(tools.postgres) == REQUIRED_MAJOR else None


def path_tools() -> Tools | None:
    paths = [shutil.which(executable_name(name)) for name in TOOL_NAMES]
    if any(path is None for path in paths):
        return None
    tools = Tools(*(Path(path) for path in paths if path is not None))
    return tools if postgres_major(tools.postgres) == REQUIRED_MAJOR else None


def verify_checksum(archive: Path, expected: str) -> None:
    with archive.open("rb") as file:
        actual = hashlib.file_digest(file, "sha256").hexdigest()
    if actual != expected:
        raise HarnessError(
            f"PostgreSQL fallback archive SHA-256 mismatch: expected {expected}, got {actual}."
        )


def fallback_tools(cache: Path) -> Tools:
    key = (platform.system(), platform.machine())
    try:
        filename, checksum = FALLBACKS[key]
    except KeyError as exc:
        raise HarnessError(
            f"No checksum-pinned PostgreSQL 17 fallback is available for {key[0]} {key[1]}. "
            "Use the Nix development shell or set DATABASE_URL."
        ) from exc
    destination = cache / "postgres-binaries" / FALLBACK_VERSION
    existing = _tools_from_directory(destination / "bin")
    if existing:
        return existing
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / filename
    if not archive.exists():
        url = f"https://github.com/theseus-rs/postgresql-binaries/releases/download/{FALLBACK_VERSION}/{filename}"
        print(
            f"==> Downloading checksum-pinned PostgreSQL {FALLBACK_VERSION} fallback",
            file=sys.stderr,
        )
        try:
            urllib.request.urlretrieve(url, archive)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise HarnessError(
                    "Could not verify the HTTPS certificate for the PostgreSQL fallback "
                    "download. Use the Nix development shell, configure this machine's "
                    "trusted CA certificates, or set DATABASE_URL."
                ) from exc
            raise
    verify_checksum(archive, checksum)
    with tarfile.open(archive) as tar:
        root = destination.resolve()
        for member in tar.getmembers():
            if not (root / member.name).resolve().is_relative_to(root):
                raise HarnessError("Fallback archive contains an unsafe path.")
        tar.extractall(destination, filter="data")
    tools = _tools_from_directory(destination / "bin")
    if tools is None:
        candidates = list(destination.glob("*/bin"))
        tools = _tools_from_directory(candidates[0]) if len(candidates) == 1 else None
    if tools is None:
        raise HarnessError(
            "Pinned PostgreSQL archive did not contain PostgreSQL 17 tools."
        )
    return tools


def explicit_database_url() -> str | None:
    try:
        return config(
            "DATABASE_URL",
            include_environment=os.environ.get("TIMETRACKER_MANAGED_DATABASE_URL")
            != "1",
        )
    except ImproperlyConfigured:
        return None


def choose_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def initialize_cluster(tools: Tools, data_dir: Path) -> None:
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            str(tools.initdb),
            "-D",
            str(data_dir),
            "--encoding=UTF8",
            "--locale-provider=builtin",
            "--builtin-locale=C.UTF-8",
            "--auth=trust",
        ]
    )


def cluster_is_running(tools: Tools, data_dir: Path) -> bool:
    result = subprocess.run(
        [str(tools.pg_ctl), "status", "-D", str(data_dir)],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def start_cluster(tools: Tools, data_dir: Path, port: int) -> None:
    pid_file = data_dir / "postmaster.pid"
    if pid_file.exists() and not cluster_is_running(tools, data_dir):
        pid_file.unlink()
    if not cluster_is_running(tools, data_dir):
        socket_dir = Path(tempfile.gettempdir()) / (
            "timetracker-pg-" + hashlib.sha256(str(data_dir).encode()).hexdigest()[:12]
        )
        socket_dir.mkdir(exist_ok=True)
        run(
            [
                str(tools.pg_ctl),
                "-D",
                str(data_dir),
                "-o",
                f"-h 127.0.0.1 -p {port} -k {socket_dir}",
                "-w",
                "start",
            ]
        )


def wait_for_ready(tools: Tools, port: int) -> None:
    for _ in range(30):
        result = subprocess.run(
            [
                str(tools.pg_isready),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-d",
                "postgres",
            ],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(0.2)
    raise HarnessError("PostgreSQL did not become ready within 6 seconds.")


def provision_database(tools: Tools, port: int) -> None:
    base = ["-h", "127.0.0.1", "-p", str(port)]
    exists = run(
        [
            str(tools.psql),
            *base,
            "-d",
            "postgres",
            "-Atqc",
            "SELECT 1 FROM pg_roles WHERE rolname = 'timetracker'",
        ],
        capture=True,
    )
    if exists.stdout.strip() != "1":
        run([str(tools.createuser), *base, "--superuser", "timetracker"])
    exists = run(
        [
            str(tools.psql),
            *base,
            "-d",
            "postgres",
            "-Atqc",
            "SELECT 1 FROM pg_database WHERE datname = 'timetracker'",
        ],
        capture=True,
    )
    if exists.stdout.strip() != "1":
        run([str(tools.createdb), *base, "-O", "timetracker", "timetracker"])


def verify_contract(tools: Tools, port: int) -> PostgresContract:
    result = run(
        [
            str(tools.psql),
            "-h",
            "127.0.0.1",
            "-p",
            str(port),
            "-U",
            "timetracker",
            "-d",
            "timetracker",
            "-At",
            "-F",
            "|",
            "-c",
            CATALOG_QUERY,
        ],
        capture=True,
    )
    fields = result.stdout.strip().split("|")
    if len(fields) != 4:
        raise HarnessError("PostgreSQL catalog contract query returned an invalid row.")
    try:
        contract = PostgresContract(int(fields[0]), fields[1], fields[2], fields[3])
    except ValueError as exc:
        raise HarnessError(
            "PostgreSQL catalog contract returned an invalid server version."
        ) from exc

    actual_major = contract.server_version_num // 10_000
    if actual_major != REQUIRED_POSTGRES_MAJOR:
        raise HarnessError(
            "PostgreSQL collation contract requires major version "
            f"{REQUIRED_POSTGRES_MAJOR}, got {actual_major}."
        )
    if contract.encoding != REQUIRED_ENCODING:
        raise HarnessError(
            f"PostgreSQL collation contract requires encoding {REQUIRED_ENCODING}, "
            f"got {contract.encoding}."
        )
    if contract.locale_provider != REQUIRED_LOCALE_PROVIDER:
        raise HarnessError(
            "PostgreSQL collation contract requires provider builtin, "
            f"got {contract.locale_provider}."
        )
    if contract.locale != REQUIRED_BUILTIN_LOCALE:
        raise HarnessError(
            "PostgreSQL collation contract requires builtin locale "
            f"{REQUIRED_BUILTIN_LOCALE}, got {contract.locale}."
        )
    return contract


def redact_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.password is None:
        return url
    user = parsed.username or ""
    host = parsed.hostname or ""
    netloc = f"{user}:***@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def makefile_contents(url: str | None) -> str:
    if url is None:
        raise HarnessError("No generated database URL.")
    if explicit_database_url():
        return "# DATABASE_URL was supplied explicitly; the harness did not alter it.\n"
    return (
        "ifeq ($(origin DATABASE_URL), undefined)\n"
        f"export DATABASE_URL := {url}\n"
        "export TIMETRACKER_MANAGED_DATABASE_URL := 1\n"
        "endif\n"
    )


def ensure(cache: Path) -> str:
    if url := explicit_database_url():
        print(f"==> Using explicit DATABASE_URL: {redact_url(url)}", file=sys.stderr)
        return url
    tools = path_tools() or fallback_tools(cache)
    data_dir = cache / "postgres" / "data"
    port_file = cache / "postgres" / "port"
    if not data_dir.exists():
        initialize_cluster(tools, data_dir)
    port = int(port_file.read_text()) if port_file.exists() else choose_port()
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(f"{port}\n")
    start_cluster(tools, data_dir, port)
    wait_for_ready(tools, port)
    provision_database(tools, port)
    verify_contract(tools, port)
    url = f"postgresql://timetracker@127.0.0.1:{port}/timetracker"
    print(
        f"==> PostgreSQL 17 ready: {redact_url(url)} (UTF8, builtin, C.UTF-8)",
        file=sys.stderr,
    )
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--makefile", type=Path, required=True)
    args = parser.parse_args()
    try:
        url = ensure(Path(__file__).parents[1] / ".cache")
        args.makefile.parent.mkdir(parents=True, exist_ok=True)
        contents = makefile_contents(url)
        if not args.makefile.is_file() or args.makefile.read_text() != contents:
            args.makefile.write_text(contents)
    except (HarnessError, subprocess.CalledProcessError, OSError) as exc:
        raise SystemExit(f"ensure-postgres: {exc}") from exc


if __name__ == "__main__":
    main()
