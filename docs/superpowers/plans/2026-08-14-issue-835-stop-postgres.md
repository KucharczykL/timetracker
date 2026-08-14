# Issue #835 Worktree PostgreSQL Shutdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an idempotent `make stop-postgres` command that fast-stops only the current worktree's managed PostgreSQL cluster without provisioning it first.

**Architecture:** GNU Make detects the standalone shutdown goal before loading the generated PostgreSQL include, preventing Make's include-remake phase from entering the provisioning path. The existing Python harness gains a non-provisioning stop operation that reuses only already-available PostgreSQL 18 tools and delegates process ownership to `pg_ctl` with the worktree data directory.

**Tech Stack:** GNU Make, Python 3.14, PostgreSQL 18 `pg_ctl`, pytest, Markdown.

## Global Constraints

- `make stop-postgres` acts only on `.cache/postgres/data` in the current worktree.
- Shutdown uses PostgreSQL fast mode and waits for completion.
- Missing and already-stopped clusters return success.
- The stop-only path must not download, initialize, start, or provision PostgreSQL.
- `stop-postgres` must be invoked as the only Make goal.
- Do not use `taskkill`, `Stop-Process`, or process-name-based termination.
- Keep the Makefile's default `PYTEST_WORKERS`; do not set it to `0` for normal verification.
- On Windows Codex desktop, launch every `make test`, `make check-fast`, and `make check` command as a managed hidden process and wait for its final log and exit status.

---

### Task 1: Protect the stop target from Make include remaking

**Files:**
- Create: `tests/test_makefile_postgres.py`
- Modify: `Makefile:1-10`

**Interfaces:**
- Consumes: GNU Make's `MAKECMDGOALS` and overridable `POSTGRES_MK` path.
- Produces: standalone `stop-postgres` recipe selecting `scripts/ensure_postgres.py --stop`; parse-time rejection of mixed goals.

- [ ] **Step 1: Write the failing Make interaction tests**

```python
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
```

- [ ] **Step 2: Run the focused tests and verify the safe RED state**

Run through the required hidden-process wrapper:

```text
make test ARGS="tests/test_makefile_postgres.py -v"
```

Expected: both tests fail because the current Makefile remakes the alternate
include and has no `stop-postgres` rule. The inert explicit `DATABASE_URL`
ensures this RED run cannot provision PostgreSQL.

- [ ] **Step 3: Add the parse-time lifecycle boundary and target**

Replace the PostgreSQL preamble at the top of `Makefile` with:

```make
POSTGRES_MK = .cache/postgres.mk

ifneq ($(filter stop-postgres,$(MAKECMDGOALS)),)
ifneq ($(MAKECMDGOALS),stop-postgres)
$(error stop-postgres must be invoked alone)
endif
else
include $(POSTGRES_MK)

$(POSTGRES_MK): scripts/ensure_postgres.py FORCE
	uv run --frozen python scripts/ensure_postgres.py --makefile $@

.PHONY: FORCE ensure-postgres
FORCE:
ensure-postgres: $(POSTGRES_MK)
endif

.PHONY: stop-postgres
stop-postgres:
	uv run --frozen python scripts/ensure_postgres.py --stop
```

Leave `all: ensure-postgres css migrate` and all later targets unchanged.

- [ ] **Step 4: Re-run the focused tests and verify GREEN**

Run through the required hidden-process wrapper:

```text
make test ARGS="tests/test_makefile_postgres.py -v"
```

Expected: both tests pass. The alternate `postgres.mk` path remains absent.

- [ ] **Step 5: Commit the Make lifecycle boundary**

```bash
git add Makefile tests/test_makefile_postgres.py
git commit -m "build: isolate PostgreSQL shutdown target"
```

### Task 2: Add non-provisioning managed-cluster shutdown

**Files:**
- Modify: `scripts/ensure_postgres.py`
- Modify: `tests/test_ensure_postgres.py`

**Interfaces:**
- Consumes: `Tools`, the worktree cache path, PostgreSQL's `pg_ctl status` exit code `3` for a stopped server, and the already-extracted fallback directory.
- Produces: `existing_tools(cache: Path) -> Tools | None`, `stop_cluster(tools: Tools, data_dir: Path) -> bool`, and `stop(cache: Path) -> None`; CLI operation `--stop`.

- [ ] **Step 1: Write the failing existing-tool discovery test**

