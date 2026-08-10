# PG-13 PostgreSQL pytest-xdist topology implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove and permanently regression-test that pytest-xdist gives PostgreSQL-backed test workers isolated disposable databases.

**Architecture:** Retain pytest-django's native `django_db_modify_db_settings_xdist_suffix` lifecycle. A focused outer pytest test creates a miniature Django project and runs it under two child xdist workers; each child records its live connection's database name. The outer assertion proves the two workers used distinct `test_…_gwN` databases and never used the configured development database.

**Tech Stack:** Python 3.14, Django 6, pytest 9, pytest-django 4.12, pytest-xdist 3.8, PostgreSQL 17, GNU Make.

## Global Constraints

- Run all project verification through Make targets; use `ARGS` only for focused `make test` runs.
- Preserve Makefile's default `PYTEST_WORKERS`; do not set it to `0` except for explicit debugging.
- GitHub Actions stays serial: `CI` selects `PYTEST_WORKERS=0`; #616 owns CI's PostgreSQL move.
- Use the existing `DATABASE_URL` and `make ensure-postgres` contract; add no database URL parser, custom xdist suffix hook, schema router, service, migration, or Compose change.
- On Windows, run Make test targets through the managed hidden process and wait for its final log and exit status.

---

### Task 1: Add a real two-worker PostgreSQL topology probe

**Files:**
- Create: `tests/test_pytest_xdist_topology.py`

**Interfaces:**
- Consumes: `pytester` (pytest's isolated child-project fixture), `DATABASE_URL`, Django's `database_settings_from_url(url)`, pytest-django's native xdist suffix fixture.
- Produces: `test_two_xdist_workers_receive_distinct_postgresql_test_databases(pytester, tmp_path)`; the test reads one JSON record per child worker with `worker_id`, `vendor`, `configured_name`, and `live_name`.

- [ ] **Step 1: Write the failing topology-probe test**

Create `tests/test_pytest_xdist_topology.py` with `pytest_plugins = ("pytester",)`. Use `pytester.makepyfile()` to create a child `settings.py` whose only app is `django.contrib.contenttypes`, whose `DATABASES["default"]` is the result of `database_settings_from_url(os.environ["DATABASE_URL"])`, and whose `TEST["NAME"]` is `os.environ["PG_XDIST_TEST_NAME"]`, set by the outer test to a unique `test_pg_xdist_probe_<uuid>` name. Use a child `conftest.py` containing:

```python
import os


def pytest_configure(config):
    worker = getattr(config, "workerinput", {}).get("workerid", "controller")
    os.environ["PYTEST_XDIST_WORKER"] = worker
```

Use a child `test_probe.py` containing:

```python
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
        report.write(json.dumps(record) + "\n")
```

Set `PG_XDIST_CONFIGURED_NAME` to the development database component parsed from `DATABASE_URL` and `PG_XDIST_REPORT` to a `tmp_path` file with `monkeypatch.setenv()` before `pytester.runpytest_subprocess("-n", "2", "--dist=each")`; the child inherits that environment. Assert exactly two records, worker IDs `{\"gw0\", \"gw1\"}`, vendor `postgresql`, distinct `live_name` values, each name starts with the unique `PG_XDIST_TEST_NAME`, ends with its worker ID, and neither equals `configured_name`.

- [ ] **Step 2: Run the focused test to verify it fails before the probe exists**

Run: `make test ARGS="tests/test_pytest_xdist_topology.py -q"`

Expected: FAIL during collection because `tests/test_pytest_xdist_topology.py` does not yet exist.

- [ ] **Step 3: Implement the minimal self-contained child project and assertions**

Add only `tests/test_pytest_xdist_topology.py`. Keep the child project independent of Timetracker models and migrations so the assertion isolates pytest-django's database identity behavior. Use `--dist=each` so the sole child probe test runs once on each of exactly two workers. Do not introduce a project `conftest.py` hook: pytest-django's built-in xdist suffix fixture is the behavior under test.

- [ ] **Step 4: Run the focused test with Make's normal worker policy**

Run: `make test ARGS="tests/test_pytest_xdist_topology.py -q"`

Expected: PASS. The outer run uses the Makefile's normal local worker default; the inner run reports `gw0` and `gw1` on separate disposable PostgreSQL databases.

- [ ] **Step 5: Run the existing live-server concurrency regression**

Run: `make test ARGS="tests/test_live_server_db_concurrency.py -q"`

Expected: PASS with the Makefile-selected worker count, confirming the pre-existing threaded live-server safety coverage remains PostgreSQL-backed.

- [ ] **Step 6: Commit the implementation**

```bash
git add tests/test_pytest_xdist_topology.py
git commit -m "test: cover PostgreSQL xdist database isolation"
```

### Task 2: Verify the normal topology and document its evidence

**Files:**
- Modify: `docs/superpowers/specs/2026-08-10-pg-13-postgresql-xdist-design.md`

**Interfaces:**
- Consumes: the two-worker probe from Task 1 and the existing `make check` target.
- Produces: a concise verification record in the issue-level design naming the actual native mechanism, two-worker probe, serial-CI boundary, and complete gate.

- [ ] **Step 1: Add the focused verification record to the design specification**

Append a `## Implementation evidence` section naming: pytest-django's native `django_db_modify_db_settings_xdist_suffix` behavior, the two-worker child probe, the live-server concurrency regression, and the fact that CI remains `-n 0` by policy. Do not claim a pass until the commands below have completed.

- [ ] **Step 2: Run the complete project gate**

Run: `make check`

Expected: PASS with the Makefile-selected local parallel worker count. On Windows use the managed hidden-process procedure; do not force serial mode.

- [ ] **Step 3: Check the final diff and status**

Run:

```bash
git diff --check HEAD~1
git status --short
```

Expected: no whitespace errors and only the evidence-documentation edit unstaged.

- [ ] **Step 4: Commit the evidence record**

```bash
git add docs/superpowers/specs/2026-08-10-pg-13-postgresql-xdist-design.md
git commit -m "docs: record PostgreSQL xdist verification"
```
