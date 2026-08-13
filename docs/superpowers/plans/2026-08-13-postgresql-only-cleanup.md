# PostgreSQL-only cleanup implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the active SQLite rendering, test topology, locking workarounds, portability audit, and stale backend assumptions left after Timetracker's PostgreSQL cutover.

**Architecture:** PostgreSQL 18 remains the sole runtime and test backend. Keep the expression classes imported by the squashed migration, but remove their alternate backend rendering; delete tests and fixtures whose only purpose was SQLite locking or portability; express surviving behavior directly in PostgreSQL terms.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, psycopg 3, pytest/pytest-django/pytest-xdist, Playwright, GNU Make.

## Global Constraints

- Complete this plan before `docs/superpowers/plans/2026-08-13-uuidv7-identity-foundation.md`.
- Keep SQLite removal separate from UUIDv7 implementation. Do not squash these cleanup commits into later UUIDv7 commits.
- PostgreSQL 18 is the only supported runtime and test backend.
- Preserve `DatabaseDurationSum` and `DatabaseDateDifference` because the squashed migration imports them.
- Do not rewrite `CHANGELOG.md` or completed files under `docs/superpowers/`; those accurately record project history.
- Do not remove ordinary Python uses of `strftime()`; they are unrelated to database compatibility.
- Do not change staging machine count while removing its obsolete database rationale.
- Keep the Makefile's default `PYTEST_WORKERS`. On Windows Codex desktop, run `make check`, `make check-fast`, and test targets through a managed hidden process and wait for its final log and exit status.
- Do not modify or stage the existing untracked `.pnpm-store/` directory.

## File Structure

- Modify `games/expressions.py`: retain PostgreSQL expression behavior and remove alternate SQL rendering.
- Modify `games/models.py` and `common/criteria.py`: state current SQL/PostgreSQL semantics without former-backend commentary.
- Modify `e2e/conftest.py`: remove the request-quiescence fixture and imports used only by it.
- Delete `e2e/test_teardown_quiescence_e2e.py`: remove the former-backend flush-lock regression.
- Delete `tests/test_live_server_db_concurrency.py`: remove the former-backend shared-connection/locking regression.
- Delete `tests/test_migration_portability.py`: remove the temporary static portability substitute superseded by PostgreSQL migration execution.
- Modify `timetracker/pytest_topology.py`: require PostgreSQL positively when applying xdist database names.
- Modify active tests and `.github/workflows/staging.yml`: remove stale backend-specific explanations while preserving their surviving behavior.

---

### Task 1: Remove alternate database rendering from runtime expressions

**Files:**
- Modify: `games/expressions.py`
- Modify: `games/models.py`
- Modify: `common/criteria.py`
- Test: `tests/test_postgresql_reverification.py`
- Test: `tests/test_sentinel_removal.py`

**Interfaces:**
- Consumes: Django's PostgreSQL compilation of `CombinedExpression`.
- Produces: unchanged `DatabaseDurationSum(lhs, rhs)` and `DatabaseDateDifference(lhs, rhs)` import paths with PostgreSQL-only behavior.

- [ ] **Step 1: Establish the PostgreSQL expression baseline**

Run through a managed hidden process on Windows:

```text
make test-fast ARGS="tests/test_postgresql_reverification.py tests/test_sentinel_removal.py -x -v"
```

Expected: PASS before cleanup; the generated duration/date expressions and conditional uniqueness behavior already execute on PostgreSQL.

- [ ] **Step 2: Remove the alternate renderer while retaining migration-stable classes**

Replace the class documentation in `games/expressions.py` and delete `DatabaseDateDifference.as_sqlite()`:

```python
class DatabaseDurationSum(CombinedExpression):
    """Add two PostgreSQL intervals with an explicit DurationField result."""

    def __init__(self, lhs, rhs):
        super().__init__(lhs, "+", rhs, output_field=models.DurationField())

    def resolve_expression(
        self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False
    ):
        return Expression.resolve_expression(
            self, query, allow_joins, reuse, summarize, for_save
        )


class DatabaseDateDifference(CombinedExpression):
    """Subtract two PostgreSQL dates as a whole-day integer."""

    def __init__(self, lhs, rhs):
        super().__init__(lhs, "-", rhs, output_field=models.IntegerField())

    def resolve_expression(
        self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False
    ):
        return Expression.resolve_expression(
            self, query, allow_joins, reuse, summarize, for_save
        )
```

