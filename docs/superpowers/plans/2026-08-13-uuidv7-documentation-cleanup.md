# UUIDv7 Documentation Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve PR #833 against current `origin/main` and leave only concise, durable UUIDv7 documentation.

**Architecture:** Merge `origin/main` without rewriting the published branch. Accept upstream's newer PostgreSQL cleanup everywhere it overlaps, then retain the UUIDv7 domain, validation, field, and clock-observation changes. Remove completed execution records and keep short developer and operator contracts.

**Tech Stack:** Git, Markdown, Python 3.14, Django, PostgreSQL 18, Make.

## Global Constraints

- Do not reintroduce files or SQLite cleanup implementations already removed or superseded on `origin/main`.
- Preserve the UUIDv7 domain, parser, converter, model field, and clock-skew behavior.
- Do not convert any existing model identifier in this PR.
- Use the Makefile's default `PYTEST_WORKERS` and managed hidden test processes on Windows.
- Remove this plan and its temporary design record from the final tree.

---

### Task 1: Merge current main and resolve overlapping cleanup

**Files:**
- Resolve to `origin/main`: `.dockerignore`, `.env.example`, `.github/workflows/staging.yml`, `.gitignore`, `common/criteria.py`, `docs/superpowers/plans/2026-08-12-one-time-sqlite-postgresql-cutover.md`, `e2e/test_filter_count_e2e.py`, `e2e/test_purchase_e2e.py`, `games/expressions.py`, `games/models.py`, `tests/test_filter_presets.py`, `tests/test_live_server_db_concurrency.py`, `tests/test_postgresql_reverification.py`, `tests/test_sentinel_removal.py`, `timetracker/pytest_topology.py`
- Merge manually: `tests/test_database_configuration.py`
- Preserve UUIDv7 changes: `games/migrations/0002_uuid_v7_domain.py`, `timetracker/uuidv7.py`, `timetracker/urls.py`, `timetracker/database.py`, `timetracker/postgres_contract.py`, `tests/test_uuidv7.py`, `tests/test_uuidv7_domain.py`, `tests/test_database_clock.py`, `tests/test_postgres_contract.py`

**Interfaces:**
- Consumes: current branch `codex/uuidv7-identity` and fetched `origin/main` at `08f8b81` or newer.
- Produces: one merge commit with no conflict markers and the upstream cleanup plus UUIDv7 foundation.

- [ ] **Step 1: Merge without committing automatically**

Run:

```text
git merge --no-commit origin/main
```

Expected: Git reports the known overlapping cleanup conflicts and leaves the merge in progress.

- [ ] **Step 2: Resolve cleanup conflicts to current main**

For every file listed under "Resolve to `origin/main`", use the exact
`origin/main` version, including upstream deletions. These files contain newer
cleanup implementations or documentation removals and must not retain this
branch's older duplicate work.

- [ ] **Step 3: Combine the connection-hook test conflict**

Start `tests/test_database_configuration.py` from `origin/main`, then change its
two connection-hook monkeypatch targets from
`timetracker.database.validate_postgres_collation_contract` to
`timetracker.database.observe_valid_postgres_connection`. Do not restore the
removed backend-engine assertion or the removed non-PostgreSQL URL case.

- [ ] **Step 4: Verify the resolved merge tree**

Run:

```text
git diff --check
git diff --name-only --diff-filter=U
rg -n "^(<<<<<<<|=======|>>>>>>>)" --glob "!uv.lock" .
```

Expected: no unmerged paths, conflict markers, or whitespace errors.

- [ ] **Step 5: Run focused merged-path tests**

Run through a managed hidden process on Windows:

```text
uv run --frozen pytest tests/test_uuidv7.py tests/test_uuidv7_domain.py tests/test_database_clock.py tests/test_postgres_contract.py tests/test_database_configuration.py -n 16 -x -v
```

Expected: all UUIDv7, PostgreSQL-domain, clock, and connection tests pass.

- [ ] **Step 6: Commit the merge**

```text
git add -A
git commit -m "Merge origin/main into codex/uuidv7-identity"
```

---

### Task 2: Remove completed plans and compress permanent guidance

**Files:**
- Delete: `docs/superpowers/specs/2026-08-13-uuidv7-identity-foundation-design.md`
- Delete: `docs/superpowers/plans/2026-08-13-uuidv7-identity-foundation.md`
- Delete: `docs/superpowers/plans/2026-08-13-postgresql-only-cleanup.md`
- Delete: `docs/superpowers/specs/2026-08-13-uuidv7-documentation-cleanup-design.md`
- Delete: `docs/superpowers/plans/2026-08-13-uuidv7-documentation-cleanup.md`
- Modify: `README.md`
- Modify: `docs/deployment.md`

**Interfaces:**
- Consumes: the merged UUIDv7 implementation and current `origin/main` documentation layout.
- Produces: durable developer and operator guidance with no completed #639 execution records.

- [ ] **Step 1: Delete completed and temporary execution records**

Delete all five files listed above. The older one-time cutover plan remains
deleted through the Task 1 merge resolution.

- [ ] **Step 2: Shorten the README convention**

Replace the current identifier section with:

```markdown
## Identifiers

Use `timetracker.uuidv7.UUIDv7Field` for new Timetracker identifiers and
`<uuidv7:identifier>` for URL parameters. UUIDv7 time and ordering are
diagnostic metadata, not creation times, business dates, or event sequences.
```

- [ ] **Step 3: Shorten deployment guidance**

Replace the current UUIDv7 deployment section with:

```markdown
## UUIDv7

Identity columns use the `uuid_v7` domain over PostgreSQL's `uuid` type. Tools
that report it as `USER-DEFINED` can use `identifier::uuid`.

Python defaults use the application host clock; database defaults use the
PostgreSQL host clock. Timetracker warns on new connections when database time
falls more than one second outside the latency-adjusted application interval.
The warning does not affect `/health` or `/health/ready`; keep both hosts
time-synchronized.
```

- [ ] **Step 4: Inspect the documentation diff**

Run:

```text
git diff --check
git diff origin/main -- README.md docs/deployment.md docs/superpowers
```

Expected: only the concise README/deployment guidance is added; the completed
#639 records and unrelated cutover-plan formatting are absent.

- [ ] **Step 5: Run the full repository gate**

Run `make check` through a managed hidden process on Windows.

Expected: lint, formatting, mypy, generated files, migration drift, TypeScript,
PostgreSQL pytest, and E2E all pass with the default worker count.

- [ ] **Step 6: Commit and update the PR**

```text
git add -A
git commit -m "docs: keep UUIDv7 guidance timeless"
git push origin codex/uuidv7-identity
```

Confirm PR #833 reports no merge conflicts and remains based on `main`.
