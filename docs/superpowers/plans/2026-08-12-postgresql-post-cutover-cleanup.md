# PostgreSQL Post-Cutover Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Timetracker's one-time SQLite cutover artifacts and remaining SQLite compatibility while preserving the deployed PostgreSQL schema and application behavior.

**Architecture:** Replace the two database-dispatched generated-field expressions with ordinary typed Django expressions and edit the sole baseline migration to match. Prove schema equivalence imperatively by comparing a restored post-cutover production dump with a fresh database built from the edited baseline; remove transitional tests and current-facing SQLite language instead of adding permanent backend-policing machinery.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, pytest/pytest-django/pytest-xdist, Playwright, GNU Make, PowerShell, Git LFS.

## Global Constraints

- Work only in the isolated `codex/issue-628-postgres-cleanup` worktree.
- This repository is the entire change boundary; do not modify `docker-compose-templates` or implement #158/#597.
- Do not add a migration. Edit the sole initial baseline in place.
- Do not write to production. Production checks in this plan are read-only; all restore and migration execution uses disposable local databases.
- Keep ordinary behavioral coverage; remove tests whose sole purpose is enforcing PostgreSQL, rejecting SQLite, or scanning for SQLite-only SQL.
- Remove or rewrite SQLite references that describe current behavior. Keep clearly historical CHANGELOG and dated plan/spec snapshots, except for the explicitly deleted one-time cutover design and plan.
- Keep the Makefile's default `PYTEST_WORKERS`; do not set it to `0` for normal verification.
- On Windows Codex desktop, run `make check` and test targets through a managed hidden process and wait for the final log and exit status.
- Use `apply_patch` for tracked file edits. Preserve unrelated worktree changes.
- Stop if the restored production copy and fresh baseline differ in either generated-column expression, if migration drift appears, or if the restored production copy has a pending migration.

## File map

**Generated fields and baseline**

- Modify `games/models.py` — define the two generated fields with native typed Django expressions and correct current comments.
- Modify `games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py` — serialize those expressions and remove `replaces`.
- Delete `games/expressions.py` — all contents are SQLite compatibility.
- Modify `tests/test_generated_duration_columns.py` — retain value/source-column behavior without the SQLite SQL sentinel.
- Modify `tests/test_generated_days_to_finish.py` — retain value/type/source-column behavior without SQL-shape policing.

**One-time cutover artifacts**

- Delete `scripts/one_time_sqlite_postgres_cutover.py`.
- Delete `scripts/sqlite_postgres_source_contract.json`.
- Delete `tests/test_one_time_sqlite_postgres_cutover.py`.
- Delete `docs/superpowers/specs/2026-08-11-one-time-sqlite-postgresql-cutover-design.md`.
- Delete `docs/superpowers/plans/2026-08-12-one-time-sqlite-postgresql-cutover.md`.

**Transitional test scaffolding**

- Delete `tests/test_migration_portability.py` — the fresh PostgreSQL build is the migration validity gate.
- Delete `tests/test_postgresql_reverification.py` — each retained behavior already has a canonical test module.
- Modify `tests/test_database_configuration.py` — keep parser/configuration behavior and remove engine-policing cases.
- Modify `timetracker/pytest_topology.py` — remove the SQLite/memory-database branches from PostgreSQL xdist namespacing.
- Keep `tests/test_pytest_xdist_topology.py` — it tests the namespacing behavior rather than a backend assertion.

**Current-language and concurrency cleanup**

- Modify `common/criteria.py`.
- Modify `games/models.py`.
- Modify `tests/test_filter_presets.py`.
- Modify `tests/test_sentinel_removal.py`.
- Modify `tests/test_live_server_db_concurrency.py`.
- Modify `e2e/test_filter_count_e2e.py`.
- Modify `e2e/test_purchase_e2e.py`.
- Modify `e2e/conftest.py` — remove the SQLite teardown-quiescence fixture.
- Delete `e2e/test_teardown_quiescence_e2e.py` — it reproduces only the retired SQLite lock failure.

---

