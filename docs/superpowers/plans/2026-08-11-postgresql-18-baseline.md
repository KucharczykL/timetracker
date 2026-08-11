# PostgreSQL 18 Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PostgreSQL 18 the only supported runtime major, with PostgreSQL
18.4 pinned for the downloaded developer fallback and CI.

**Architecture:** Runtime validation owns one `REQUIRED_POSTGRES_MAJOR = 18`.
The developer harness imports it, but separately pins exact 18.4.0 archives.
CI uses `postgres:18.4`; external operators may use any PostgreSQL 18.x server.

**Tech Stack:** Django, psycopg, pytest, Nix, GitHub Actions, PostgreSQL 18.4.

## Global Constraints

- Accept PostgreSQL major 18 only; keep UTF8, `builtin`, `C.UTF-8` unchanged.
- Pin fallback assets to 18.4.0 and CI to `postgres:18.4`.
- Do not migrate or automatically delete developer data; document deletion of
  disposable `.cache/postgres/data` before the first PostgreSQL 18 run.
- Preserve #617's app-only `DATABASE_URL__FILE` Compose work and #618 scope.

---

## File structure

| File | Responsibility |
| --- | --- |
| `timetracker/postgres_contract.py` | Runtime PostgreSQL 18 contract. |
| `scripts/ensure_postgres.py` | Exact 18.4.0 fallback assets and harness validation. |
| `shell.nix` | Nix PostgreSQL 18 developer tool. |
| `.github/workflows/build-docker.yml` | PostgreSQL 18.4 CI service. |
| `tests/test_postgres_contract.py` | Runtime-major acceptance/rejection. |
| `tests/test_ensure_postgres.py` | Complete fallback-version and checksum mapping. |
| `tests/test_ci_workflow.py` | CI patch-pin guard. |
| `docs/configuration.md`, `README.md` | PostgreSQL 18 and disposable-cache upgrade note. |
| `docs/superpowers/specs/2026-08-10-pg-15-16-external-postgresql-deployment-backup-design.md` | Replace dual-major design statements. |
| `docs/superpowers/plans/2026-08-10-pg-15-16-external-postgresql-deployment-backup.md` | Replace dual-major/matrix tasks; retain external deployment work. |

### Task 1: Establish one PostgreSQL 18 runtime contract

**Files:**
- Modify: `timetracker/postgres_contract.py`, `tests/test_postgres_contract.py`, `tests/test_postgresql_reverification.py`

- [ ] Write a failing parameterized test that accepts `180004` and rejects
  `170004` and `190000`, all with the exact `major version 18` error text.
- [ ] Run `python -m pytest tests/test_postgres_contract.py -q` with the
  managed database URL; confirm 18 fails under the current dual-major code.
- [ ] Replace `SUPPORTED_POSTGRES_MAJORS` with `REQUIRED_POSTGRES_MAJOR = 18`;
  compare `actual_major != REQUIRED_POSTGRES_MAJOR`; update the live assertion
  to equal 18.
- [ ] Re-run the focused tests and commit `feat: require PostgreSQL 18`.

### Task 2: Pin the Nix and fallback harness to 18.4.0

**Files:**
- Modify: `scripts/ensure_postgres.py`, `shell.nix`, `tests/test_ensure_postgres.py`

- [ ] Write failing tests asserting `REQUIRED_MAJOR == 18`,
  `FALLBACK_VERSION == "18.4.0"`, and the complete four-entry mapping from the
  approved spec's archive/checksum table.
- [ ] Run `python -m pytest tests/test_ensure_postgres.py -q`; confirm the
  current PostgreSQL 17 values fail.
- [ ] Change the harness imports/checks to use `REQUIRED_POSTGRES_MAJOR`, set
  `REQUIRED_MAJOR = 18`, replace every fallback asset/checksum, update all 17
  messages, and change `postgresql_17` to `postgresql_18` in `shell.nix`.
- [ ] Re-run harness tests and commit `build: pin developer PostgreSQL to 18.4`.

### Task 3: Pin CI and reconcile the existing deployment work

**Files:**
- Modify: `.github/workflows/build-docker.yml`, `tests/test_ci_workflow.py`
- Modify: `docs/superpowers/specs/2026-08-10-pg-15-16-external-postgresql-deployment-backup-design.md`
- Modify: `docs/superpowers/plans/2026-08-10-pg-15-16-external-postgresql-deployment-backup.md`

- [ ] Write a failing workflow test requiring `postgres:18.4`, with no major
  matrix, and requiring the existing database URL/locale initialization.
- [ ] Run `python -m pytest tests/test_ci_workflow.py -q`; confirm it finds
  `postgres:17`.
- [ ] Change the service image to `postgres:18.4`; replace every dual-major,
  17/18 matrix, and `SUPPORTED_POSTGRES_MAJORS` plan/design assertion with the
  single-major baseline. Retain `DATABASE_URL__FILE`, app-only Compose, and
  #618's isolated restore design.
- [ ] Re-run workflow/document focused tests and commit
  `ci: test against PostgreSQL 18.4`.

### Task 4: Document reset and prove the integrated baseline

**Files:**
- Modify: `README.md`, `docs/configuration.md`, `tests/test_compose_deployment.py`

- [ ] Add failing documentation assertions for PostgreSQL 18, the precise
  `.cache/postgres/data` reset instruction, and the non-root Compose URL-secret
  requirement.
- [ ] Document: stop the harness, remove only `.cache/postgres/data`, and rerun
  `make`; never reuse that PostgreSQL 17 cluster with 18. State that
  `postgres:18.4` is a patch pin, while runtime accepts 18.x.
- [ ] Add a container smoke test, run as image UID 1000, which mounts a
  file-backed URL secret and proves `DATABASE_URL__FILE` is readable. Document
  the required host ownership/read permission instead of trusting Compose
  `mode: 0400` for file-backed secrets.
- [ ] In a fresh worktree/cache, run managed hidden-process `make check` and
  confirm the 18.4.0 Windows archive is downloaded, initialized, and the full
  gate succeeds. Commit `docs: require PostgreSQL 18`.

## Self-review

- Task 1 owns runtime semantics; Task 2 owns reproducible local tooling; Task
  3 owns CI and prior-plan reconciliation; Task 4 owns operator transition and
  end-to-end proof.
- No task migrates, deletes automatically, or changes production data.
- The plan uses one major name (`REQUIRED_POSTGRES_MAJOR`) and one exact
  artifact version (`FALLBACK_VERSION = "18.4.0"`) consistently.
