# PG-15/PG-16 External PostgreSQL Deployment and Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support an externally managed PostgreSQL 17 or 18 database through a
file-backed URL, document app-only Compose/rootless Quadlet deployment, and
verify portable manual backups through an isolated restore check.

**Architecture:** Timetracker continues to accept one complete PostgreSQL URL,
but `DATABASE_URL` opts into the project's existing `NAME__FILE` resolution.
Compose and Quadlet consume a read-only secret and never own PostgreSQL. The CI
matrix validates the application contract and a database-only dump/restore on
both supported server majors; the operator guide uses the same isolated-restore
boundary for real deployments.

**Tech Stack:** Django 6, psycopg 3, pytest/pytest-django, GitHub Actions,
Docker Compose, rootless Podman Quadlets, PostgreSQL 17 and 18 client tools.

## Global Constraints

- Support exactly PostgreSQL majors 17 and 18; reject later majors until they
  have explicit compatibility coverage.
- Keep the database contract: UTF8 encoding, `builtin` locale provider, and
  builtin locale `C.UTF-8`.
- `DATABASE_URL` remains the sole application database setting; do not add
  discrete `PGHOST`, `PGUSER`, `PGPASSWORD`, or database-mode settings.
- `DATABASE_URL__FILE` wins over `DATABASE_URL`, consistent with the existing
  `allow_file=True` resolver precedence.
- Do not add a PostgreSQL service, volume, initialization, lifecycle, or
  scheduler to Timetracker's Compose or Quadlet deployment artifacts.
- Backups are manual. Scheduling, retention, monitoring, alerting, and offsite
  transport remain out of scope for #597.
- Routine restore verification creates and drops only an explicitly named,
  isolated verification database; it never replaces the live database.
- On Windows, keep Makefile-selected pytest worker counts and run `make check`
  through the managed hidden-process procedure.

---

## File structure

| File | Responsibility |
| --- | --- |
| `timetracker/postgres_contract.py` | Declare supported PostgreSQL majors and validate the connected server against them. |
| `timetracker/database.py` | Resolve `DATABASE_URL` through the file-aware configuration path. |
| `tests/test_postgres_contract.py` | Unit-test the supported-major and rejected-major contract. |
| `tests/test_database_configuration.py` | Prove file-backed URL resolution and its precedence. |
| `tests/test_postgresql_reverification.py` | Assert the live integration server belongs to the supported-major set. |
| `docker-compose.yml` | App-only Compose deployment using a file-backed database URL secret. |
| `docker-compose.no-caddy.yml` | Match the external-secret contract in the no-Caddy app deployment. |
| `.env.example` | Explain the Compose secret-file path without placing a database URL in `.env`. |
| `tests/test_compose_deployment.py` | Parse both Compose files and lock down the external-database boundary. |
| `.github/workflows/build-docker.yml` | Execute the test gate and dump/restore proof against PostgreSQL 17 and 18. |
| `tests/test_ci_workflow.py` | Guard the Actions matrix, PostgreSQL contract, and restore-verification step. |
| `README.md` | Link image users to the external-PostgreSQL deployment guide. |
| `docs/deployment.md` | Give Docker/Quadlet secret wiring and the manual backup/isolated restore runbook. |

## Task 1: Accept PostgreSQL 17 and 18 and enable the URL secret

**Files:**
- Modify: `timetracker/postgres_contract.py:6-8, 73-84`
- Modify: `timetracker/database.py:50-67, 73-74`
- Modify: `tests/test_postgres_contract.py:25-53`
- Modify: `tests/test_database_configuration.py:42-67`
- Modify: `tests/test_postgresql_reverification.py:166-181`

**Interfaces:**
- Consumes: `config(name, *, allow_file: bool = False)` and the existing
  `PostgresContract` catalog snapshot.
- Produces: `SUPPORTED_POSTGRES_MAJORS: frozenset[int]` and
  `required_database_settings()` accepting a URL from either
  `DATABASE_URL__FILE` or `DATABASE_URL`.