```python
def test_existing_tools_reuse_extracted_fallback_without_provisioning(
    harness, monkeypatch, tmp_path
):
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    destinations: list[Path] = []
    monkeypatch.setattr(harness, "path_tools", lambda: None)
    monkeypatch.setattr(
        harness,
        "_tools_from_fallback_destination",
        lambda destination: destinations.append(destination) or tools,
    )
    monkeypatch.setattr(
        harness,
        "fallback_tools",
        lambda cache: pytest.fail("stop must not provision fallback tools"),
    )

    assert harness.existing_tools(tmp_path) is tools
    assert destinations == [tmp_path / "postgres-binaries" / harness.FALLBACK_VERSION]
```

- [ ] **Step 2: Run the discovery test and verify RED**

Run through the required hidden-process wrapper:

```text
make test ARGS="tests/test_ensure_postgres.py::test_existing_tools_reuse_extracted_fallback_without_provisioning -v"
```

Expected: FAIL because `existing_tools` does not exist.

- [ ] **Step 3: Implement non-provisioning existing-tool discovery**

Add after `fallback_tools`:

```python
def existing_tools(cache: Path) -> Tools | None:
    return path_tools() or _tools_from_fallback_destination(
        cache / "postgres-binaries" / FALLBACK_VERSION
    )
```

- [ ] **Step 4: Re-run the discovery test and verify GREEN**

Run the same focused command. Expected: PASS with no call to `fallback_tools`.

- [ ] **Step 5: Write the failing missing-cluster test**

```python
def test_stop_missing_cluster_is_a_noop_without_tool_discovery(
    harness, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        harness,
        "existing_tools",
        lambda cache: pytest.fail("missing cluster must not discover tools"),
    )

    harness.stop(tmp_path)

    assert "No worktree-managed PostgreSQL cluster exists" in capsys.readouterr().err
```

- [ ] **Step 6: Run the missing-cluster test and verify RED**

Run through the required hidden-process wrapper:

```text
make test ARGS="tests/test_ensure_postgres.py::test_stop_missing_cluster_is_a_noop_without_tool_discovery -v"
```

Expected: FAIL because `stop` does not exist.

- [ ] **Step 7: Implement the missing-cluster no-op**

Add after `start_cluster`:

```python
def stop(cache: Path) -> None:
    data_dir = cache / "postgres" / "data"
    if not data_dir.exists():
        print("==> No worktree-managed PostgreSQL cluster exists.", file=sys.stderr)
        return
```

- [ ] **Step 8: Re-run the missing-cluster test and verify GREEN**

Run the same focused command. Expected: PASS.

- [ ] **Step 9: Write the failing already-stopped test**

```python
def test_stop_initialized_cluster_without_pid_is_a_noop(
    harness, monkeypatch, tmp_path, capsys
):
    (tmp_path / "postgres" / "data").mkdir(parents=True)
    monkeypatch.setattr(
        harness,
        "existing_tools",
        lambda cache: pytest.fail("stopped cluster must not discover tools"),
    )

    harness.stop(tmp_path)

    assert "already stopped" in capsys.readouterr().err
```

- [ ] **Step 10: Run the already-stopped test and verify RED**

Run through the required hidden-process wrapper:

```text
make test ARGS="tests/test_ensure_postgres.py::test_stop_initialized_cluster_without_pid_is_a_noop -v"
```

Expected: FAIL because `stop` continues past the existing data directory.

- [ ] **Step 11: Implement the PID-metadata no-op**

Extend `stop`:

```python
    if not (data_dir / "postmaster.pid").exists():
        print(
            "==> Worktree-managed PostgreSQL cluster is already stopped.",
            file=sys.stderr,
        )
        return
```

- [ ] **Step 12: Re-run the already-stopped test and verify GREEN**

Run the same focused command. Expected: PASS.

- [ ] **Step 13: Write the failing running-cluster and failure tests**

