# PG-13 PostgreSQL pytest-xdist topology implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every PostgreSQL pytest-xdist worker a collision-resistant, bounded test-database name across concurrent runs.

**Architecture:** Add `timetracker.pytest_topology`, an importable local pytest plugin loaded by root `conftest.py`. It overrides pytest-django's documented xdist suffix fixture, explicitly waits for pytest-django's tox suffix fixture, and derives a 59-character ASCII `TEST.NAME` from 48 bits of base-name hash, 128 bits of xdist `testrun_uid` hash, and 32 bits of worker-ID hash. The real plugin is loaded by both project test trees and the child integration probe.

**Tech Stack:** Python 3.14, Django 6, pytest 9, pytest-django 4.12, pytest-xdist 3.8, PostgreSQL 17.

## Global Constraints

- Preserve the Makefile's default `PYTEST_WORKERS`; CI remains serial at `-n 0`.
- Add no launcher, Makefile-generated ID, migration, service, schema router, or Compose change.
- PostgreSQL names must be at most 63 UTF-8 bytes; generated names are ASCII and exactly 59 bytes.
- Run verification through Make; ensure no other pytest process is active before the one full gate.

---

### Task 1: Write topology regressions

**Files:**

- Modify: `tests/test_pytest_xdist_topology.py`
- Test: `timetracker/pytest_topology.py`

- [ ] **Step 1: Add failing pure name-contract tests**

Test `test_database_name(base_name, run_uid, worker_id)` with literal invariants: output is ASCII and 59 characters; same inputs are deterministic; changing any input changes the name; two long Unicode base names do not create a name longer than 63 bytes. Assert `test_` prefix and the three fixed-size hash components, rather than duplicating the hash implementation in the expectation.

- [ ] **Step 2: Replace the child probe with the real plugin**

Create the pytester child `conftest.py` with:

```python
pytest_plugins = ("timetracker.pytest_topology",)
```

Run it with `-n 2 --dist=each --testrunuid topology-run-a`. Each worker writes one JSON document to `Path(PG_XDIST_REPORT_DIR) / f"{worker_id}.json"`; the parent reads `gw0.json` and `gw1.json`. Assert the records have PostgreSQL live connections, one shared `testrun_uid`, distinct live names, and neither live name equals the development name.

- [ ] **Step 3: Establish RED**

Run: `make test ARGS="tests/test_pytest_xdist_topology.py -q"`

Expected: FAIL because the importable plugin and naming helper do not exist.

### Task 2: Add the globally loaded plugin

**Files:**

- Create: `conftest.py`
- Create: `timetracker/pytest_topology.py`

- [ ] **Step 1: Load the plugin at repository scope**

Create root `conftest.py`:

```python
pytest_plugins = ("timetracker.pytest_topology",)
```

This makes the fixture visible to both `tests/` and `e2e/`; do not move existing `tests/conftest.py` fixtures.

- [ ] **Step 2: Implement a bounded ASCII name**

In `timetracker/pytest_topology.py`, define:

```python
def test_database_name(base_name: str, run_uid: str, worker_id: str) -> str:
    base_hash = hashlib.sha256(base_name.encode()).hexdigest()[:12]
    run_hash = hashlib.sha256(run_uid.encode()).hexdigest()[:32]
    worker_hash = hashlib.sha256(worker_id.encode()).hexdigest()[:8]
    return f"test_{base_hash}_{run_hash}_{worker_hash}"
```

- [ ] **Step 3: Implement the documented fixture with explicit tox order**

Add:

```python
@pytest.fixture(scope="session")
def django_db_modify_db_settings_xdist_suffix(
    request, django_db_modify_db_settings_tox_suffix, testrun_uid, worker_id
):
    if not hasattr(request.config, "workerinput"):
        return
    for database in settings.DATABASES.values():
        if database["ENGINE"] == "django.db.backends.sqlite3":
            continue
        test_name = database.setdefault("TEST", {}).get("NAME")
        if not test_name:
            test_name = f"test_{database['NAME']}"
        if test_name != ":memory:":
            database["TEST"]["NAME"] = test_database_name(
                test_name, testrun_uid, worker_id
            )
```

Import `hashlib`, `pytest`, and `django.conf.settings`. The tox dependency must remain in the signature: it forces tox suffix application before bounded hashing. The `request.config.workerinput` check prevents inherited xdist environment from changing a serial nested process.

- [ ] **Step 4: Run focused verification and commit**

Run:

```bash
make test ARGS="tests/test_pytest_xdist_topology.py -q"
make test ARGS="tests/test_live_server_db_concurrency.py -q"
```

Expected: both PASS at Make's default local worker count.

Commit:

```bash
git add conftest.py timetracker/pytest_topology.py tests/test_pytest_xdist_topology.py
git commit -m "test: namespace PostgreSQL xdist databases by run"
```

### Task 3: Record evidence and verify globally

**Files:**

- Modify: `docs/superpowers/specs/2026-08-10-pg-13-postgresql-xdist-design.md`

- [ ] **Step 1: Record the plugin, two-worker probe, e2e visibility, and serial-CI boundary**

- [ ] **Step 2: Run one managed full gate**

Run: `make check`

Expected: PASS with the default worker count and no overlapping pytest process.

- [ ] **Step 3: Run `git diff --check HEAD~1`, inspect `git status --short`, and commit the evidence**

```bash
git add docs/superpowers/specs/2026-08-10-pg-13-postgresql-xdist-design.md
git commit -m "docs: record PostgreSQL xdist verification"
```