- [ ] **Step 1: Write the failing supported-major tests**

  Replace the single-major happy-path test with a parameterized test for
  `(170004, 180004)`. Add mismatches for `160010` and `190000`, asserting an
  actionable message that names `17 or 18`. Add a database-configuration test
  that writes `postgresql://file.example/tracker\n` to a temporary file, sets
  both `DATABASE_URL__FILE` and `DATABASE_URL`, resets config caches, and
  asserts `required_database_settings()["HOST"] == "file.example"`. Extend the
  live integration assertion to require the observed major to be in `{17, 18}`.

  ```python
  @pytest.mark.parametrize("version", [170004, 180004])
  def test_validate_postgres_collation_contract_accepts_supported_majors(version):
      assert validate_postgres_collation_contract(
          RecordingConnection((version, "UTF8", "b", "C.UTF-8"), [])
      ).server_version_num == version


  def test_file_database_url_wins_over_plain_environment(monkeypatch, tmp_path):
      secret = tmp_path / "database_url"
      secret.write_text("postgresql://file.example/tracker\\n")
      monkeypatch.setenv("DATABASE_URL__FILE", str(secret))
      monkeypatch.setenv("DATABASE_URL", "postgresql://plain.example/tracker")
      # Set ENV_FILE/INI_FILE to absent temporary paths, reset caches, then assert.
  ```

- [ ] **Step 2: Run the focused tests and confirm the expected failures**

  Run:

  ```powershell
  uv run --frozen pytest tests/test_postgres_contract.py tests/test_database_configuration.py -q
  ```

  Expected: the PostgreSQL 18 and file-backed URL cases fail because the
  validator requires exactly 17 and `required_database_settings()` does not pass
  `allow_file=True`.

- [ ] **Step 3: Implement the minimal contract and resolver changes**

  Replace `REQUIRED_POSTGRES_MAJOR = 17` with
  `SUPPORTED_POSTGRES_MAJORS = frozenset({17, 18})`. Reject when
  `actual_major not in SUPPORTED_POSTGRES_MAJORS`; format the error as
  `requires major version 17 or 18, got ...`. Keep every encoding/provider/
  locale check unchanged. Change both `config("DATABASE_URL")` calls in
  `required_database_settings()` to pass `allow_file=True`, including the
  managed-development fallback call. Update the `validate_default_connection`
  docstring to say “supported PostgreSQL contract.”

  ```python
  SUPPORTED_POSTGRES_MAJORS = frozenset({17, 18})

  if actual_major not in SUPPORTED_POSTGRES_MAJORS:
      raise PostgresContractViolation(
          "PostgreSQL collation contract requires major version 17 or 18, "
          f"got {actual_major} (server_version_num={contract.server_version_num})."
      )

  url = config("DATABASE_URL", allow_file=True)
  ```

- [ ] **Step 4: Run focused and live PostgreSQL verification**

  Run:

  ```powershell
  uv run --frozen pytest tests/test_postgres_contract.py tests/test_database_configuration.py -q
  make test-fast ARGS="tests/test_postgresql_reverification.py"
  ```

  Expected: all focused tests pass; the live test accepts the local PostgreSQL
  17 developer cluster and still proves UTF8/builtin/`C.UTF-8`.

- [ ] **Step 5: Commit the configuration boundary**

  ```powershell
  git add timetracker/postgres_contract.py timetracker/database.py tests/test_postgres_contract.py tests/test_database_configuration.py tests/test_postgresql_reverification.py
  git commit -m "feat: support PostgreSQL 18 database connections"
  ```

## Task 2: Make both Compose variants externally secret-backed

**Files:**
- Modify: `docker-compose.yml:1-23`
- Modify: `docker-compose.no-caddy.yml:1-21`
- Modify: `.env.example:1-57`
- Create: `tests/test_compose_deployment.py`

