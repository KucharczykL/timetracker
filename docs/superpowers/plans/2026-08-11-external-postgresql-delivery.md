# External PostgreSQL Deployment and Recovery Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish #617's PostgreSQL-18 external deployment guide, verify it independently, then finish #618's manual backup and isolated restore guide with PostgreSQL 18.4 CI proof.

**Architecture:** The application remains an external-database client using one
file-backed URL. Stage 1 documents that contract without creating a server.
After its verification gate, Stage 2 adds only manual operator procedures and a
bounded CI restore check against the existing `postgres:18.4` service.

**Tech Stack:** Docker Compose, rootless Podman Quadlets, GitHub Actions,
PostgreSQL 18.4 client tools, Django, pytest, Markdown.

## Global Constraints

- Accept PostgreSQL 18.x only; the developer fallback and CI service remain
  pinned to 18.4.
- Timetracker never owns a PostgreSQL service, storage, roles, initialization,
  lifecycle, or server configuration.
- The only application connection input is `DATABASE_URL`, including
  `DATABASE_URL__FILE`.
- Both image examples must account for the image's uid 1000 user; a mounted URL
  secret must be readable by the mapped host user.
- Backup scheduling, retention, monitoring, alerting, and off-host transport
  remain #597.
- Routine restore verification never targets the live database. On failure it
  retains the isolated verification database; only success drops it.

---

## File structure

| File | Responsibility |
| --- | --- |
| `docs/deployment.md` | Operator guide for external PostgreSQL 18 deployment, backup, and restore verification. |
| `README.md` | Concise image-use entry point linking to the operator guide. |
| `tests/test_compose_deployment.py` | Structural external-database Compose contract. |
| `.github/workflows/build-docker.yml` | PostgreSQL 18.4 dump/restore proof after the normal test gate. |
| `tests/test_ci_workflow.py` | Workflow-shape guard for the actual CI restore command. |

### Task 1: Publish the external deployment guide (#617)

**Files:**
- Create: `docs/deployment.md`
- Modify: `README.md:25-61`
- Verify: `tests/test_compose_deployment.py`

**Interfaces:**
- Consumes: the existing Compose secret name `timetracker_database_url` and
  application path `/run/secrets/timetracker_database_url`.
- Produces: a human-operated deployment contract; no new runtime setting,
  service, volume, or container artifact.

- [ ] **Step 1: Read the existing deployment boundary and image examples**

Read `docker-compose.yml`, `docker-compose.no-caddy.yml`, `README.md`, and
`docs/configuration.md`. Record the exact existing Compose contract:

```yaml
DATABASE_URL__FILE: /run/secrets/timetracker_database_url
secret: timetracker_database_url
```

Confirm there is no `postgres` service or database volume before documenting
the deployment; the guide must describe the existing boundary, not invent one.

- [ ] **Step 2: Write `docs/deployment.md`**

Include these bounded sections and commands:

```markdown
## External PostgreSQL contract

Timetracker requires a PostgreSQL 18.x database initialized with UTF8,
`builtin`, and `C.UTF-8`. PostgreSQL ownership, lifecycle, roles, storage,
networking, and upgrades belong to the operator.

## Docker Compose

Create a protected host file containing only:

postgresql://timetracker:<percent-encoded-password>@postgres/timetracker

Set `TIMETRACKER_DATABASE_URL_FILE` to its absolute path, then start the
existing app-only Compose deployment. Explain that `postgres` is merely an
example hostname, not an application requirement.

## Rootless Podman Quadlet

Network=backend.network
Environment=DATABASE_URL__FILE=/run/secrets/timetracker_database_url
Volume=%h/docker-compose-templates/secrets/timetracker_database_url:/run/secrets/timetracker_database_url:ro
UserNS=keep-id:uid=%U,gid=%G
```

State that the secret's host owner/read mode must let the keep-id mapped uid
read it. Do not include a PostgreSQL Quadlet, `POSTGRES_*` variable, database
volume, or server health check. Link readers to #597 for backup automation,
retention, monitoring, and alerting.

- [ ] **Step 3: Replace incomplete image snippets with a guide link**

In `README.md`, retain image-tag and uid-1000 facts, remove the runnable
Docker/Quadlet examples that omit the required database URL, and add:

```markdown
For Docker Compose and rootless Podman Quadlet deployments with an
operator-managed PostgreSQL 18 database, see [Deployment](docs/deployment.md).
```

- [ ] **Step 4: Run the existing Compose-boundary test**

Run:

```powershell
$env:DATABASE_URL = 'postgresql://timetracker@127.0.0.1:7661/timetracker'
.\.venv\Scripts\python.exe -m pytest tests/test_compose_deployment.py -q
```