### Task 1: Replace compatibility expressions and make the baseline permanent

**Files:**

- Modify: `games/models.py:8-17,23-32,323-330,444-455`
- Modify: `games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py:3-55,279-294,479-490`
- Delete: `games/expressions.py`
- Modify: `tests/test_generated_duration_columns.py:1-55`
- Modify: `tests/test_generated_days_to_finish.py:1-52`

**Interfaces:**

- Consumes: Django `ExpressionWrapper`, `CombinedExpression`, `Coalesce`, `F`, `DurationField`, and `IntegerField` serialization.
- Produces: `Session.duration_total` and `PlayEvent.days_to_finish` with the same stored PostgreSQL values and `pg_get_expr` definitions as production; one initial migration with no `replaces` attribute.

- [ ] **Step 1: Record the accepted production evidence before editing**

Run the read-only migration query:

```powershell
ssh --% nas podman exec postgres psql -U lukas -d timetracker -Atc "select name from django_migrations where app='games' order by name;"
```

Expected: rows `0001_initial` through `0036_alter_playevent_days_to_finish` and the surviving `0001_squashed_0036_alter_playevent_days_to_finish` row. Stop if the squashed row is absent.

Run the read-only generated-expression query:

```powershell
ssh --% nas podman exec postgres psql -U lukas -d timetracker -Atc "SELECT c.relname || '.' || a.attname, pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d JOIN pg_attribute a ON a.attrelid=d.adrelid AND a.attnum=d.adnum JOIN pg_class c ON c.oid=d.adrelid WHERE (c.relname='games_session' AND a.attname='duration_total') OR (c.relname='games_playevent' AND a.attname='days_to_finish') ORDER BY 1;"
```

Expected, ignoring whitespace:

```text
games_playevent.days_to_finish|COALESCE(CASE WHEN (ended = started) THEN 1 ELSE (ended - started) END, 0)
games_session.duration_total|(COALESCE((timestamp_end - timestamp_start), '00:00:00'::interval) + duration_manual)
```

- [ ] **Step 2: Run the existing characterization tests before the refactor**

Run through the required hidden process:

```powershell
$env:PATH='C:\Users\lukas\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\override;C:\Users\lukas\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback;'+$env:PATH
$outLog=Join-Path $env:TEMP 'timetracker-628-task1-before.out.log'
$errLog=Join-Path $env:TEMP 'timetracker-628-task1-before.err.log'
$proc=Start-Process -FilePath (Get-Command make).Source -ArgumentList @('test-fast','"ARGS=tests/test_generated_duration_columns.py tests/test_generated_days_to_finish.py tests/test_session_querysets.py"') -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -Wait
Get-Content -Raw $outLog
Get-Content -Raw $errLog
if ($proc.ExitCode -ne 0) { exit $proc.ExitCode }
```

Expected: all selected characterization tests pass. These are the behavior contract for the refactor; no structural “must use PostgreSQL” test is added.

- [ ] **Step 3: Replace the model expressions with ordinary typed Django expressions**

In `games/models.py`, import `ExpressionWrapper` from `django.db.models`, remove the `games.expressions` import, and use:

```python
duration_total = GeneratedField(
    expression=ExpressionWrapper(
        Coalesce(F("timestamp_end") - F("timestamp_start"), timedelta(0))
        + F("duration_manual"),
        output_field=models.DurationField(),
    ),
    output_field=models.DurationField(),
    db_persist=True,
    editable=False,
)
```

For `PlayEvent.days_to_finish`, use a typed built-in `Func` so Django emits
native date subtraction instead of resolving `DateField - DateField` to an
interval:

```python
Case(
    When(ended=F("started"), then=Value(1)),
    default=Func(
        F("ended"),
        F("started"),
        function="",
        template="(%(expressions)s)",
        arg_joiner=" - ",
        output_field=models.IntegerField(),
    ),
    output_field=models.IntegerField(),
)
```

Also rewrite the `Game.Meta` comment so it states the current invariant without SQLite history:

```python
# A normal unique constraint permits multiple rows when platform is NULL;
# this preserves the platformless-game deduplication guarantee.
```

- [ ] **Step 4: Serialize the same expressions in the baseline and remove squash compatibility**

In `games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py`:

1. Delete `import games.expressions`.
2. Delete the complete `replaces = [...]` block.
3. Replace `DatabaseDurationSum(...)` with the serializer form:

```python
models.ExpressionWrapper(
    django.db.models.expressions.CombinedExpression(
        django.db.models.functions.comparison.Coalesce(
            django.db.models.expressions.CombinedExpression(
                models.F("timestamp_end"), "-", models.F("timestamp_start")
            ),
            datetime.timedelta(0),
        ),
        "+",
        models.F("duration_manual"),
    ),
    output_field=models.DurationField(),
)
```

4. Replace `DatabaseDateDifference(...)` with Django's serializer form:

```python
models.Func(
    models.F("ended"),
    models.F("started"),
    arg_joiner=" - ",
    function="",
    output_field=models.IntegerField(),
    template="(%(expressions)s)",
)
```

Keep `initial = True`, the filename, dependencies, and all operations unchanged.

- [ ] **Step 5: Delete the compatibility module and simplify its behavioral tests**

Delete `games/expressions.py`.

In `tests/test_generated_duration_columns.py`, remove `connection` from the imports, remove `field.generated_sql(connection)`, and delete the `django_format_dtdelta` assertion. Keep the persisted-field, output-type, source-column, and value assertions.

In `tests/test_generated_days_to_finish.py`, remove `connection` and `RawSQL` imports, remove `field.generated_sql(connection)`, and delete the SQL-string and `RawSQL` assertions. Keep the persisted-field, output-type, source-column, and value assertions.

- [ ] **Step 6: Verify focused behavior and migration drift**

Run through a hidden process:

```powershell
$outLog=Join-Path $env:TEMP 'timetracker-628-task1-after.out.log'
$errLog=Join-Path $env:TEMP 'timetracker-628-task1-after.err.log'
$proc=Start-Process -FilePath (Get-Command make).Source -ArgumentList @('test-fast','"ARGS=tests/test_generated_duration_columns.py tests/test_generated_days_to_finish.py tests/test_session_querysets.py"') -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -Wait
Get-Content -Raw $outLog
Get-Content -Raw $errLog
if ($proc.ExitCode -ne 0) { exit $proc.ExitCode }
make check-migrations
```

Expected: focused behavior passes and `makemigrations --check --dry-run` prints `No changes detected` without creating a migration.

- [ ] **Step 7: Compare a restored production copy with a fresh baseline**

Create two exact, disposable local databases. The first is restored from the accepted cutover dump; the second is built by the edited baseline:

```powershell
make ensure-postgres
$pgBin=(Get-ChildItem '.cache/postgres-binaries/18.4.0' -Recurse -Filter postgres.exe | Select-Object -First 1).DirectoryName
$managedUrl=((Select-String -Path '.cache/postgres.mk' -Pattern '^export DATABASE_URL := (.+)$').Matches[0].Groups[1].Value)
$managedUri=[Uri]$managedUrl
$pgHost=$managedUri.Host
$pgPort=$managedUri.Port
$dump=Join-Path $env:TEMP 'timetracker-post-cutover-20260812.dump'
scp nas:/docker/timetracker/backups/postgres-cutover-20260812T154734+0200/timetracker-post-cutover.dump $dump

& (Join-Path $pgBin 'dropdb.exe') -h $pgHost -p $pgPort -U timetracker --if-exists timetracker_628_prod_copy
& (Join-Path $pgBin 'dropdb.exe') -h $pgHost -p $pgPort -U timetracker --if-exists timetracker_628_fresh
& (Join-Path $pgBin 'createdb.exe') -h $pgHost -p $pgPort -U timetracker timetracker_628_prod_copy
& (Join-Path $pgBin 'createdb.exe') -h $pgHost -p $pgPort -U timetracker timetracker_628_fresh
& (Join-Path $pgBin 'pg_restore.exe') -h $pgHost -p $pgPort -U timetracker --no-owner --no-privileges -d timetracker_628_prod_copy $dump

$prodCopyUrl="postgresql://timetracker@${pgHost}:$pgPort/timetracker_628_prod_copy"
$freshUrl="postgresql://timetracker@${pgHost}:$pgPort/timetracker_628_fresh"
$env:DATABASE_URL=$freshUrl
$env:TIMETRACKER_MANAGED_DATABASE_URL='0'
uv run --frozen python manage.py migrate --noinput
```

