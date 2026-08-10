# PG-13 PostgreSQL pytest-xdist topology implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each PostgreSQL pytest-xdist invocation a unique, disposable worker-database namespace.

**Architecture:** Use pytest-xdist's supported, run-wide `PYTEST_XDIST_TESTRUNUID` and pytest-django's supported `django_db_modify_db_settings_xdist_suffix` fixture. The fixture derives a bounded PostgreSQL test name from the ordinary Django test name, a stable hash of the xdist run UID, and the worker ID. Django continues to create, migrate, and tear down the databases.

**Tech Stack:** Python 3.14, Django 6, pytest 9, pytest-django 4.12, pytest-xdist 3.8, PostgreSQL 17, GNU Make.

## Global Constraints

- Preserve Makefile's default `PYTEST_WORKERS`; do not set it to `0` except for explicit debugging.
- CI remains serial (`PYTEST_WORKERS=0`); #616 owns the CI PostgreSQL migration.
- Do not add a test launcher, Makefile-generated run ID, database service, schema router, migration, or Compose change.
- PostgreSQL identifiers are at most 63 characters; namespace construction must stay within that limit for arbitrary configured database names and `--testrunuid` values.
- Run all verification through Make; on Windows, use the managed hidden process and wait for its final log and exit status.

---

### Task 1: Write the run-and-worker topology regressions

**Files:**

- Modify: `tests/test_pytest_xdist_topology.py`

**Interfaces:**

- Consumes: `_xdist_test_database_name(base_name: str, run_uid: str, worker_id: str) -> str` from `tests/conftest.py`.
- Produces: deterministic naming coverage and a real two-worker PostgreSQL probe using the repository's actual test fixture.

- [ ] **Step 1: Add failing deterministic name assertions**

Load `tests/conftest.py` by path, as `tests/test_ensure_postgres.py` does. Assert that one run UID produces distinct `gw0` and `gw1` names; distinct run UIDs produce distinct names; and a long base name results in a name no longer than 63 characters. The fixed expected name for `("test_timetracker", "run-a", "gw0")` is `test_timetracker_66b1eb530fb7_gw0`.

- [ ] **Step 2: Make the child probe use the real fixture**

In the pytester child `conftest.py`, execute `runpy.run_path(os.environ["TIMETRACKER_TESTS_CONFTEST"])`. The outer test sets that variable to the repository `tests/conftest.py` path. Run the child with `-n 2 --dist=each --testrunuid topology-run-a` and record `PYTEST_XDIST_TESTRUNUID`, `PYTEST_XDIST_WORKER`, `connection.vendor`, development name, and live name. Assert both records carry `topology-run-a`, have workers `gw0` and `gw1`, use PostgreSQL, end in their worker IDs, include the `topology-run-a` hash, differ from each other, and differ from the development database.

- [ ] **Step 3: Run the focused test to establish RED**

Run: `make test ARGS="tests/test_pytest_xdist_topology.py -q"`

Expected: FAIL because the helper and overriding fixture do not exist, and default pytest-django names omit the run UID.

### Task 2: Apply the xdist run UID through pytest-django

**Files:**

- Modify: `tests/conftest.py`

**Interfaces:**

- Produces `_xdist_test_database_name(base_name, run_uid, worker_id) -> str` and session fixture `django_db_modify_db_settings_xdist_suffix()`.
- Consumes `PYTEST_XDIST_TESTRUNUID`, `PYTEST_XDIST_WORKER`, and `django.conf.settings.DATABASES`.

- [ ] **Step 1: Implement the bounded helper**

Add `hashlib`, `os`, and `django.conf.settings`. Add:

```python
def _xdist_test_database_name(base_name: str, run_uid: str, worker_id: str) -> str:
    run_hash = hashlib.sha256(run_uid.encode()).hexdigest()[:12]
    suffix = f"_{run_hash}_{worker_id}"
    return f"{base_name[: 63 - len(suffix)]}{suffix}"
```

- [ ] **Step 2: Override only the xdist suffix fixture**

Add this session fixture:

```python
@pytest.fixture(scope="session")
def django_db_modify_db_settings_xdist_suffix() -> None:
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    run_uid = os.environ.get("PYTEST_XDIST_TESTRUNUID")
    if not worker_id or not run_uid:
        return
    for database in settings.DATABASES.values():
        if database["ENGINE"] == "django.db.backends.sqlite3":
            continue
        test_name = database.setdefault("TEST", {}).get("NAME")
        if not test_name:
            test_name = f"test_{database['NAME']}"
        if test_name != ":memory:":
            database["TEST"]["NAME"] = _xdist_test_database_name(
                test_name, run_uid, worker_id
            )
```

This preserves pytest-django's fixture chain, including the tox suffix fixture, while replacing only the fixed xdist worker suffix. Serial runs have neither xdist variable and retain Django's ordinary test name.

- [ ] **Step 3: Run focused tests and live-server regression**

Run:

```bash
make test ARGS="tests/test_pytest_xdist_topology.py -q"
make test ARGS="tests/test_live_server_db_concurrency.py -q"
```

Expected: both PASS with Make's normal local worker count.

- [ ] **Step 4: Commit the topology implementation**

```bash
git add tests/conftest.py tests/test_pytest_xdist_topology.py
git commit -m "test: namespace PostgreSQL xdist databases by run"
```

### Task 3: Record evidence and complete the gate

**Files:**

- Modify: `docs/superpowers/specs/2026-08-10-pg-13-postgresql-xdist-design.md`

- [ ] **Step 1: Record evidence after focused checks pass**

Append a concise section naming `PYTEST_XDIST_TESTRUNUID`, the pytest-django fixture override, the real two-worker probe, the live-server regression, and the unchanged serial-CI boundary.

- [ ] **Step 2: Run one managed full gate**

Run: `make check`

Expected: PASS with the Makefile-selected worker count. Before starting, ensure no other `make check` or pytest process is active; wait for this process tree's final exit status before another invocation.

- [ ] **Step 3: Check final diff and commit evidence**

Run `git diff --check HEAD~1` and `git status --short`, then commit the evidence:

```bash
git add docs/superpowers/specs/2026-08-10-pg-13-postgresql-xdist-design.md
git commit -m "docs: record PostgreSQL xdist verification"
```