Do not rename either class: `games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py` imports both paths.

- [ ] **Step 3: Rewrite active-source comments around the surviving semantics**

In `games/models.py`, replace the conditional uniqueness comment with:

```python
# SQL NULLs are distinct under an ordinary unique constraint, so this
# preserves uniqueness for games whose platform is absent.
```

In `common/criteria.py`, replace the regex comment with:

```python
# PostgreSQL compiles a regex modifier's value during query execution.
# Validate it while parsing so invalid or pathological patterns become a
# FilterError instead of failing or monopolizing a request worker.
```

- [ ] **Step 4: Verify PostgreSQL behavior and migration drift**

Run through managed hidden processes on Windows:

```text
make test-fast ARGS="tests/test_postgresql_reverification.py tests/test_sentinel_removal.py -x -v"
make check-migrations
```

Expected: PASS and `No changes detected`; deleting the renderer changes no PostgreSQL DDL or model state.

- [ ] **Step 5: Commit the runtime cleanup atomically**

```text
git add games/expressions.py games/models.py common/criteria.py
git commit -m "refactor: remove SQLite expression compatibility"
```

---

### Task 2: Remove former-backend locking fixtures and regressions

**Files:**
- Modify: `e2e/conftest.py`
- Delete: `e2e/test_teardown_quiescence_e2e.py`
- Delete: `tests/test_live_server_db_concurrency.py`

**Interfaces:**
- Consumes: pytest-django's ordinary PostgreSQL test database and live-server lifecycle.
- Produces: no custom browser request-draining teardown and no shared-cache/locking regression surface.

- [ ] **Step 1: Record the relevant E2E baseline**

Run through a managed hidden process on Windows:

```text
make test-e2e
```

Expected: PASS before removal. Retain the final log so post-removal failures can be compared with the baseline.

- [ ] **Step 2: Delete the request-quiescence workaround**

Remove the complete `_flush_waits_for_inflight_requests` fixture from
`e2e/conftest.py`, from its `@pytest.fixture(autouse=True)` decorator through
the final `page.wait_for_timeout(25)` call.

Also remove the now-unused imports:

```python
import time
from playwright.sync_api import Request
```

Keep `_reset_settings_caches()` and every browser-discovery fixture unchanged.

- [ ] **Step 3: Delete regressions whose claimed failure mode no longer exists**

Delete both files in full:

```text
e2e/test_teardown_quiescence_e2e.py
tests/test_live_server_db_concurrency.py
```

Do not transplant their sleeps, request counters, shared-cache assertions, or lock timing into PostgreSQL tests. Existing E2E coverage continues exercising the actual browser/live-server paths.

- [ ] **Step 4: Verify the E2E suite without the workaround**

Run through managed hidden processes on Windows:

```text
make test-e2e
make test-fast ARGS="tests/test_health.py tests/test_pytest_xdist_topology.py -x -v"
```

Expected: PASS. The E2E teardown completes with ordinary pytest-django/PostgreSQL behavior and xdist still assigns isolated databases.

- [ ] **Step 5: Commit the test-lifecycle cleanup atomically**

```text
git add e2e/conftest.py e2e/test_teardown_quiescence_e2e.py tests/test_live_server_db_concurrency.py
git commit -m "test: remove SQLite locking workarounds"
```

---

### Task 3: Remove the portability audit and all remaining active assumptions

**Files:**
- Delete: `tests/test_migration_portability.py`
- Modify: `timetracker/pytest_topology.py`
- Modify: `tests/test_database_configuration.py`
- Modify: `tests/test_postgresql_reverification.py`
- Modify: `tests/test_filter_presets.py`
- Modify: `tests/test_sentinel_removal.py`
- Modify: `e2e/test_filter_count_e2e.py`
- Modify: `e2e/test_purchase_e2e.py`
- Modify: `.github/workflows/staging.yml`
- Test: `tests/test_pytest_xdist_topology.py`