Query both databases and compare normalized expressions:

```powershell
$schemaQuery="SELECT c.relname || '.' || a.attname || '|' || regexp_replace(pg_get_expr(d.adbin, d.adrelid), '[[:space:]]+', '', 'g') FROM pg_attrdef d JOIN pg_attribute a ON a.attrelid=d.adrelid AND a.attnum=d.adnum JOIN pg_class c ON c.oid=d.adrelid WHERE (c.relname='games_session' AND a.attname='duration_total') OR (c.relname='games_playevent' AND a.attname='days_to_finish') ORDER BY 1;"
$prodExpressions=& (Join-Path $pgBin 'psql.exe') -h $pgHost -p $pgPort -U timetracker -d timetracker_628_prod_copy -Atc $schemaQuery
$freshExpressions=& (Join-Path $pgBin 'psql.exe') -h $pgHost -p $pgPort -U timetracker -d timetracker_628_fresh -Atc $schemaQuery
$schemaDiff=Compare-Object $prodExpressions $freshExpressions
$schemaDiff
if ($schemaDiff) { throw 'Generated-column schema differs from production' }
$prodExpressions
```

Expected: `Compare-Object` prints nothing; the two normalized expressions match the Step 1 evidence.

Run the edited migration graph against the restored production copy without applying anything:

```powershell
$env:DATABASE_URL=$prodCopyUrl
uv run --frozen python manage.py migrate --check
uv run --frozen python manage.py showmigrations games --plan
```

Expected: exit 0, no pending migration, and the sole baseline is marked applied.

Clean up only the exact disposable resources:

```powershell
$env:DATABASE_URL=$managedUrl
$env:TIMETRACKER_MANAGED_DATABASE_URL='1'
& (Join-Path $pgBin 'dropdb.exe') -h $pgHost -p $pgPort -U timetracker --if-exists timetracker_628_prod_copy
& (Join-Path $pgBin 'dropdb.exe') -h $pgHost -p $pgPort -U timetracker --if-exists timetracker_628_fresh
Remove-Item -LiteralPath $dump -Force
```

- [ ] **Step 8: Commit the PostgreSQL-native baseline**

```powershell
git add games/models.py games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py tests/test_generated_duration_columns.py tests/test_generated_days_to_finish.py
git add -u games/expressions.py
git diff --cached --check
git commit -m "refactor: make generated fields PostgreSQL-native"
```

### Task 2: Remove the one-time cutover package

**Files:**

- Delete: `scripts/one_time_sqlite_postgres_cutover.py`
- Delete: `scripts/sqlite_postgres_source_contract.json`
- Delete: `tests/test_one_time_sqlite_postgres_cutover.py`
- Delete: `docs/superpowers/specs/2026-08-11-one-time-sqlite-postgresql-cutover-design.md`
- Delete: `docs/superpowers/plans/2026-08-12-one-time-sqlite-postgresql-cutover.md`

**Interfaces:**

- Consumes: accepted #621 issue evidence and the external raw/cutover backups.
- Produces: no one-shot cutover executable, source contract, dedicated test suite, or duplicate operational instructions in the product tree.

- [ ] **Step 1: Prove the removal list is self-contained**

```powershell
rg -n "one_time_sqlite_postgres_cutover|sqlite_postgres_source_contract|one-time-sqlite-postgresql-cutover" . --glob '!docs/superpowers/plans/2026-08-12-postgresql-post-cutover-cleanup.md' --glob '!docs/superpowers/specs/2026-08-12-postgresql-post-cutover-cleanup-design.md'
```