Expected: PASS. This parses the Compose documents and confirms their single
app service, URL-secret mount, and absence of bundled PostgreSQL state.

- [ ] **Step 5: Manually review the guide against the boundary**

Confirm the guide includes `DATABASE_URL__FILE`, `backend.network`, the
example `postgres` alias, and the uid-1000 permission explanation. Confirm it
does not describe a Timetracker-managed PostgreSQL server or automatic backup.
Human prose is reviewed directly; do not add brittle source-text tests for it.

- [ ] **Step 6: Commit Stage 1**

```powershell
git add docs/deployment.md README.md
git commit -m "docs: guide external PostgreSQL deployment"
```

### Task 2: Verification gate between #617 and #618

**Files:**
- Verify only: `docker-compose.yml`, `docker-compose.no-caddy.yml`,
  `.github/workflows/build-docker.yml`, `tests/test_compose_deployment.py`,
  `tests/test_ci_workflow.py`

**Interfaces:**
- Consumes: Stage 1's documentation and the already-implemented Compose,
  runtime, and image-user secret-smoke contracts.
- Produces: explicit evidence that Stage 2 may rely on an app-only external
  PostgreSQL 18 deployment.

- [ ] **Step 1: Run the focused deployment/workflow guards**

Run:

```powershell
$env:DATABASE_URL = 'postgresql://timetracker@127.0.0.1:7661/timetracker'
.\.venv\Scripts\python.exe -m pytest tests/test_compose_deployment.py tests/test_ci_workflow.py -q
```

Expected: PASS, including the guard that requires `postgres:18.4` and the
uid-1000 `DATABASE_URL__FILE` smoke-test workflow step.

- [ ] **Step 2: Run the full local gate through a hidden managed Windows process**

Run `make check` using the repository's managed hidden-process procedure and
the Makefile default pytest worker count. Wait for the process's final log and
exit code.

Expected: the PostgreSQL 18 harness contract, static checks, TypeScript tests,
and parallel pytest suite all pass.

- [ ] **Step 3: Inspect the GitHub Actions run before Stage 2**

After pushing Stage 1, confirm the `Smoke test database URL secret` job step
completed successfully. This is the actual Docker execution evidence; the
local workflow test only guards its required command shape.

- [ ] **Step 4: Stop if the gate fails**

Do not start #618 work until the failing deployment/workflow condition is
understood and fixed. Preserve the external-only boundary while correcting it.

### Task 3: Add PostgreSQL 18.4 isolated restore proof (#618)

**Files:**
- Modify: `tests/test_ci_workflow.py`
- Modify: `.github/workflows/build-docker.yml`

**Interfaces:**
- Consumes: CI's existing `postgres:18.4` service and its
  `postgresql://timetracker:timetracker@127.0.0.1:5432/timetracker` URL.
- Produces: a `Verify PostgreSQL backup restore` workflow step that creates and
  drops only `timetracker_restore_verify` after a successful restore.

- [ ] **Step 1: Write the failing workflow contract test**

Add this test to `tests/test_ci_workflow.py`:

```python
def test_test_job_verifies_an_isolated_postgresql_backup_restore():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    steps = workflow["jobs"]["test"]["steps"]
    restore = next(
        step
        for step in steps
        if step.get("name") == "Verify PostgreSQL backup restore"
    )

    assert "postgres:18.4" in restore["run"]
    assert "pg_dump" in restore["run"]
    assert "--format=custom" in restore["run"]
    assert "--no-owner" in restore["run"]
    assert "--no-privileges" in restore["run"]
    assert "timetracker_restore_verify" in restore["run"]
    assert "pg_restore" in restore["run"]
    assert "--exit-on-error" in restore["run"]
    assert "manage.py migrate --check" in restore["run"]
    assert "dropdb" in restore["run"]
    assert "trap" not in restore["run"]
```

The missing workflow step makes this fail; the final assertion protects the
requirement that a failed restore preserves the verification database.

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
$env:DATABASE_URL = 'postgresql://timetracker@127.0.0.1:7661/timetracker'
.\.venv\Scripts\python.exe -m pytest tests/test_ci_workflow.py::test_test_job_verifies_an_isolated_postgresql_backup_restore -q
```

Expected: FAIL with `StopIteration` because the restore workflow step does not
yet exist.

- [ ] **Step 3: Add the bounded CI restore command**

Append this step after `Run checks` and before the image secret smoke test in
`.github/workflows/build-docker.yml`:

```yaml
      - name: Verify PostgreSQL backup restore
        run: |
          set -euo pipefail
          postgres_id="$(docker ps --filter 'ancestor=postgres:18.4' --format '{{.ID}}' | head -n 1)"
          test -n "$postgres_id"
          verification_database=timetracker_restore_verify
          dump_file=/tmp/timetracker.dump
          docker exec "$postgres_id" pg_dump -U timetracker --format=custom --no-owner --no-privileges --file="$dump_file" timetracker
          docker exec "$postgres_id" createdb -U timetracker "$verification_database"
          docker exec "$postgres_id" pg_restore -U timetracker --exit-on-error --no-owner --no-privileges --dbname="$verification_database" "$dump_file"
          DATABASE_URL="postgresql://timetracker:timetracker@127.0.0.1:5432/$verification_database" uv run --frozen python manage.py migrate --check
          docker exec "$postgres_id" dropdb -U timetracker "$verification_database"
