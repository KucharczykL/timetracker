# PG-07 PostgreSQL Migration Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 36 historical `games` migrations with one regenerated squashed baseline that builds a complete database on PostgreSQL 17, proven equivalent to the history it retires.

**Architecture:** Repair the one model expression PostgreSQL rejects (`Session.duration_calculated` coalescing an interval against integer `0`), then delete the 36 migrations and regenerate a single squashed baseline from the repaired models, hand-adding a `replaces` list so existing SQLite installations record it as applied instead of recreating live tables. A static test guards the three defect classes being removed, and a new `make` target keeps migration drift out of the tree. PostgreSQL verification is a one-shot throwaway container whose output is pasted into the pull request; PG-13 (#615) owns making it routine.

**Tech Stack:** Python 3.14, Django 6 migrations and `GeneratedField`, pytest-django, ruff, podman, PostgreSQL 17, GNU Make.

## Global Constraints

- Scope is PG-07 only: add no database dependency to `pyproject.toml`, no `DATABASE_URL` handling, no settings change, and no PostgreSQL-backed test. PG-11 (#613) owns configuration, PG-12 (#614) dev provisioning, PG-13 (#615) test topology.
- **The baseline file MUST be named `0001_squashed_0036_alter_playevent_days_to_finish.py`, not `0001_initial.py`.** A squashed migration whose `replaces` list contains its own key is a cycle: `MigrationLoader.replace_migration` recurses into every replaced key that is itself a replacement, and aborts with `CommandError: Cyclical squash replacement found, starting at ('games', '0001_initial')`. That fires inside `build_graph()`, so it kills `migrate`, `makemigrations`, `showmigrations`, and every pytest-django test-database build.
- The baseline keeps `initial = True` and carries `replaces` naming all 36 retired migrations under app label `games`.
- Persisted column names and output types are unchanged: `duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`.
- The interval repair must produce byte-identical SQLite generated-column SQL. Any SQLite DDL change other than column order is a plan failure.
- **`ARGS` scopes `make test` only.** `test` is `pytest -n $(PYTEST_WORKERS) $(ARGS)` with no default path, so `ARGS` selects. `test-fast` is `pytest tests/ … $(ARGS)` and `test-e2e` is `pytest e2e/ … $(ARGS)`, where `ARGS` *appends a second target* and silently runs the whole suite. Never use `ARGS` with those two.
- **There is no `sqlite3` CLI in this environment.** `shell.nix` provides only `nodejs_26`, `python3`, `uv`, `ruff`, and `pnpm_10`. Read databases with `uv run --frozen python`.
- `makemigrations` writes Django-writer style, which is not ruff-formatted. Every task that generates or hand-writes Python runs `make lint-fix` and `make format` before committing.
- The final verification gate is the full `make check`, including `e2e/`.

---

## File structure

- Modify `games/models.py:317-331`: replace the integer `0` fallback with `timedelta(0)` in both `Session.duration_calculated` and the `duration_total` sum that repeats the same expression.
- Delete `games/migrations/0001_initial.py` through `games/migrations/0036_alter_playevent_days_to_finish.py` (36 files).
- Create `games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py`: the regenerated baseline plus a hand-added `replaces` list.
- Delete `tests/test_migration_sentinel_removal.py`: it round-trips migration 0024 by pinning the module names `0023_alter_game_platform_alter_purchase_platform_and_more` and `0025_game_unique_platformless_game_name_year` (`tests/test_migration_sentinel_removal.py:21-22`) and driving `MigrationExecutor.migrate()` between them. All three migrations are retired by the baseline, so the test raises `KeyError` on a name that no longer exists. It cannot be repaired — there is no surviving migration to round-trip.
- Create `tests/test_migration_portability.py`: static guard rejecting `RawSQL`/`RunSQL`, generated-on-generated columns, and SQLite-only function names in the migration source.
- Modify `Makefile`: add a `check-migrations` target and wire it into `check` and `check-fast`, giving the spec's `makemigrations --check` requirement a permanent home.

---

### Task 1: Repair the interval literal PostgreSQL rejects

**Files:**
- Modify: `games/models.py:317-331`
- Test: `tests/test_generated_duration_columns.py` (existing; must stay green unchanged)

**Interfaces:**
- Consumes: `games.models.Session`, `django.db.models.functions.Coalesce`, `datetime.timedelta` (already imported at `games/models.py:11` and `games/models.py:2`).
- Produces: `Session.duration_calculated` and `Session.duration_total` whose generated expressions coalesce against a `timedelta(0)` literal rather than integer `0`. Values and column types unchanged on both backends.

Committed together with Task 2 — changing the model without regenerating migrations leaves drift.

- [ ] **Step 1: Build a database from the retiring history, before touching the model**

```bash
rm -rf /tmp/pg07 && mkdir -p /tmp/pg07/at0036 && DATA_DIR=/tmp/pg07/at0036 make migrate
```

Expected: applies `games.0001_initial` through `games.0036_alter_playevent_days_to_finish`, then loads the ExchangeRate fixture.

Order matters: `migrate` depends on `makemigrations` in the Makefile, so running it *after* the model edit would write a stray `0037`. `Coalesce(…, 0)` and `Coalesce(…, timedelta(0))` deconstruct differently, so the edit is genuinely detected as drift.

- [ ] **Step 2: Record the generated-column clauses as the comparison baseline**

```bash
uv run --frozen python - <<'PY'
import pathlib, re, sqlite3
rows = sqlite3.connect("/tmp/pg07/at0036/db.sqlite3").execute(
    "select sql from sqlite_master where name like 'games_%' and sql is not null"
)
clauses = sorted(
    " ".join(match.split())
    for (sql,) in rows
    for match in re.findall(r'"\w+"[^,]*?GENERATED ALWAYS AS \(.*?\) STORED', sql)
)
pathlib.Path("/tmp/pg07/generated-before.txt").write_text("\n".join(clauses))
print(len(clauses), "generated columns")
print(*clauses, sep="\n")
PY
```

Expected: `4 generated columns` — `days_to_finish`, `price_per_game`, `duration_calculated`, `duration_total`. Note these come from **3** `CREATE TABLE` rows: `games_session` carries two of them.

- [ ] **Step 3: Apply the repair**

In `games/models.py`, change both `Coalesce(...)` fallbacks from `0` to `timedelta(0)`:

```python
    duration_calculated = GeneratedField(
        expression=Coalesce(F("timestamp_end") - F("timestamp_start"), timedelta(0)),
        output_field=models.DurationField(),
        db_persist=True,
        editable=False,
    )
    duration_total = GeneratedField(
        expression=DatabaseDurationSum(
            Coalesce(F("timestamp_end") - F("timestamp_start"), timedelta(0)),
            F("duration_manual"),
        ),
        output_field=models.DurationField(),
        db_persist=True,
        editable=False,
    )
```

The integer `0` renders as `COALESCE(<interval>, 0)` on PostgreSQL, which fails with `COALESCE types interval and integer cannot be matched`. `Coalesce` wraps the bare `timedelta` in a `Value` through `_parse_expressions`, so no explicit `Value(...)` is needed. On SQLite both literals render as the same integer-microsecond parameter, so the emitted DDL is unchanged.

Run `make format` — the `duration_calculated` expression fits in 88 columns and ruff will collapse it to one line.

- [ ] **Step 4: Prove the existing duration coverage stays green**

Run: `make test ARGS="tests/test_generated_duration_columns.py -v"`
Expected: PASS.

This file asserts more than values — `test_duration_total_uses_only_source_columns` (`tests/test_generated_duration_columns.py:43-55`) inspects `field.expression.flatten()` for `F` references, checks `db_persist` and `output_field`, and renders `field.generated_sql(connection)`. It passes because `timedelta(0)` and `0` emit identical SQLite SQL: `COALESCE(django_timestamp_diff("timestamp_end", "timestamp_start"), %s)` with parameter `0` either way. If this test fails, the repair changed SQLite DDL and the plan's premise is broken — stop.

Do not commit yet; Task 2 carries this edit.

---

### Task 2: Replace the 36 migrations with the regenerated baseline

**Files:**
- Delete: `games/migrations/0001_initial.py` … `games/migrations/0036_alter_playevent_days_to_finish.py`
- Delete: `tests/test_migration_sentinel_removal.py`
- Create: `games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py`
- Modify: `Makefile` (add `check-migrations`, wire into `check` and `check-fast`)
- Modify: `games/models.py` (carries Task 1's edit into this commit)

**Interfaces:**
- Consumes: `games/models.py` as repaired in Task 1.
- Produces: `games.migrations.0001_squashed_0036_alter_playevent_days_to_finish` with `initial = True` and `replaces = [("games", "0001_initial"), … 36 entries]`, which Django records as applied on any database where all 36 originals are recorded.

- [ ] **Step 1: Capture the retiring history's full schema**

```bash
uv run --frozen python - <<'PY'
import json, sqlite3
rows = sqlite3.connect("/tmp/pg07/at0036/db.sqlite3").execute(
    "select type, name, sql from sqlite_master "
    "where sql is not null and name not like 'sqlite_%'"
)
schema = {f"{t}:{n}": " ".join(s.split()) for t, n, s in rows}
open("/tmp/pg07/schema-history.json", "w").write(json.dumps(schema, indent=1, sort_keys=True))
print(len(schema), "objects captured")
PY
```

- [ ] **Step 2: Record the replaces list, then delete the originals**

```bash
uv run --frozen python - <<'PY'
import pathlib
names = sorted(p.stem for p in pathlib.Path("games/migrations").glob("0*.py"))
pathlib.Path("/tmp/pg07/replaces.txt").write_text(
    "\n".join(f'        ("games", "{n}"),' for n in names)
)
print(len(names), "migrations recorded ->", names[0], "..", names[-1])
PY
rm games/migrations/0*.py
rm -rf games/migrations/__pycache__
```

Expected: `36 migrations recorded -> 0001_initial .. 0036_alter_playevent_days_to_finish`, then `games/migrations/` empty apart from `__init__.py`.

Removing `__pycache__` keeps the diff clean and stops a reviewer mistaking stale bytecode for surviving files.

- [ ] **Step 3: Regenerate the baseline**

Run: `make makemigrations`
Expected: a new `games/migrations/0001_initial.py` listing `Create model Device`, `Game`, `Platform`, `SiteSetting`, `ExchangeRate`, `GameStatusChange`, `PlayEvent`, `Purchase`, `Session`, `UserPreferences`, `FilterPreset`, then `Add field platform to game`, the `unique_platformless_game_name_year` constraint, and `Alter unique_together for game (1 constraint(s))`. Roughly 205 lines as written by Django.

- [ ] **Step 4: Rename it to a squashed name**

```bash
git mv games/migrations/0001_initial.py \
       games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py 2>/dev/null \
  || mv games/migrations/0001_initial.py \
        games/migrations/0001_squashed_0036_alter_playevent_days_to_finish.py
```

This is not cosmetic. Step 5 adds `("games", "0001_initial")` to `replaces`; if the file were still named `0001_initial`, that entry would name the migration itself and Django would abort with `Cyclical squash replacement found`.

- [ ] **Step 5: Hand-add the replaces list**

Insert into the `Migration` class, directly after `initial = True`, using the 36 lines from `/tmp/pg07/replaces.txt`:

```python
class Migration(migrations.Migration):
    initial = True

    replaces = [
        ("games", "0001_initial"),
        ("games", "0002_purchase_price_per_game"),
        # … all 36 entries from /tmp/pg07/replaces.txt, in generated order …
        ("games", "0036_alter_playevent_days_to_finish"),
    ]

    dependencies = [...]
```

Keep `initial = True`. Without `replaces`, Django would attempt `CREATE TABLE` against live tables on any existing installation.

- [ ] **Step 6: Format and lint the generated file**

```bash
make lint-fix
make format
```

Django's migration writer emits single quotes and long lines, and puts `import games.expressions` in the wrong isort block — `ruff check` reports `I001` on it, which is *not* in the per-file ignore list (`pyproject.toml:73` ignores only `RUF012` for migrations). After formatting the file grows to roughly 668 lines.

- [ ] **Step 7: Delete the migration round-trip test the baseline invalidates**

```bash
git rm tests/test_migration_sentinel_removal.py
```

It pins `("games", "0023_alter_game_platform_alter_purchase_platform_and_more")` and `("games", "0025_game_unique_platformless_game_name_year")` at `tests/test_migration_sentinel_removal.py:21-22` and calls `MigrationExecutor.migrate()` between them to exercise migration 0024's sentinel removal. With those names retired it raises `KeyError` in `executor.py`. It is not repairable: its subject is a historical data migration that no longer exists, and the invariant it guarded — no sentinel Platform or Device rows — is now structural, since both foreign keys are nullable with no sentinel to create.

- [ ] **Step 8: Add a permanent migration-drift target**

In `Makefile`, add after the `makemigrations` target:

```makefile
check-migrations:
	uv run --frozen python manage.py makemigrations --check --dry-run
```

and add `check-migrations` to both aggregate lists:

```makefile
check: ensure-python lint format-check typecheck ts-check check-icons check-migrations test-ts test

check-fast: ensure-python lint format-check typecheck ts-check check-icons check-migrations test-ts test-fast
```

The spec requires `makemigrations --check` to be clean, and nothing in `make check` checked migration drift before. Bare `make makemigrations` is not a substitute — on drift it *writes* a `0002_*.py` instead of failing.

- [ ] **Step 9: Confirm the baseline equals the model state**

Run: `make check-migrations`
Expected: exit 0, no output. This is the proof that the baseline is the current models, which is why regeneration was chosen over `squashmigrations` — the seven `RunPython`/`RunSQL` migrations are optimizer barriers that would leave the julianday `RawSQL` and the generated-on-generated column intact.

- [ ] **Step 10: Prove the generated-column SQL is unchanged**

```bash
rm -rf /tmp/pg07/after && mkdir -p /tmp/pg07/after && DATA_DIR=/tmp/pg07/after make migrate
uv run --frozen python - <<'PY'
import pathlib, re, sqlite3
def clauses(path):
    rows = sqlite3.connect(path).execute(
        "select sql from sqlite_master where name like 'games_%' and sql is not null"
    )
    return sorted(
        " ".join(m.split())
        for (sql,) in rows
        for m in re.findall(r'"\w+"[^,]*?GENERATED ALWAYS AS \(.*?\) STORED', sql)
    )
before = pathlib.Path("/tmp/pg07/generated-before.txt").read_text().splitlines()
after = clauses("/tmp/pg07/after/db.sqlite3")
print("IDENTICAL" if before == after else "DIFFERS")
for line in set(before) ^ set(after):
    print("  only one side:", line)
PY
```

Expected: `IDENTICAL`. Compare the extracted clauses as a sorted list — never whole `CREATE TABLE` statements, whose row order and column order both legitimately differ.

- [ ] **Step 11: Prove schema equivalence against the retired history**

```bash
uv run --frozen python - <<'PY'
import json, re, sqlite3
def objects(path):
    rows = sqlite3.connect(path).execute(
        "select type, name, sql from sqlite_master "
        "where sql is not null and name not like 'sqlite_%'"
    )
    return {f"{t}:{n}": " ".join(s.split()) for t, n, s in rows}
history = json.load(open("/tmp/pg07/schema-history.json"))
baseline = objects("/tmp/pg07/after/db.sqlite3")
print("only in history:", sorted(set(history) - set(baseline)))
print("only in baseline:", sorted(set(baseline) - set(history)))
columns = lambda sql: sorted(re.findall(r'"(\w+)"\s+[a-z]', sql))
for key in sorted(set(history) & set(baseline)):
    if columns(history[key]) != columns(baseline[key]):
        print("COLUMN SET DIFFERS:", key)
    elif history[key] != baseline[key]:
        print("column order differs (accepted):", key)
PY
```

Expected: both "only in" lists empty, no `COLUMN SET DIFFERS` line, and exactly six `column order differs (accepted)` lines — `games_game`, `games_platform`, `games_playevent`, `games_purchase`, `games_session`, `games_userpreferences`. Save the output for the pull request.

- [ ] **Step 12: Prove the baseline is a no-op on an existing 0036 database**

```bash
DATA_DIR=/tmp/pg07/at0036 make migrate
uv run --frozen python -c "
import sqlite3
connection = sqlite3.connect('/tmp/pg07/at0036/db.sqlite3')
print('games rows:', connection.execute(\"select count(*) from django_migrations where app='games'\").fetchone()[0])
print('newest:', connection.execute(\"select name from django_migrations where app='games' order by id desc limit 1\").fetchone()[0])
"
```

Expected: `migrate` prints `No migrations to apply.`, then `games rows: 37` and `newest: 0001_squashed_0036_alter_playevent_days_to_finish`.

The count goes 36 → 37 because `MigrationExecutor.check_replacements` records the squashed migration itself once all replaced keys are applied. That extra row *is* the mechanism — it is what makes this a no-op rather than an attempted table creation. This is the direct evidence that the maintainer's production database, running `main-a62da2c` at 0036, needs no operator action. Record the exact output for the pull request.

- [ ] **Step 13: Run the non-browser gate**

Run: `make check-fast`
Expected: PASS. The test database is built from the baseline, so the whole suite now exercises it.

- [ ] **Step 14: Commit**

```bash
git add games/models.py games/migrations/ Makefile
git add -u tests/test_migration_sentinel_removal.py
git commit -m "refactor: replace migration history with a PostgreSQL baseline"
```

---

### Task 3: Guard the removed defect classes

**Files:**
- Create: `tests/test_migration_portability.py`

**Interfaces:**
- Consumes: `django.db.migrations.loader.MigrationLoader` to read the `games` migration set, `django.db.models.fields.generated.GeneratedField`, and `django.conf.settings.BASE_DIR` for a cwd-independent path.
- Produces: no importable API; a test module only.

- [ ] **Step 1: Write the guard**

Create `tests/test_migration_portability.py`:

```python
"""Reject the SQLite-only constructs PG-07 removed from the migration set.

PostgreSQL verification is a manual, one-shot container run until PG-13 (#615)
supplies a harness, so the three defect classes that each aborted a fresh
PostgreSQL build are held out statically in the meantime.

Known blind spots, covered instead by the PostgreSQL build itself: RunSQL
nested inside SeparateDatabaseAndState, and lookups inside a Q object, whose
left-hand side Q.flatten() discards.
"""

import pathlib

import pytest
from django.conf import settings
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunSQL
from django.db.models import F, Q
from django.db.models.expressions import RawSQL
from django.db.models.fields.generated import GeneratedField

# Excludes date(/datetime(, which collide with datetime.date(...) and
# datetime.datetime(...) field defaults — ordinary Python, not SQLite calls.
SQLITE_ONLY_FUNCTIONS = ("julianday(", "strftime(", "unixepoch(")

GENERATED_COLUMNS = frozenset(
    {"duration_calculated", "duration_total", "price_per_game", "days_to_finish"}
)


def migration_directory():
    directory = pathlib.Path(settings.BASE_DIR) / "games" / "migrations"
    assert directory.is_dir(), f"migration package missing at {directory}"
    return directory


def games_migrations():
    loader = MigrationLoader(connection=None, ignore_no_migrations=True)
    migrations = [
        (name, migration)
        for (app_label, name), migration in loader.disk_migrations.items()
        if app_label == "games"
    ]
    assert migrations, "no games migrations discovered"
    return migrations


def generated_fields(migration):
    """Yield (operation, field) for every GeneratedField the operation declares."""
    for operation in migration.operations:
        entries = [(None, getattr(operation, "field", None))]
        entries += list(getattr(operation, "fields", None) or [])
        for _, field in entries:
            if isinstance(field, GeneratedField):
                yield operation, field


def referenced_column_names(expression):
    """Column names an expression reads, including Q lookup left-hand sides."""
    names = set()
    for node in expression.flatten():
        if isinstance(node, F):
            names.add(node.name.split("__")[0])
        elif isinstance(node, Q):
            for child in node.children:
                if isinstance(child, tuple):
                    names.add(child[0].split("__")[0])
    return names


def test_no_run_sql_operations():
    offenders = [
        name
        for name, migration in games_migrations()
        for operation in migration.operations
        if isinstance(operation, RunSQL)
    ]
    assert offenders == [], f"RunSQL is not portable; found in {offenders}"


def test_no_raw_sql_in_generated_columns():
    offenders = [
        name
        for name, migration in games_migrations()
        for _, field in generated_fields(migration)
        if any(isinstance(node, RawSQL) for node in field.expression.flatten())
    ]
    assert offenders == [], f"RawSQL in a generated column; found in {offenders}"


def test_no_generated_column_reads_another_generated_column():
    offenders = []
    for name, migration in games_migrations():
        for operation, field in generated_fields(migration):
            own = getattr(operation, "name", None)
            # AddField/AlterField.name is the field; CreateModel.name is the
            # model, which merely widens the forbidden set for that operation.
            forbidden = GENERATED_COLUMNS - {own}
            read = referenced_column_names(field.expression) & forbidden
            if read:
                offenders.append((name, own, sorted(read)))
    assert offenders == [], (
        f"PostgreSQL forbids a generated column reading another; found {offenders}"
    )


@pytest.mark.parametrize("function", SQLITE_ONLY_FUNCTIONS)
def test_no_sqlite_only_function_names_in_migration_source(function):
    offenders = [
        path.name
        for path in sorted(migration_directory().glob("0*.py"))
        if function in path.read_text()
    ]
    assert offenders == [], f"{function} is SQLite-only; found in {offenders}"
```

- [ ] **Step 2: Format and lint it**

```bash
make lint-fix
make format
```

Hand-written import blocks reliably trip `I001`, and ruff reformats several of the comprehensions above. Do this before running the test, so Step 5's commit is already gate-clean.

- [ ] **Step 3: Verify the guard catches the defects it exists for**

Temporarily restore the retired history. Do **not** use `git stash` — it would park the new test file rather than the migrations, and the run would fail on a missing file instead of on the defects.

```bash
BASELINE=$(git rev-parse HEAD)
git checkout HEAD~1 -- games/migrations/
make test ARGS="tests/test_migration_portability.py -v"
```

`HEAD` is Task 2's commit, so `HEAD~1` is the pre-baseline tree. Checking out the path restores the 36 originals; the baseline file has no counterpart there and survives, which is fine — the guard reports every offender it finds.

Expected: four failures —
- `test_no_run_sql_operations` reports `0016_add_needs_price_update`
- `test_no_raw_sql_in_generated_columns` reports `0008_game_original_year_released_gamestatuschange_and_more`
- `test_no_generated_column_reads_another_generated_column` reports `0014_session_duration_total`
- `test_no_sqlite_only_function_names_in_migration_source[julianday(]` reports `0008_game_original_year_released_gamestatuschange_and_more`

This step is the whole point of the guard — if it passes against the old history, it is not testing anything. Restore:

```bash
rm games/migrations/0*.py
git checkout $BASELINE -- games/migrations/
git status --short
```

Expected: only the untracked test file. The `rm` is required because the 36 originals do not exist in `$BASELINE`, so checking that path out will not remove them.

- [ ] **Step 4: Verify the guard passes against the baseline**

Run: `make test ARGS="tests/test_migration_portability.py -v"`
Expected: PASS, all six cases (three plus three parametrized).

- [ ] **Step 5: Commit**

```bash
git add tests/test_migration_portability.py
git commit -m "test: reject SQLite-only constructs in migrations"
```

---

### Task 4: Verify a fresh PostgreSQL 17 build

**Files:**
- No repository files. Artifacts live in `/tmp/pg07/` and are pasted into the pull request.

**Interfaces:**
- Consumes: the committed baseline from Task 2.
- Produces: pull-request evidence only.

This is the one task that runs outside `make`. The project has no PostgreSQL driver and gains none here; PG-13 (#615) owns turning this into a repeatable target, which is why no target is added for it now.

- [ ] **Step 1: Start PostgreSQL 17 matching PG-05's locale contract**

```bash
podman run -d --rm --name tt-pg07 \
  -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=timetracker \
  -e POSTGRES_INITDB_ARGS="--locale-provider=builtin --builtin-locale=C.UTF-8 --encoding=UTF8" \
  -p 55432:5432 docker.io/library/postgres:17
```

Then: `podman exec tt-pg07 pg_isready -U postgres`
Expected: `accepting connections`.

The locale flags are not cosmetic — PG-05 (#607) made the `builtin` provider with builtin locale `C.UTF-8` part of the deployment contract, so verification must build under it.

- [ ] **Step 2: Write a throwaway settings overlay**

Create `/tmp/pg07/pg_settings.py`:

```python
from timetracker.settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "timetracker",
        "USER": "postgres",
        "PASSWORD": "verify",
        "HOST": "127.0.0.1",
        "PORT": "55432",
    }
}
```

It lives outside the repository on purpose: `timetracker/settings.py:145` still hardcodes SQLite, and changing that is PG-11's outcome.

- [ ] **Step 3: Build the database**

```bash
PYTHONPATH=/tmp/pg07 DJANGO_SETTINGS_MODULE=pg_settings \
  uv run --frozen --with "psycopg[binary]" python manage.py migrate
```

Expected: every app applies, ending with `games.0001_squashed_0036_alter_playevent_days_to_finish... OK` and `sessions.0001_initial... OK`, then the ExchangeRate fixture loads. Any `ProgrammingError` here is a real portability defect, not an environment problem.

- [ ] **Step 4: Prove the generated columns compute, not merely parse**

```bash
PYTHONPATH=/tmp/pg07 DJANGO_SETTINGS_MODULE=pg_settings \
  uv run --frozen --with "psycopg[binary]" python manage.py shell -c "
import datetime as dt
from django.db.models import Sum
from django.utils import timezone
from games.models import Game, PlayEvent, Purchase, Session

game = Game.objects.create(name='Verify', sort_name='verify')
start = timezone.now()
Session.objects.create(game=game, timestamp_start=start, timestamp_end=start + dt.timedelta(hours=2))
Session.objects.create(game=game, timestamp_start=start, duration_manual=dt.timedelta(minutes=30))
Session.objects.create(game=game, timestamp_start=start, timestamp_end=start + dt.timedelta(hours=1), duration_manual=dt.timedelta(minutes=15))
for session in Session.objects.order_by('id'):
    session.refresh_from_db()
    print('session', session.duration_calculated, session.duration_total)
print('duration_total sum', Session.objects.aggregate(total=Sum('duration_total'))['total'])
PlayEvent.objects.create(game=game, started=dt.date(2026, 1, 1), ended=dt.date(2026, 1, 11))
PlayEvent.objects.create(game=game, started=dt.date(2026, 1, 1), ended=dt.date(2026, 1, 1))
PlayEvent.objects.create(game=game, started=dt.date(2026, 1, 1))
for event in PlayEvent.objects.order_by('id'):
    event.refresh_from_db()
    print('days_to_finish', event.days_to_finish)
linked = Purchase.objects.create(date_purchased=dt.date(2026, 1, 1), price=30, price_currency='USD', num_purchases=3)
unlinked = Purchase.objects.create(date_purchased=dt.date(2026, 1, 1), price=30, price_currency='USD')
linked.refresh_from_db(); unlinked.refresh_from_db()
print('price_per_game', linked.price_per_game, unlinked.price_per_game)
game.refresh_from_db(); print('playtime', game.playtime)
"
```

Expected exactly:

```
session 2:00:00 2:00:00
session 0:00:00 0:30:00
session 1:00:00 1:15:00
duration_total sum 3:45:00
days_to_finish 10
days_to_finish 1
days_to_finish 0
price_per_game 10.0 None
playtime 3:45:00
```

`days_to_finish 1` is the same-day rule from PG-03 (#605). `price_per_game None` is the `NULLIF` guard from PG-02 (#604) — a Purchase with no linked games must yield NULL, not a division error. The explicit `duration_total sum` aggregate is what exercises `duration_total` on PostgreSQL; `playtime` does **not**, because `games/signals.py:111-113` recomputes it as `Sum(F("duration_calculated") + F("duration_manual"))` rather than from `duration_total`.

- [ ] **Step 5: Tear down**

```bash
podman rm -f tt-pg07
```

- [ ] **Step 6: Record the evidence**

Paste into the pull-request body: the Step 3 migrate tail, the Step 4 output, and Task 2's Step 10, Step 11, and Step 12 outputs. No commit — the spec chose one-shot evidence over a permanent harness.

---

### Task 5: Gate and open the pull request

- [ ] **Step 1: Run the full gate**

Run: `make check`
Expected: PASS, including `e2e/` and the new `check-migrations`. Do not substitute `check-fast`; only the full gate catches browser-test breakage.

Ensure `make dev` is not running — its watchers rewrite served assets and cause mass phantom e2e failures.

- [ ] **Step 2: Open the pull request**

Body includes the Task 4 Step 6 evidence, a statement that the interval repair is PG-01 (#603) rework and why it lands here, the deletion of `tests/test_migration_sentinel_removal.py` with its justification, and a link to the Plan adjustments entry in #599.

Follow-up issues are already filed — #809 (`replaces` removal after cutover), #810 (transfer copies by column name), #811 (re-verify PG-01..PG-06) — and slotted into #600. Reference them; do not create new ones.

---

## Gotchas

- **A squashed migration must not name itself in `replaces`.** This is the single most likely way to break this task; see Global Constraints.
- **`make migrate` runs `makemigrations` first.** On a clean tree it prints `No changes detected`; between Task 1's model edit and Task 2's regeneration it would write a stray `0037`. Task 1 Step 1 must run before the edit.
- **`DATA_DIR` controls the database location** and is read by `timetracker/config.py`, so throwaway builds need no settings change.
- **`tests/test_migration_sentinel_removal.py` is the only file outside `games/migrations/` that references migration module names.** Everything else naming them is prose in `docs/`. Task 2 Step 7 deletes it.
- **The nine data operations are not carried over deliberately.** `initialize_num_purchases`, `set_finished_status`, `copy_year_released`, `set_abandoned_status`, `create_game_status_changes`, `calculate_game_playtime`, the `needs_price_update` UPDATE, `backfill_related_game`, and `remove_sentinels` are all filters or updates over rows that cannot exist in an empty database. The ExchangeRate seed comes from `games/apps.py:42-45`'s `post_migrate` hook, not a migration, so nothing seeded is lost.
- **`duration_manual` defaults to `timedelta(0)`** (`games/models.py:314-316`), which is why `duration_total` does not go NULL for a Session with no manual duration. Do not "fix" that with a second `Coalesce`.
- **`games/expressions.py:30-36` still emits `julianday(`** into SQLite DDL from `DatabaseDateDifference.as_sqlite`, and the baseline reaches it by importing the class. The source-text guard cannot see that, and should not — it is the correct dialect-aware rendering. The guard targets literal SQLite SQL written into migration files.
- **The shell here is fish.** Every heredoc, `$( )`, and `VAR=value cmd` block above is POSIX syntax; run them through `bash -c` if invoking by hand.