Expected: matches occur only in the five files being deleted. If a live import or command entry point appears elsewhere, remove that reference in this task before deleting its target.

- [ ] **Step 2: Delete all five artifacts together**

Use `apply_patch` to delete the five files. Do not replace them with a generic transfer command or shortened in-repository runbook.

- [ ] **Step 3: Verify collection and references after deletion**

```powershell
rg -n "one_time_sqlite_postgres_cutover|sqlite_postgres_source_contract|one-time-sqlite-postgresql-cutover" . --glob '!docs/superpowers/plans/2026-08-12-postgresql-post-cutover-cleanup.md' --glob '!docs/superpowers/specs/2026-08-12-postgresql-post-cutover-cleanup-design.md'
uv run --frozen pytest --collect-only -q tests
```

Expected: `rg` exits 1 with no matches; pytest collection succeeds without importing the deleted tool.

- [ ] **Step 4: Commit the artifact removal**

```powershell
git add -u scripts tests docs/superpowers/specs docs/superpowers/plans
git diff --cached --check
git commit -m "chore: remove one-time SQLite cutover artifacts"
```

### Task 3: Remove transition-only test scaffolding

**Files:**

- Delete: `tests/test_migration_portability.py`
- Delete: `tests/test_postgresql_reverification.py`
- Modify: `tests/test_database_configuration.py:19-35,89-97`
- Modify: `timetracker/pytest_topology.py:21-41`
- Test: `tests/test_pytest_xdist_topology.py`
- Test: `tests/test_generated_duration_columns.py`
- Test: `tests/test_generated_purchase_price_columns.py`
- Test: `tests/test_generated_days_to_finish.py`
- Test: `tests/test_sorting.py`
- Test: `tests/test_session_querysets.py`
- Test: `tests/test_filter_presets.py`
- Test: `tests/test_postgres_contract.py`

**Interfaces:**

- Consumes: canonical behavior tests listed above and the permanent PostgreSQL test harness.
- Produces: test coverage organized around behavior, with no duplicate PG-01..PG-06 reverification suite or source-scanning portability gate.

- [ ] **Step 1: Verify every reverification behavior has canonical coverage**

Run:

```powershell
rg -n "test_generated_duration_values|test_price_per_game|test_generated_days_to_finish|nullable_direct_sort|nullable_aggregate_sort|only_manual|without_manual|case_differing_names|validate_postgres_collation_contract" tests
```

Expected coverage map:

- generated durations → `tests/test_generated_duration_columns.py`;
- generated purchase prices → `tests/test_generated_purchase_price_columns.py`;
- generated day differences → `tests/test_generated_days_to_finish.py`;
- nullable/stable sorting → `tests/test_sorting.py`;
- interval queryset partitioning → `tests/test_session_querysets.py`;
- preset JSON/uniqueness behavior → `tests/test_filter_presets.py`;
- connection contract → `tests/test_postgres_contract.py` and `tests/test_ensure_postgres.py`.

Stop if any behavior lacks a canonical test; move that behavior assertion into the named canonical module before deleting the duplicate suite.

- [ ] **Step 2: Delete the two transition-only modules**

Delete `tests/test_postgresql_reverification.py` and `tests/test_migration_portability.py` with `apply_patch`.

The fresh test-database build already rejects invalid PostgreSQL migration SQL and generated-column dependencies, so do not replace the portability scanner.

- [ ] **Step 3: Remove backend-policing configuration assertions**

In `tests/test_database_configuration.py`:

- keep `test_postgresql_url_maps_to_django_database_settings`, because it verifies the custom URL parser's output;
- remove the `sqlite:///tmp/tracker.sqlite3` and `mysql://db/tracker` cases from the malformed-URL parameter list;
- rename the parameterized test to `test_database_url_rejects_malformed_urls`;
- delete `test_project_settings_use_required_postgresql_database_configuration` entirely;
- keep missing-secret, precedence, parser, and connection-contract tests.

- [ ] **Step 4: Simplify xdist database namespacing to its only runtime**