**Interfaces:**
- Consumes: `settings.DATABASES` under the project's required PostgreSQL configuration.
- Produces: xdist worker database names only for PostgreSQL and no active static portability contract.

- [ ] **Step 1: Make the xdist fixture assert its actual backend contract**

Replace the backend skip in `timetracker/pytest_topology.py`:

```python
if database["ENGINE"] != "django.db.backends.postgresql":
    raise AssertionError(
        "Timetracker's pytest topology requires the PostgreSQL backend."
    )
```

Then continue computing and assigning `database["TEST"]["NAME"]` exactly as today. This turns a silent compatibility branch into a useful configuration failure.

- [ ] **Step 2: Delete the obsolete migration portability module**

Delete `tests/test_migration_portability.py` in full. Do not retain a weakened `RunSQL` blacklist: every test database now executes the migration graph against PostgreSQL, and the UUIDv7 plan adds focused reversible-migration tests.

- [ ] **Step 3: Remove the obsolete URL-parser fixture value and rewrite current test comments**

In `tests/test_database_configuration.py`, remove only this parametrized value:

```python
"sqlite:///tmp/tracker.sqlite3",
```

Keep the MySQL URL so the test still proves that non-PostgreSQL schemes are rejected.

Apply these exact semantic rewrites:

```python
# tests/test_postgresql_reverification.py
def assert_postgresql() -> None:
    """Assert the backend required by these PostgreSQL contract tests."""
    assert connection.vendor == "postgresql"
```

```python
# tests/test_filter_presets.py
# The required PostgreSQL C.UTF-8 collation compares these names as distinct,
# matching the case-sensitive client-side warning.
```

```python
# tests/test_sentinel_removal.py module docstring ending
and the conditional unique constraint preserves the platformless-dedup
guarantee that ordinary SQL uniqueness cannot provide when a key is NULL.
```

```python
# e2e/test_filter_count_e2e.py
# Exactly one <filter-count> belongs on the page; each badge fetches its count
# on load. The query-string model lets one view cover success and error states.
```

```python
# e2e/test_purchase_e2e.py
# Assert the split through its public UI outcome rather than duplicating the
# implementation with an ORM assertion.
```

In `.github/workflows/staging.yml`, replace the obsolete multi-line database rationale above `flyctl deploy` with:

```yaml
# Staging intentionally remains a single-machine deployment.
```

Do not change `--ha=false` or `flyctl scale count 1` in this cleanup.

- [ ] **Step 4: Prove no active backend-compatibility references remain**

Run:

```text
rg -n -i "sqlite|julianday\(|as_sqlite|SQLITE_BUSY|SQLITE_LOCKED" games common timetracker tests e2e .github README.md docs/deployment.md
```

Expected: no matches. Matches under `CHANGELOG.md` and `docs/superpowers/` are intentionally historical and are outside this command.

- [ ] **Step 5: Run the focused and fast repository gates**

Run through managed hidden processes on Windows:

```text
make test-fast ARGS="tests/test_database_configuration.py tests/test_postgresql_reverification.py tests/test_filter_presets.py tests/test_sentinel_removal.py tests/test_pytest_xdist_topology.py -x -v"
make check-fast
```

Expected: all pass with the Makefile's default worker count; PostgreSQL creates every test schema from the real migrations.

- [ ] **Step 6: Commit the remaining cleanup atomically**

```text
git add tests/test_migration_portability.py timetracker/pytest_topology.py tests/test_database_configuration.py tests/test_postgresql_reverification.py tests/test_filter_presets.py tests/test_sentinel_removal.py e2e/test_filter_count_e2e.py e2e/test_purchase_e2e.py .github/workflows/staging.yml
git commit -m "chore: remove remaining SQLite assumptions"
```

- [ ] **Step 7: Run the full cleanup acceptance gate**

Run `make check` through a managed hidden process on Windows and wait for the final log and exit status.

Expected: lint, formatting, mypy, TypeScript, generated assets, migration drift, Vitest, pytest, and E2E all pass. Re-run the Step 4 `rg` command and require no active matches. Do not create a commit for verification-only output.