```python
def test_stop_running_cluster_uses_fast_waiting_pg_ctl(
    harness, monkeypatch, tmp_path, capsys
):
    data_dir = tmp_path / "postgres" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "postmaster.pid").write_text("12345\n")
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    status_commands: list[list[str]] = []
    stop_commands: list[list[str]] = []
    monkeypatch.setattr(harness, "existing_tools", lambda cache: tools)

    def status(args, **kwargs):
        status_commands.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(harness.subprocess, "run", status)
    monkeypatch.setattr(
        harness, "run", lambda args, **kwargs: stop_commands.append(args)
    )

    harness.stop(tmp_path)

    assert status_commands == [[str(tools.pg_ctl), "status", "-D", str(data_dir)]]
    assert stop_commands == [
        [str(tools.pg_ctl), "stop", "-D", str(data_dir), "-m", "fast", "-w"]
    ]
    assert "PostgreSQL stopped" in capsys.readouterr().err


def test_stop_running_cluster_requires_existing_tools(harness, monkeypatch, tmp_path):
    data_dir = tmp_path / "postgres" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "postmaster.pid").write_text("12345\n")
    monkeypatch.setattr(harness, "existing_tools", lambda cache: None)
    monkeypatch.setattr(
        harness,
        "fallback_tools",
        lambda cache: pytest.fail("stop must not provision fallback tools"),
    )

    with pytest.raises(harness.HarnessError, match="without provisioning"):
        harness.stop(tmp_path)


def test_stop_cluster_rejects_unexpected_status_failure(harness, monkeypatch, tmp_path):
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    monkeypatch.setattr(
        harness.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 1, stdout="", stderr="permission denied"
        ),
    )

    with pytest.raises(harness.HarnessError, match="permission denied"):
        harness.stop_cluster(tools, tmp_path / "data")


def test_stop_cluster_propagates_shutdown_failure(harness, monkeypatch, tmp_path):
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    monkeypatch.setattr(
        harness.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout="", stderr=""
        ),
    )
    failure = subprocess.CalledProcessError(1, [str(tools.pg_ctl), "stop"])
    monkeypatch.setattr(
        harness, "run", lambda *args, **kwargs: (_ for _ in ()).throw(failure)
    )

    with pytest.raises(subprocess.CalledProcessError):
        harness.stop_cluster(tools, tmp_path / "data")
```

- [ ] **Step 14: Run the running-cluster and failure tests and verify RED**

Run through the required hidden-process wrapper:

```text
make test ARGS="tests/test_ensure_postgres.py -k 'stop_running_cluster or rejects_unexpected_status or propagates_shutdown_failure' -v"
```

Expected: all four tests fail because tool enforcement, status, and shutdown are not implemented.

- [ ] **Step 15: Implement checked status and fast waiting shutdown**

Add before `stop`:

```python
def stop_cluster(tools: Tools, data_dir: Path) -> bool:
    status = subprocess.run(
        [str(tools.pg_ctl), "status", "-D", str(data_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        detail = (status.stderr or status.stdout).strip()
        message = "Could not determine managed PostgreSQL cluster status"
        if detail:
            message += f": {detail}"
        raise HarnessError(message)
    run(
        [
            str(tools.pg_ctl),
            "stop",
            "-D",
            str(data_dir),
            "-m",
            "fast",
            "-w",
        ]
    )
    return True
```

Complete `stop` with:

```python
    tools = existing_tools(cache)
    if tools is None:
        raise HarnessError(
            "PostgreSQL 18 tools are unavailable; cannot stop the managed "
            "cluster without provisioning them."
        )
    if stop_cluster(tools, data_dir):
        print("==> Worktree-managed PostgreSQL stopped.", file=sys.stderr)
    else:
        print(
            "==> Worktree-managed PostgreSQL cluster is already stopped.",
            file=sys.stderr,
        )
```

- [ ] **Step 16: Re-run the running-cluster and failure tests and verify GREEN**

Run the same focused command. Expected: all three pass, including the exact
data directory, `fast`, `-w`, and failure propagation assertions.

- [ ] **Step 17: Write the failing stopped-status test**

```python
def test_stop_cluster_treats_pg_ctl_not_running_as_a_noop(
    harness, monkeypatch, tmp_path
):
    tools = harness.Tools(*(tmp_path / name for name in harness.TOOL_NAMES))
    monkeypatch.setattr(
        harness.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 3, stdout="", stderr=""
        ),
    )
    monkeypatch.setattr(
        harness, "run", lambda *args, **kwargs: pytest.fail("must not stop twice")
    )

    assert harness.stop_cluster(tools, tmp_path / "data") is False
```

- [ ] **Step 18: Run the stopped-status test and verify RED**

Run through the required hidden-process wrapper:

```text
make test ARGS="tests/test_ensure_postgres.py::test_stop_cluster_treats_pg_ctl_not_running_as_a_noop -v"
```

Expected: FAIL because status `3` is still treated as an unexpected error.

- [ ] **Step 19: Implement and verify stopped-status handling**

Add near the harness constants:

```python
PG_CTL_NOT_RUNNING = 3
```

Add before the unexpected-status branch in `stop_cluster`:

```python
    if status.returncode == PG_CTL_NOT_RUNNING:
        return False
```

Run the same focused command. Expected: PASS and no shutdown command.

- [ ] **Step 20: Write the failing CLI routing test**