**Interfaces:**
- Consumes: application setting `DATABASE_URL__FILE=/run/secrets/timetracker_database_url`.
- Produces: both Compose variants expose only the `timetracker` service and
  mount a Compose secret named `timetracker_database_url` at that path.

- [ ] **Step 1: Write failing Compose contract tests**

  Add a YAML-parsing test parameterized over `docker-compose.yml` and
  `docker-compose.no-caddy.yml`. Require exactly one service named
  `timetracker`, require its environment list to contain
  `DATABASE_URL__FILE=/run/secrets/timetracker_database_url`, and require its
  `secrets` list to mount `timetracker_database_url` at
  `/run/secrets/timetracker_database_url`. Require the top-level secret to use
  `${TIMETRACKER_DATABASE_URL_FILE:?set TIMETRACKER_DATABASE_URL_FILE}` and
  assert no service or top-level volume is named `postgres`.

  ```python
  @pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.no-caddy.yml"])
  def test_compose_uses_only_an_external_database_secret(filename):
      compose = yaml.safe_load((REPO / filename).read_text())
      assert set(compose["services"]) == {"timetracker"}
      service = compose["services"]["timetracker"]
      assert "DATABASE_URL__FILE=/run/secrets/timetracker_database_url" in service["environment"]
      assert compose["secrets"]["timetracker_database_url"]["file"] == "${TIMETRACKER_DATABASE_URL_FILE:?set TIMETRACKER_DATABASE_URL_FILE}"
  ```

- [ ] **Step 2: Run the new test and confirm it fails**

  Run:

  ```powershell
  uv run --frozen pytest tests/test_compose_deployment.py -q
  ```

  Expected: FAIL because neither Compose file declares the database URL secret.

- [ ] **Step 3: Add the same Compose secret contract to both variants**

  Add the top-level declaration:

  ```yaml
  secrets:
    timetracker_database_url:
      file: ${TIMETRACKER_DATABASE_URL_FILE:?set TIMETRACKER_DATABASE_URL_FILE}
  ```

  Under each `timetracker` service, add the exact `DATABASE_URL__FILE`
  environment entry and:

  ```yaml
  secrets:
    - source: timetracker_database_url
      target: timetracker_database_url
      mode: 0400
  ```

  In `.env.example`, add a commented Compose-only variable with an absolute
  host-path example, explain that the pointed-to file contains the complete URL,
  and explicitly do not add `DATABASE_URL=` there.

- [ ] **Step 4: Run configuration validation and the guard**

  Run:

  ```powershell
  $secret = Join-Path ([System.IO.Path]::GetTempPath()) "timetracker_database_url"
  "postgresql://timetracker:testing@postgres/timetracker" | Set-Content -NoNewline $secret
  $env:TIMETRACKER_DATABASE_URL_FILE = $secret
  docker compose config
  Remove-Item -LiteralPath $secret
  uv run --frozen pytest tests/test_compose_deployment.py -q
  ```

  Expected: Compose renders one app service and its declared secret; the test
  confirms no bundled PostgreSQL service or volume exists.

- [ ] **Step 5: Commit the deployment artifact change**

  ```powershell
  git add docker-compose.yml docker-compose.no-caddy.yml .env.example tests/test_compose_deployment.py
  git commit -m "feat: read Compose database URL from a secret file"
  ```

## Task 3: Prove both server majors and an isolated logical restore in CI

**Files:**
- Modify: `.github/workflows/build-docker.yml:10-49`
- Modify: `tests/test_ci_workflow.py:1-28`

**Interfaces:**
- Consumes: the supported-major contract from Task 1 and the app-only deployment
  boundary from Task 2.
- Produces: one GitHub Actions test matrix entry per supported major and a
  disposable restore-verification step using only CI's PostgreSQL service.