In `timetracker/pytest_topology.py`, retain the worker/non-worker gate and replace the loop body with:

```python
for configured_database in settings.DATABASES.values():
    database = cast(dict[str, Any], configured_database)
    test_name = database.setdefault("TEST", {}).get("NAME")
    if not test_name:
        test_name = f"test_{database['NAME']}"
    database["TEST"]["NAME"] = xdist_database_name(test_name, testrun_uid, worker_id)
```

There is no SQLite skip and no `:memory:` branch.

- [ ] **Step 5: Run the canonical behavior and topology tests**

Use a hidden process:

```powershell
$outLog=Join-Path $env:TEMP 'timetracker-628-task3.out.log'
$errLog=Join-Path $env:TEMP 'timetracker-628-task3.err.log'
$makeArgs='"ARGS=tests/test_database_configuration.py tests/test_pytest_xdist_topology.py tests/test_generated_duration_columns.py tests/test_generated_purchase_price_columns.py tests/test_generated_days_to_finish.py tests/test_sorting.py tests/test_session_querysets.py tests/test_filter_presets.py tests/test_postgres_contract.py"'
$proc=Start-Process -FilePath (Get-Command make).Source -ArgumentList @('test-fast',$makeArgs) -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -Wait
Get-Content -Raw $outLog
Get-Content -Raw $errLog
if ($proc.ExitCode -ne 0) { exit $proc.ExitCode }
```

Expected: all canonical behavior and topology tests pass.

- [ ] **Step 6: Commit the test-scaffolding cleanup**

```powershell
git add timetracker/pytest_topology.py tests/test_database_configuration.py
git add -u tests/test_migration_portability.py tests/test_postgresql_reverification.py
git diff --cached --check
git commit -m "test: remove database-transition scaffolding"
```

### Task 4: Remove SQLite-era concurrency machinery and current-facing language

**Files:**

- Modify: `common/criteria.py:367-372`
- Modify: `tests/test_filter_presets.py:519-524`
- Modify: `tests/test_sentinel_removal.py:1-5`
- Modify: `tests/test_live_server_db_concurrency.py:1-22,62-111`
- Modify: `e2e/test_filter_count_e2e.py:41-45`
- Modify: `e2e/test_purchase_e2e.py:174-177`
- Modify: `e2e/conftest.py:1-72`
- Delete: `e2e/test_teardown_quiescence_e2e.py`

**Interfaces:**

- Consumes: PostgreSQL MVCC/concurrent-request behavior and pytest-django's normal teardown.
- Produces: current comments and test names that describe live behavior, while retaining the real concurrent read/write request test.

- [ ] **Step 1: Remove the obsolete E2E teardown workaround**

In `e2e/conftest.py`, delete `_flush_waits_for_inflight_requests` completely and remove its now-unused imports:

```python
import time
from playwright.sync_api import Request
```

Delete `e2e/test_teardown_quiescence_e2e.py`. Do not add a replacement fixture: PostgreSQL can complete a reader while test teardown deletes rows under MVCC, and the full E2E gate will exercise ordinary teardown.

- [ ] **Step 2: Retain the real concurrent-request test with an accurate contract**

In `tests/test_live_server_db_concurrency.py`:

- replace the module docstring with `"""Concurrent live-server reads, writes, and test-thread queries stay reliable."""`;
- delete `test_test_database_uses_postgresql`;
- keep `test_concurrent_live_server_requests_all_succeed` and its helpers;
- rewrite that test's docstring to say it exercises interleaved authenticated reads, atomic settings writes, and test-thread ORM queries;
- rewrite the final in-test comment to describe the retained concurrent ORM behavior without the retired database history.

- [ ] **Step 3: Rewrite every remaining current-facing SQLite comment**

Apply these meanings, preserving the code beneath them:

- `common/criteria.py`: invalid or pathological regexes are rejected before database execution so they cannot produce a 500 or tie up a worker; do not name SQLite's `REGEXP` hook.
- `tests/test_filter_presets.py`: rename `test_postgresql_invalid_regex_is_rejected_without_persisting` to `test_invalid_regex_is_rejected_without_persisting`; describe the configured case-sensitive collation in `test_case_differing_names_are_distinct`.
- `tests/test_sentinel_removal.py`: say ordinary uniqueness permits repeated `NULL` platform values, so the conditional constraint preserves platformless deduplication.
- `e2e/test_filter_count_e2e.py`: two badges would issue duplicate concurrent count requests; the invariant is exactly one badge, without a connection-contention story.
- `e2e/test_purchase_e2e.py`: the UI assertion proves the browser observed the completed split operation; do not justify it through SQLite contention.

- [ ] **Step 4: Run focused concurrency and E2E verification**

First run the retained threaded live-server test through a hidden process:

```powershell
$outLog=Join-Path $env:TEMP 'timetracker-628-concurrency.out.log'
$errLog=Join-Path $env:TEMP 'timetracker-628-concurrency.err.log'
$proc=Start-Process -FilePath (Get-Command make).Source -ArgumentList @('test-fast','"ARGS=tests/test_live_server_db_concurrency.py tests/test_filter_presets.py tests/test_sentinel_removal.py"') -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -Wait
Get-Content -Raw $outLog
Get-Content -Raw $errLog
if ($proc.ExitCode -ne 0) { exit $proc.ExitCode }
```

Then run the affected browser paths three times, each through a hidden process, to exercise teardown without the removed fixture:

```powershell
1..3 | ForEach-Object {
    $outLog=Join-Path $env:TEMP "timetracker-628-e2e-$_.out.log"
    $errLog=Join-Path $env:TEMP "timetracker-628-e2e-$_.err.log"
    $proc=Start-Process -FilePath (Get-Command make).Source -ArgumentList @('test-e2e','"ARGS=e2e/test_filter_count_e2e.py e2e/test_purchase_e2e.py"') -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -Wait
    Get-Content -Raw $outLog
    Get-Content -Raw $errLog
    if ($proc.ExitCode -ne 0) { exit $proc.ExitCode }
}
```

Expected: the threaded test passes and all three E2E runs pass with normal pytest-django teardown.

- [ ] **Step 5: Audit current code and guidance, classifying historical matches**

Current-facing code outside dated historical documents must have no SQLite matches:

```powershell
rg -n -i "sqlite|julianday|django_format_dtdelta|django\.db\.backends\.sqlite3" . --glob '!CHANGELOG.md' --glob '!docs/superpowers/plans/**' --glob '!docs/superpowers/specs/**'
```

Expected: exit 1 with no matches.

Then inspect the retained historical set:

```powershell
rg -n -i "sqlite" CHANGELOG.md docs/superpowers/plans docs/superpowers/specs
```

Expected: matches are dated historical records or the approved #628 design/plan. Do not mechanically rewrite them. Stop and fix a passage only if it presents itself as current setup, deployment, runtime, or operator guidance.

- [ ] **Step 6: Commit current-language and concurrency cleanup**

```powershell
git add common/criteria.py tests/test_filter_presets.py tests/test_sentinel_removal.py tests/test_live_server_db_concurrency.py e2e/test_filter_count_e2e.py e2e/test_purchase_e2e.py e2e/conftest.py
git add -u e2e/test_teardown_quiescence_e2e.py
git diff --cached --check
git commit -m "chore: remove current SQLite assumptions"
```

### Task 5: Run the complete verification gate and prepare review evidence

**Files:**

- Verify: entire repository
- Verify: `docs/superpowers/specs/2026-08-12-postgresql-post-cutover-cleanup-design.md`
- Verify: `docs/superpowers/plans/2026-08-12-postgresql-post-cutover-cleanup.md`

**Interfaces:**

- Consumes: all preceding committed tasks.
- Produces: a clean reviewable branch with full test, migration, schema-parity, and reference-audit evidence.

- [ ] **Step 1: Review the complete diff against the design**

```powershell
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
git diff origin/main...HEAD -- games/models.py games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py timetracker/pytest_topology.py
git status --short --branch
```