```python
def test_stop_cli_routes_to_shutdown_without_ensuring(harness, monkeypatch, tmp_path):
    stopped: list[Path] = []
    monkeypatch.setattr(harness.sys, "argv", [str(HARNESS_PATH), "--stop"])
    monkeypatch.setattr(harness, "stop", stopped.append)
    monkeypatch.setattr(
        harness, "ensure", lambda cache: pytest.fail("stop must not ensure")
    )

    harness.main()

    assert stopped == [HARNESS_PATH.parents[1] / ".cache"]
```

- [ ] **Step 21: Run the CLI test and verify RED**

Run through the required hidden-process wrapper:

```text
make test ARGS="tests/test_ensure_postgres.py::test_stop_cli_routes_to_shutdown_without_ensuring -v"
```

Expected: FAIL because the parser still requires `--makefile`.

- [ ] **Step 22: Implement mutually exclusive CLI routing**

Replace the parser setup and operation selection in `main` with:

```python
def main() -> None:
    parser = argparse.ArgumentParser()
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--makefile", type=Path)
    operation.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    cache = Path(__file__).parents[1] / ".cache"
    try:
        if args.stop:
            stop(cache)
            return
        if args.makefile is None:
            raise HarnessError("No generated Makefile path was supplied.")
        url = ensure(cache)
        args.makefile.parent.mkdir(parents=True, exist_ok=True)
        contents = makefile_contents(url)
        if not args.makefile.is_file() or args.makefile.read_text() != contents:
            args.makefile.write_text(contents)
    except (HarnessError, subprocess.CalledProcessError, OSError) as exc:
        operation_name = "stop-postgres" if args.stop else "ensure-postgres"
        raise SystemExit(f"{operation_name}: {exc}") from exc
```

Update the module docstring from provisioning-only language to:

```python
"""Manage the ignored PostgreSQL 18 development cluster used by Make."""
```

- [ ] **Step 23: Run all PostgreSQL harness tests and verify GREEN**

Run through the required hidden-process wrapper:

```text
make test ARGS="tests/test_ensure_postgres.py tests/test_makefile_postgres.py -v"
```

Expected: all focused tests pass with no warnings or errors.

- [ ] **Step 24: Commit the managed shutdown behavior**

```bash
git add scripts/ensure_postgres.py tests/test_ensure_postgres.py
git commit -m "build: stop worktree-managed PostgreSQL"
```

### Task 3: Document cleanup and run repository verification

**Files:**
- Modify: `README.md`
- Modify: `docs/database.md`

**Interfaces:**
- Consumes: the implemented standalone `make stop-postgres` command.
- Produces: discoverable worktree-cleanup instructions and explicit local-versus-external database behavior.

- [ ] **Step 1: Update the README development workflow**

After the development-server paragraph, add:

```markdown
Before removing a development worktree, run `make stop-postgres`. The command
waits for the worktree-managed PostgreSQL server to stop and succeeds when the
cluster is already stopped or was never initialized.
```

- [ ] **Step 2: Document the managed cluster lifecycle**

Extend the development paragraph in `docs/database.md` with:

```markdown
Run `make stop-postgres` before removing a development worktree. It performs a
fast shutdown of only the cluster under that worktree's
`.cache/postgres/data`, waits for completion, and is safe to repeat. It does
not initialize a missing cluster or stop a server supplied through
`DATABASE_URL`.
```

- [ ] **Step 3: Run formatting and focused verification**

Run through the required hidden-process wrapper:

```text
make check-fast
```

Expected: PASS with the Makefile-selected parallel worker count.

- [ ] **Step 4: Commit the documentation**

```bash
git add README.md docs/database.md
git commit -m "docs: explain managed PostgreSQL cleanup"
```

- [ ] **Step 5: Exercise the real shutdown command twice**

Run through the required hidden-process wrapper:

```text
make stop-postgres
make stop-postgres
```

Expected: the first invocation reports a completed fast shutdown of the
current worktree cluster; the second reports that it is already stopped and
also exits zero. Neither invocation remakes `.cache/postgres.mk`.

- [ ] **Step 6: Run the complete verification gate**

Run through the required hidden-process wrapper:

```text
make check
```

Expected: PASS with the Makefile-selected parallel worker count. The normal
gate may restart the managed cluster after the explicit idempotency exercise.

- [ ] **Step 7: Inspect the final scope**

```bash
git status --short
git diff --check 89706da..HEAD
git log -5 --oneline
```

Expected: no uncommitted implementation changes, no whitespace errors, and
only the specification, plan, Make boundary, helper/tests, and documentation
commits for issue #835.