- [ ] **Step 1: Write failing workflow contract assertions**

  Extend `tests/test_ci_workflow.py` to require
  `strategy.matrix.postgres_major == [17, 18]`, a service image of
  `postgres:${{ matrix.postgres_major }}`, and a named step such as
  `Verify PostgreSQL backup restore`. Assert that the step uses `pg_dump` with
  `--format=custom --no-owner --no-privileges`, creates
  `timetracker_restore_verify`, restores with `pg_restore --exit-on-error`,
  invokes `manage.py migrate --check` with that database URL, and drops exactly
  `timetracker_restore_verify`.

  ```python
  assert test_job["strategy"]["matrix"]["postgres_major"] == [17, 18]
  assert postgres["image"] == "postgres:${{ matrix.postgres_major }}"
  restore_step = next(step for step in test_job["steps"] if step["name"] == "Verify PostgreSQL backup restore")
  assert "--format=custom" in restore_step["run"]
  assert "timetracker_restore_verify" in restore_step["run"]
  assert "migrate --check" in restore_step["run"]
  ```

- [ ] **Step 2: Run the workflow test and confirm it fails**

  Run:

  ```powershell
  uv run --frozen pytest tests/test_ci_workflow.py -q
  ```

  Expected: FAIL because the job currently declares one fixed `postgres:17`
  service and has no restore-verification step.

- [ ] **Step 3: Add the dual-major matrix and restore proof**

  Give the test job this matrix and image:

  ```yaml
  strategy:
    matrix:
      postgres_major: [17, 18]
  services:
    postgres:
      image: postgres:${{ matrix.postgres_major }}
  ```

  Keep the existing UTF8/builtin/C.UTF-8 initialization, health check, and test
  `DATABASE_URL`. After `make check`, add one shell step that obtains the CI
  service container ID by its `postgres:${{ matrix.postgres_major }}` ancestor,
  then runs these operations in order:

  ```bash
  docker exec "$postgres_id" pg_dump -U timetracker --format=custom --no-owner --no-privileges --file=/tmp/timetracker.dump timetracker
  docker exec "$postgres_id" createdb -U timetracker timetracker_restore_verify
  docker exec "$postgres_id" pg_restore -U timetracker --exit-on-error --no-owner --no-privileges --dbname=timetracker_restore_verify /tmp/timetracker.dump
  DATABASE_URL=postgresql://timetracker:timetracker@127.0.0.1:5432/timetracker_restore_verify uv run --frozen python manage.py migrate --check
  docker exec "$postgres_id" dropdb -U timetracker --if-exists timetracker_restore_verify
  ```

  Add a shell `trap` immediately after the database name is set so a failed
  restore still attempts to drop only `timetracker_restore_verify`.

- [ ] **Step 4: Run local structural validation and the supported local major**

  Run:

  ```powershell
  uv run --frozen pytest tests/test_ci_workflow.py tests/test_postgresql_reverification.py -q
  ```

  Expected: the workflow guard passes; the local PostgreSQL 17 service remains
  valid. Let GitHub Actions provide the PostgreSQL 18 execution evidence.

- [ ] **Step 5: Commit CI proof**

  ```powershell
  git add .github/workflows/build-docker.yml tests/test_ci_workflow.py
  git commit -m "test: verify PostgreSQL 17 and 18 backup restores"
  ```

## Task 4: Publish the external deployment and manual recovery guide

**Files:**
- Modify: `README.md:22-66`
- Modify: `docs/configuration.md:21-53, 88-91`
- Create: `docs/deployment.md`

**Interfaces:**
- Consumes: the file-backed database URL from Task 1, the Compose secret name
  from Task 2, and the CI-proven dump/restore flags from Task 3.
- Produces: a single operator guide for Docker, rootless Podman Quadlet, manual
  backup, and isolated restore verification.

- [ ] **Step 1: Write documentation checks first**

  Add assertions to `tests/test_compose_deployment.py` that
  `docs/deployment.md` contains `DATABASE_URL__FILE`, `backend.network`, the
  `postgres` alias, `pg_dump --format=custom --no-owner --no-privileges`,
  `pg_restore --exit-on-error`, `timetracker_restore_verify`, and a statement
  that routine verification does not drop/recreate the live database. Also
  require the guide to link scheduling/retention work to #597.

