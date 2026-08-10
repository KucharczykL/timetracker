# PG-14 PostgreSQL 17 CI Verification Implementation Plan

**Goal:** Make GitHub Actions run the existing `make check` gate against an
explicit PostgreSQL 17 service satisfying the project contract.

**Architecture:** The workflow owns the disposable CI service and exposes it
through `DATABASE_URL`; the unchanged Makefile recognizes that explicit URL
and does not invoke its fallback provisioner.  Django validates the connected
server contract during ordinary database access.

## Task 1: Wire and guard the CI database service

**Files:**
- Modify: `.github/workflows/build-docker.yml`
- Add: `tests/test_ci_workflow.py`

1. Add a focused test that loads the test workflow and requires a PostgreSQL
   17 service, `timetracker` database credentials, exact UTF8/builtin/C.UTF-8
   initialization, a `pg_isready` health check, and a job-level `DATABASE_URL`
   pointing at that service.  Run it and confirm it fails because the workflow
   does not yet declare the service.
2. Add the `postgres:17` Actions service with those environment values, port
   mapping, and health check.  Set the test job `DATABASE_URL` to the service's
   ephemeral database.  Leave the `make check` step and `PYTEST_WORKERS`
   policy untouched.
3. Re-run the focused test, then run `make check` with the Makefile-selected
   worker count.  Confirm `ensure-postgres` selects the explicit URL and no
   fallback archive is needed in CI.

**Acceptance:** CI has an explicit PostgreSQL 17 service under the portable
locale contract; regressions in that wiring fail locally; the unchanged full
gate passes against it.