```

Do not add a cleanup trap. If any command before the final `dropdb` fails, the
workflow fails and leaves the verification database in the CI service container
for investigation. The database is ephemeral with the CI job.

- [ ] **Step 4: Re-run the workflow guards**

Run:

```powershell
$env:DATABASE_URL = 'postgresql://timetracker@127.0.0.1:7661/timetracker'
.\.venv\Scripts\python.exe -m pytest tests/test_ci_workflow.py -q
```

Expected: PASS. The existing service/secret tests and new bounded-restore test
must all pass.

- [ ] **Step 5: Commit the CI proof**

```powershell
git add .github/workflows/build-docker.yml tests/test_ci_workflow.py
git commit -m "ci: verify PostgreSQL backup restore"
```

### Task 4: Publish the manual backup and restore runbook (#618)

**Files:**
- Modify: `docs/deployment.md`
- Verify: `.github/workflows/build-docker.yml`, `tests/test_ci_workflow.py`

**Interfaces:**
- Consumes: the Stage 1 external URL-secret deployment guide and Stage 2 CI
  restore command.
- Produces: manual operator commands that use an operator-controlled
  PostgreSQL-18-compatible client and never manipulate the live database.

- [ ] **Step 1: Add the manual backup section**

Add a `## Manual backup` section to `docs/deployment.md`. State that the
operator runs a PostgreSQL-18-compatible `pg_dump` client against the external
server and stores the output in protected, operator-selected storage:

```bash
pg_dump "$DATABASE_URL" --format=custom --no-owner --no-privileges \
  --file=/path/to/protected/timetracker-$(date +%F).dump
```

Explain that the dump is database-only and does not create cluster roles or
privileges. Link #597 for scheduling, retention, monitoring, and off-host
transport.

- [ ] **Step 2: Add the isolated restore-verification section**

Add a `## Isolated restore verification` section using an administrator-capable
operator connection. It must run these operations in order, substituting only
operator-selected URLs and paths:

```bash
createdb --maintenance-db=postgres timetracker_restore_verify
pg_restore --exit-on-error --no-owner --no-privileges \
  --dbname=timetracker_restore_verify /path/to/protected/timetracker.dump
DATABASE_URL=postgresql://<operator>@<host>/timetracker_restore_verify \
  python manage.py migrate --check
dropdb --maintenance-db=postgres timetracker_restore_verify
```

State explicitly: run `dropdb` only after all prior commands succeed; on a
failure leave `timetracker_restore_verify` for inspection; never drop,
recreate, or restore into the live Timetracker database. Production disaster
recovery is a separate deliberate procedure.

- [ ] **Step 3: Review commands for operator boundaries**

Check that the runbook does not assume a Timetracker-owned Postgres container,
credential mechanism, backup location, or role layout. It may recommend a
dedicated application role/database but must not require it.

- [ ] **Step 4: Run focused guards and full local verification**

Run the focused workflow guard first:

```powershell
$env:DATABASE_URL = 'postgresql://timetracker@127.0.0.1:7661/timetracker'
.\.venv\Scripts\python.exe -m pytest tests/test_ci_workflow.py tests/test_compose_deployment.py -q
```

Then run managed hidden-process `make check`, waiting for final log and exit
status. Expected: both commands pass.

- [ ] **Step 5: Commit the runbook**

```powershell
git add docs/deployment.md
git commit -m "docs: document PostgreSQL backup recovery"
```

## Final acceptance review

- [ ] Confirm #617's Compose, Docker, and rootless Quadlet documentation all
  use `DATABASE_URL__FILE`, remain app-only, and describe PostgreSQL 18.x.
- [ ] Confirm the independent Stage 1 gate has evidence from `make check` and
  the CI image-user secret smoke test before #618 work is treated as started.
- [ ] Confirm #618's CI and operator procedures use custom dumps, an explicit
  isolated verification database, `pg_restore --exit-on-error`, a read-only
  migration check, and success-only drop semantics.
- [ ] Confirm no task adds automatic backup operations or production restore.