- [ ] **Step 2: Run the documentation guard and confirm it fails**

  Run:

  ```powershell
  uv run --frozen pytest tests/test_compose_deployment.py -q
  ```

  Expected: FAIL because `docs/deployment.md` does not yet exist.

- [ ] **Step 3: Write the guide and cross-links**

  Create `docs/deployment.md` with these bounded sections:

  1. **External database contract:** PostgreSQL 17 or 18, UTF8/builtin/
     `C.UTF-8`; one `DATABASE_URL` only; dedicated role/database recommended,
     never required; PostgreSQL lifecycle stays with the operator.
  2. **Docker Compose:** create a protected file containing the URL; set only
     `TIMETRACKER_DATABASE_URL_FILE` to its host path; start the existing
     app-only Compose file. State that Compose has no PostgreSQL service,
     database volume, or initialization.
  3. **Rootless Podman Quadlet:** show the app additions exactly:

     ```ini
     Network=backend.network
     Environment=DATABASE_URL__FILE=/run/secrets/timetracker_database_url
     Volume=%h/docker-compose-templates/secrets/timetracker_database_url:/run/secrets/timetracker_database_url:ro
     ```

     Explain that the independently managed PostgreSQL container advertises
     `NetworkAlias=postgres`, so the secret URL may use `@postgres/`.
  4. **Manual backup:** use a matching PostgreSQL client and a protected
     operator connection to create a custom database-only dump with
     `pg_dump --format=custom --no-owner --no-privileges`; state that the
     backup location and off-host handling are operator choices, while #597
     owns automation/retention.
  5. **Restore verification:** create a deliberately named empty
     `timetracker_restore_verify` database with an admin connection; restore
     using `pg_restore --exit-on-error --no-owner --no-privileges`; run
     `DATABASE_URL=<verification URL> python manage.py migrate --check`; then
     drop that exact database. State that failures retain it for inspection and
     that disaster recovery replacing production is a separate deliberate
     procedure.

  Update `README.md` to replace the incomplete `docker run` and Quadlet
  snippets with a concise “Running the image” summary and a link to the guide.
  Update `docs/configuration.md` to mark `DATABASE_URL` as file-capable,
  describe `DATABASE_URL__FILE` in the table and priority text, and change the
  server requirement from exact 17 to supported majors 17 and 18.

- [ ] **Step 4: Run documentation and project checks**

  Run:

  ```powershell
  uv run --frozen pytest tests/test_compose_deployment.py tests/test_database_configuration.py -q
  make check
  ```

  Expected: documentation guard, config coverage, and the full project gate
  pass. On Windows, launch `make check` through the managed hidden process and
  wait for its final exit status.

- [ ] **Step 5: Commit the operator guide**

  ```powershell
  git add README.md docs/configuration.md docs/deployment.md tests/test_compose_deployment.py
  git commit -m "docs: describe external PostgreSQL deployment and recovery"
  ```

## Self-review

- **Spec coverage:** Task 1 implements file-backed URL precedence and the
  supported-major correction. Task 2 preserves app-only deployment and proves
  it structurally. Task 3 gives both supported majors live application and
  logical-restore evidence. Task 4 documents Compose, rootless Podman, manual
  backup, isolated verification, and #597's exclusion. No database lifecycle,
  scheduler, or destructive production restore is added.
- **Placeholder scan:** Every task names concrete files, commands, settings,
  flags, and expected outcomes. The guide's operator URLs/paths are explicitly
  deployment inputs rather than missing implementation details.
- **Type consistency:** `SUPPORTED_POSTGRES_MAJORS` is a `frozenset[int]` in
  Task 1; every later task uses the same exact 17/18 set. Both deployment
  variants use the exact `timetracker_database_url` secret name and
  `/run/secrets/timetracker_database_url` target.