Expected: only the files in this plan changed, no whitespace errors, and no unrelated working-tree changes.

- [ ] **Step 2: Run migration and current-reference gates**

```powershell
make check-migrations
rg -n -i "sqlite|julianday|django_format_dtdelta|django\.db\.backends\.sqlite3" . --glob '!CHANGELOG.md' --glob '!docs/superpowers/plans/**' --glob '!docs/superpowers/specs/**'
```

Expected: no migration drift and no current-facing matches. `rg` exit 1 is the expected no-match result.

- [ ] **Step 3: Run the full repository gate through a managed hidden process**

```powershell
$env:PATH='C:\Users\lukas\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\override;C:\Users\lukas\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback;'+$env:PATH
$runId=[guid]::NewGuid().ToString('N')
$outLog=Join-Path $env:TEMP "timetracker-628-check-$runId.out.log"
$errLog=Join-Path $env:TEMP "timetracker-628-check-$runId.err.log"
$proc=Start-Process -FilePath (Get-Command make).Source -ArgumentList @('check') -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -Wait
Get-Content -Raw $outLog
Get-Content -Raw $errLog
$exitCode=$proc.ExitCode
Remove-Item -LiteralPath $outLog,$errLog -Force
if ($exitCode -ne 0) { exit $exitCode }
```

Expected: `make check` exits 0 using the Makefile's normal parallel worker count.

- [ ] **Step 4: Re-run the production-copy migration check after all edits**

Restore the accepted dump into the exact disposable database again:

```powershell
$pgBin=(Get-ChildItem '.cache/postgres-binaries/18.4.0' -Recurse -Filter postgres.exe | Select-Object -First 1).DirectoryName
$managedUrl=((Select-String -Path '.cache/postgres.mk' -Pattern '^export DATABASE_URL := (.+)$').Matches[0].Groups[1].Value)
$managedUri=[Uri]$managedUrl
$pgHost=$managedUri.Host
$pgPort=$managedUri.Port
$dump=Join-Path $env:TEMP 'timetracker-post-cutover-20260812.dump'
scp nas:/docker/timetracker/backups/postgres-cutover-20260812T154734+0200/timetracker-post-cutover.dump $dump
& (Join-Path $pgBin 'dropdb.exe') -h $pgHost -p $pgPort -U timetracker --if-exists timetracker_628_prod_copy
& (Join-Path $pgBin 'createdb.exe') -h $pgHost -p $pgPort -U timetracker timetracker_628_prod_copy
& (Join-Path $pgBin 'pg_restore.exe') -h $pgHost -p $pgPort -U timetracker --no-owner --no-privileges -d timetracker_628_prod_copy $dump
$prodCopyUrl="postgresql://timetracker@${pgHost}:$pgPort/timetracker_628_prod_copy"
$env:DATABASE_URL=$prodCopyUrl
$env:TIMETRACKER_MANAGED_DATABASE_URL='0'
uv run --frozen python manage.py migrate --check
uv run --frozen python manage.py showmigrations games --plan
```

Expected: exit 0, no pending operations, and the sole baseline marked applied.

Clean up only the exact disposable database and dump:

```powershell
$env:DATABASE_URL=$managedUrl
$env:TIMETRACKER_MANAGED_DATABASE_URL='1'
& (Join-Path $pgBin 'dropdb.exe') -h $pgHost -p $pgPort -U timetracker --if-exists timetracker_628_prod_copy
Remove-Item -LiteralPath $dump -Force
```

- [ ] **Step 5: Record handoff evidence**

Capture for the PR description:

```text
- restored production-copy `migrate --check`: PASS; squashed baseline applied
- production-copy vs fresh-baseline pg_get_expr comparison: identical
- focused concurrency/E2E teardown runs: PASS (three repetitions)
- current-facing SQLite audit: no matches outside classified history
- make check: PASS
```

Do not claim a pass without the current run's exit code and output. Then use `superpowers:requesting-code-review` before opening the PR and `superpowers:finishing-a-development-branch` for the integration handoff.
