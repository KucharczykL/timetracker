# PG-07 PostgreSQL Migration Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 36 historical `games` migrations with one regenerated `0001_initial` that builds a complete database on PostgreSQL 17, proven equivalent to the history it retires.

**Architecture:** Repair the one model expression PostgreSQL rejects (`Session.duration_calculated` coalescing an interval against integer `0`), then delete the 36 migrations and regenerate a single `0001_initial` from the repaired models, hand-adding a `replaces` list so existing SQLite installations record it as applied instead of recreating live tables. A static test guards the three defect classes being removed. PostgreSQL verification is a one-shot throwaway container whose output is pasted into the pull request; PG-13 owns making it routine.

**Tech Stack:** Python 3.14, Django 6 migrations and `GeneratedField`, pytest-django, podman, PostgreSQL 17, GNU Make.

## Global Constraints

- Scope is PG-07 only: add no database dependency to `pyproject.toml`, no `DATABASE_URL` handling, no settings change, no `make` target, and no PostgreSQL-backed test. PG-11 owns configuration, PG-12 dev provisioning, PG-13 test topology.
- The baseline keeps `initial = True` and carries `replaces` naming all 36 retired migrations under app label `games`.
- Persisted column names and output types are unchanged: `duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`.
- The interval repair must produce byte-identical SQLite generated-column SQL. Any SQLite DDL change other than column order is a plan failure.
- Use `make` targets for project commands. The single exception is the PostgreSQL verification in Task 3, which needs a driver the project does not depend on; it is deliberately not a `make` target.
- The final verification gate is the full `make check`, including `e2e/`.

---

## File structure

- Modify `games/models.py:317-327`: replace the integer `0` fallback with `timedelta(0)` in both `Session.duration_calculated` and the `duration_total` sum that repeats the same expression.
- Delete `games/migrations/0001_initial.py` through `games/migrations/0036_alter_playevent_days_to_finish.py` (36 files).
- Create `games/migrations/0001_initial.py`: the regenerated baseline plus a hand-added `replaces` list.
- Create `tests/test_migration_portability.py`: static guard rejecting `RawSQL`/`RunSQL`, generated-on-generated columns, and SQLite-only function names in `games/migrations/`.

---

### Task 1: Repair the interval literal PostgreSQL rejects

**Files:**
- Modify: `games/models.py:317-327`
- Test: `tests/test_generated_duration_columns.py` (existing; must stay green unchanged)

**Interfaces:**
- Consumes: `games.models.Session`, `django.db.models.functions.Coalesce`, `datetime.timedelta` (both already imported in `games/models.py:11` and `games/models.py:2`).
- Produces: `Session.duration_calculated` and `Session.duration_total` whose generated expressions coalesce against a `timedelta(0)` literal rather than integer `0`. Values and column types are unchanged on both backends.

This task is committed together with Task 2, because changing the model without regenerating migrations leaves `makemigrations --check` dirty. Do the edit here, verify semantics, and carry it into Task 2's commit.

- [ ] **Step 1: Record the current SQLite generated-column SQL as the comparison baseline**

```bash
rm -rf /tmp/pg07/before && mkdir -p /tmp/pg07/before && DATA_DIR=/tmp/pg07/before make migrate
```

Expected: applies `games.0001_initial` through `games.0036_alter_playevent_days_to_finish`, then loads the ExchangeRate fixture.

- [ ] **Step 2: Dump the generated-column expressions**

```bash
sqlite3 /tmp/pg07/before/db.sqlite3 "select sql from sqlite_master where name like 'games_%' and sql like '%GENERATED%'" > /tmp/pg07/generated-before.sql
```

Expected: four `GENERATED ALWAYS AS (…) STORED` clauses — `days_to_finish`, `price_per_game`, `duration_calculated`, `duration_total`.

- [ ] **Step 3: Apply the repair**

In `games/models.py`, replace both `Coalesce(...)` fallbacks:

```python
    duration_calculated = GeneratedField(
        expression=Coalesce(
            F("timestamp_end") - F("timestamp_start"), timedelta(0)
        ),
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

The integer `0` renders as `COALESCE(<interval>, 0)` on PostgreSQL, which fails with `COALESCE types interval and integer cannot be matched`. On SQLite both literals render as integer microseconds, so the emitted DDL is unchanged.

- [ ] **Step 4: Prove the existing duration semantics are untouched**

Run: `make test-fast ARGS="tests/test_generated_duration_columns.py -v"`
Expected: PASS. This file covers ended-timed, manual-only, and ended-with-manual Sessions; it asserts values, not expression shape, so it must pass without edits.

- [ ] **Step 5: Prove the SQLite DDL is byte-identical**

Regenerating migrations happens in Task 2, so compare through a fresh throwaway build once Task 2's baseline exists. Record here that `/tmp/pg07/generated-before.sql` is the artifact Task 2 Step 7 diffs against. Do not commit yet.

---

### Task 2: Replace the 36 migrations with the regenerated baseline

**Files:**
- Delete: `games/migrations/0001_initial.py` … `games/migrations/0036_alter_playevent_days_to_finish.py`
- Create: `games/migrations/0001_initial.py`
- Modify: `games/models.py` (carries Task 1's edit into this commit)

**Interfaces:**
- Consumes: `games/models.py` as repaired in Task 1.
- Produces: `games.migrations.0001_initial` with `initial = True` and `replaces = [("games", "0001_initial"), … 36 entries]`, which Django treats as applied on any database where all 36 originals are recorded.

- [ ] **Step 1: Build a database at 0036 to test the upgrade path against**

```bash
rm -rf /tmp/pg07/at0036 && mkdir -p /tmp/pg07/at0036 && DATA_DIR=/tmp/pg07/at0036 make migrate
```

Expected: all 36 applied. This database stands in for the maintainer's production box, which runs `main-a62da2c` at migration 0036. Keep it — Step 8 proves the baseline is a no-op against it.

- [ ] **Step 2: Capture the retiring history's full schema**

```bash
sqlite3 /tmp/pg07/at0036/db.sqlite3 .schema > /tmp/pg07/schema-history.sql
```

- [ ] **Step 3: Record the replaces list, then delete the originals**

```bash
uv run --frozen python - <<'PY'
import pathlib
names = sorted(p.stem for p in pathlib.Path("games/migrations").glob("0*.py"))
pathlib.Path("/tmp/pg07/replaces.txt").write_text(
    "\n".join(f'        ("games", "{n}"),' for n in names)
)
print(len(names), "migrations recorded")
PY
rm games/migrations/0*.py
rm -rf games/migrations/__pycache__
```

Expected: `36 migrations recorded`, then an empty `games/migrations/` apart from `__init__.py`.

Removing `__pycache__` matters: stale bytecode for deleted modules confuses nothing in Django's loader, but leaving it makes the `git status` diff noisy and can mislead a reviewer into thinking files survived.

- [ ] **Step 4: Regenerate the baseline**

Run: `make makemigrations`
Expected: `games/migrations/0001_initial.py` listing `Create model Device`, `Game`, `Platform`, `SiteSetting`, `ExchangeRate`, `GameStatusChange`, `PlayEvent`, `Purchase`, `Session`, `UserPreferences`, `FilterPreset`, plus the `unique_platformless_game_name_year` constraint. The file is roughly 205 lines.

- [ ] **Step 5: Hand-add the replaces list**

Insert into the `Migration` class in `games/migrations/0001_initial.py`, directly after `initial = True`, using the 36 lines from `/tmp/pg07/replaces.txt`:

```python
class Migration(migrations.Migration):
    initial = True

    replaces = [
        ("games", "0001_initial"),
        ("games", "0002_purchase_price_per_game"),
        # … all 36 entries from /tmp/pg07/replaces.txt, in order …
        ("games", "0036_alter_playevent_days_to_finish"),
    ]

    dependencies = [
        ...
    ]
```

Keep `initial = True`. Without `replaces`, Django would attempt `CREATE TABLE` against live tables on any existing installation.

- [ ] **Step 6: Confirm the baseline equals the model state**

Run: `make makemigrations`
Expected: `No changes detected`. This is the proof that the baseline is the current models, which is why regeneration was chosen over `squashmigrations`.

- [ ] **Step 7: Prove schema equivalence against the retired history**

```bash
rm -rf /tmp/pg07/after && mkdir -p /tmp/pg07/after && DATA_DIR=/tmp/pg07/after make migrate
sqlite3 /tmp/pg07/after/db.sqlite3 .schema > /tmp/pg07/schema-baseline.sql
sqlite3 /tmp/pg07/after/db.sqlite3 "select sql from sqlite_master where name like 'games_%' and sql like '%GENERATED%'" > /tmp/pg07/generated-after.sql
diff /tmp/pg07/generated-before.sql /tmp/pg07/generated-after.sql && echo "GENERATED COLUMNS IDENTICAL"
```

Expected: `GENERATED COLUMNS IDENTICAL`. Task 1's repair must not alter SQLite DDL.

Then compare full schemas:

```bash
uv run --frozen python - <<'PY'
import re, sqlite3
def objects(path):
    rows = sqlite3.connect(path).execute(
        "select type, name, sql from sqlite_master "
        "where sql is not null and name not like 'sqlite_%'"
    )
    return {(t, n): " ".join(s.split()) for t, n, s in rows}
before = objects("/tmp/pg07/at0036/db.sqlite3")
after = objects("/tmp/pg07/after/db.sqlite3")
print("only in history:", sorted(set(before) - set(after)))
print("only in baseline:", sorted(set(after) - set(before)))
def columns(sql):
    return sorted(re.findall(r'"(\w+)"\s+[a-z]', sql))
for key in sorted(set(before) & set(after)):
    if columns(before[key]) != columns(after[key]):
        print("COLUMN SET DIFFERS:", key)
PY
```

Expected: both "only in" lists empty and no `COLUMN SET DIFFERS` line. Six tables will differ in column *order* — that is accepted and documented in the spec; the column *sets* must match exactly.

Save this output for the pull request.

- [ ] **Step 8: Prove the baseline is a no-op on an existing 0036 database**

```bash
DATA_DIR=/tmp/pg07/at0036 make migrate
sqlite3 /tmp/pg07/at0036/db.sqlite3 "select count(*) from django_migrations where app='games'"
```

Expected: `migrate` reports no schema work for `games` and exits 0. This is the direct evidence that the maintainer's production database needs no operator action. Record the exact output in the pull request.

- [ ] **Step 9: Run the full non-browser suite against the baseline**

Run: `make check-fast`
Expected: PASS. The test database is built from the baseline, so every test now exercises it.

- [ ] **Step 10: Commit**

```bash
git add games/models.py games/migrations/
git commit -m "refactor: replace migration history with a PostgreSQL baseline"
```

---

### Task 3: Guard the removed defect classes

**Files:**
- Create: `tests/test_migration_portability.py`

**Interfaces:**
- Consumes: `django.db.migrations.loader.MigrationLoader` to read the `games` migration set, and `django.db.models.fields.generated.GeneratedField`.
- Produces: no importable API; a test module only.

- [ ] **Step 1: Write the guard**

Create `tests/test_migration_portability.py`:

```python
"""Reject the SQLite-only constructs PG-07 removed from the migration set.

PostgreSQL verification is a manual, one-shot container run until PG-13
supplies a harness, so these three defect classes — each of which aborted a
fresh PostgreSQL build — are held out statically in the meantime.
"""

import pytest
from django.db.migrations.loader import MigrationLoader
from django.db.models.expressions import RawSQL
from django.db.models.fields.generated import GeneratedField
from django.db.migrations.operations.special import RunSQL

# Deliberately excludes date(/datetime(: those collide with datetime.date(...)
# and datetime.datetime(...) field defaults, which are ordinary Python.
SQLITE_ONLY_FUNCTIONS = ("julianday(", "strftime(", "unixepoch(")


def games_migrations():
    loader = MigrationLoader(connection=None, ignore_no_migrations=True)
    return [
        (name, migration)
        for (app_label, name), migration in loader.disk_migrations.items()
        if app_label == "games"
    ]


def generated_fields(migration):
    for operation in migration.operations:
        for attribute in ("field", "fields"):
            value = getattr(operation, attribute, None)
            entries = value if isinstance(value, list) else [(None, value)]
            for _, field in entries:
                if isinstance(field, GeneratedField):
                    yield operation, field


def test_no_raw_sql_in_migrations():
    offenders = [
        name
        for name, migration in games_migrations()
        for operation in migration.operations
        if isinstance(operation, RunSQL)
    ]
    assert offenders == [], f"RunSQL is not portable; found in {offenders}"


def test_no_raw_sql_expressions_in_generated_columns():
    offenders = [
        name
        for name, migration in games_migrations()
        for _, field in generated_fields(migration)
        if any(
            isinstance(node, RawSQL)
            for node in field.expression.flatten()
        )
    ]
    assert offenders == [], f"RawSQL in a generated column; found in {offenders}"


def test_no_generated_column_references_another_generated_column():
    generated_names = {"duration_calculated", "duration_total", "price_per_game", "days_to_finish"}
    offenders = []
    for name, migration in games_migrations():
        for operation, field in generated_fields(migration):
            # AddField/AlterField.name is the field; CreateModel.name is the
            # model, which simply widens the forbidden set for that operation.
            own = getattr(operation, "name", None)
            referenced = {
                node.name
                for node in field.expression.flatten()
                if hasattr(node, "name") and isinstance(getattr(node, "name", None), str)
            }
            if referenced & (generated_names - {own}):
                offenders.append((name, own, sorted(referenced & generated_names)))
    assert offenders == [], (
        f"PostgreSQL forbids a generated column referencing another; found {offenders}"
    )


@pytest.mark.parametrize("function", SQLITE_ONLY_FUNCTIONS)
def test_no_sqlite_only_function_names_in_migration_source(function):
    import pathlib

    offenders = [
        path.name
        for path in pathlib.Path("games/migrations").glob("0*.py")
        if function in path.read_text()
    ]
    assert offenders == [], f"{function} is SQLite-only; found in {offenders}"
```

- [ ] **Step 2: Verify the guard catches the defects it exists for**

Temporarily restore the retired history into the working tree. Do not use `git stash` — it would park the new test file rather than the migrations, and the run would fail on a missing file instead of on the defects.

```bash
BASELINE=$(git rev-parse HEAD)
git checkout HEAD~1 -- games/migrations/
make test-fast ARGS="tests/test_migration_portability.py -v"
```

`HEAD` is Task 2's commit, so `HEAD~1` is the pre-baseline tree. Checking out the path restores the 36 originals and overwrites the baseline `0001_initial.py` with the historical one.

Expected: four failures —
- `test_no_raw_sql_in_migrations` reports `0016_add_needs_price_update`
- `test_no_raw_sql_expressions_in_generated_columns` reports `0008_game_original_year_released_gamestatuschange_and_more`
- `test_no_generated_column_references_another_generated_column` reports `0014_session_duration_total`
- `test_no_sqlite_only_function_names_in_migration_source[julianday(]` reports `0008_game_original_year_released_gamestatuschange_and_more`

This step is the whole point of the guard — if it passes against the old history, it is not testing anything. Then restore the baseline:

```bash
rm games/migrations/0*.py
git checkout $BASELINE -- games/migrations/
git status --short
```

Expected: `git status --short` shows only the untracked test file. `rm` is required because the 36 originals do not exist in `$BASELINE`, so checking that path out will not remove them.

- [ ] **Step 3: Verify the guard passes against the baseline**

Run: `make test-fast ARGS="tests/test_migration_portability.py -v"`
Expected: PASS, all cases.

- [ ] **Step 4: Commit**

```bash
git add tests/test_migration_portability.py
git commit -m "test: reject SQLite-only constructs in migrations"
```

---

### Task 4: Verify a fresh PostgreSQL 17 build

**Files:**
- No repository files. Verification artifacts live in `/tmp/pg07/` and are pasted into the pull request.

**Interfaces:**
- Consumes: the committed baseline from Task 2.
- Produces: pull-request evidence only.

This task deliberately runs outside `make`. The project has no PostgreSQL driver and gains none here; PG-13 owns turning this into a repeatable target.

- [ ] **Step 1: Start PostgreSQL 17 matching PG-05's locale contract**

```bash
podman run -d --rm --name tt-pg07 \
  -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=timetracker \
  -e POSTGRES_INITDB_ARGS="--locale-provider=builtin --builtin-locale=C.UTF-8 --encoding=UTF8" \
  -p 55432:5432 docker.io/library/postgres:17
```

Then wait for readiness: `podman exec tt-pg07 pg_isready -U postgres`
Expected: `accepting connections`.

The locale flags are not cosmetic — PG-05 made the `builtin` provider with builtin locale `C.UTF-8` part of the deployment contract, so verification must build under it.

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

It lives outside the repository on purpose: `timetracker/settings.py` still hardcodes SQLite, and changing that is PG-11's outcome.

- [ ] **Step 3: Build the database**

```bash
PYTHONPATH=/tmp/pg07 DJANGO_SETTINGS_MODULE=pg_settings \
  uv run --frozen --with "psycopg[binary]" python manage.py migrate
```

Expected: every app applies, ending with `games.0001_initial... OK` and `sessions.0001_initial... OK`, then the ExchangeRate fixture loads. Any `ProgrammingError` here is a real portability defect, not an environment problem.

- [ ] **Step 4: Prove the generated columns compute, not merely parse**

```bash
PYTHONPATH=/tmp/pg07 DJANGO_SETTINGS_MODULE=pg_settings \
  uv run --frozen --with "psycopg[binary]" python manage.py shell -c "
import datetime as dt
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
days_to_finish 10
days_to_finish 1
days_to_finish 0
price_per_game 10.0 None
playtime 3:45:00
```

`days_to_finish 1` is the same-day rule from PG-03. `price_per_game None` is the `NULLIF` guard from PG-02 — a Purchase with no linked games must yield NULL, not a division error. `playtime 3:45:00` proves the Session signal aggregates the generated totals.

- [ ] **Step 5: Tear down**

```bash
podman rm -f tt-pg07
```

- [ ] **Step 6: Record the evidence**

Paste into the pull request body: the Step 3 migrate tail, the Step 4 output, the Step 7 schema comparison from Task 2, and the Step 8 no-op output from Task 2. No commit — the spec chose one-shot evidence over a permanent harness.

---

### Task 5: Gate and hand off

**Files:**
- No repository files beyond what earlier tasks committed.

- [ ] **Step 1: Run the full gate**

Run: `make check`
Expected: PASS, including `e2e/`. Do not substitute `check-fast`; only the full gate catches browser-test breakage.

Ensure `make dev` is not running — its watchers rewrite served assets and cause mass phantom e2e failures.

- [ ] **Step 2: File the follow-up issues**

Three, each referencing #609:

1. *Remove the migration baseline's `replaces` list after the PostgreSQL cutover* — the list exists only so SQLite installations recognize the baseline as applied; charter step 19 schedules its removal.
2. *SQLite-to-PostgreSQL transfer must copy by column name, not ordinal* — the baseline reorders columns in `games_game`, `games_platform`, `games_playevent`, `games_purchase`, `games_session`, and `games_userpreferences`. Positional copying would silently transpose values. Belongs to the SQLite transfer and cutover group.
3. *Re-verify PG-01 through PG-06 against a real PostgreSQL server under PG-13* — their outcomes were reasoned, never executed; the first execution found a defect in PG-01's.

- [ ] **Step 3: Open the pull request**

Body includes the evidence from Task 4 Step 6, a statement that the interval repair is PG-01 rework and why it lands here, and a link to the Plan adjustments entry in the epic.

---

## Gotchas

- **`make migrate` runs `makemigrations` first.** On a clean tree it prints `No changes detected` and is harmless, but after Task 1's model edit and before Task 2's regeneration it would generate a stray `0037`. Do Task 1 Step 1 and Step 2 *before* editing the model.
- **`DATA_DIR` controls the database location** and is read by `timetracker/config.py`, so throwaway builds need no settings change.
- **Nothing outside `games/migrations/` references migration module names.** Only inter-migration `dependencies` and prose in `docs/` mention them, so deletion breaks no import.
- **The nine data operations are not carried over deliberately.** `initialize_num_purchases`, `set_finished_status`, `copy_year_released`, `set_abandoned_status`, `create_game_status_changes`, `calculate_game_playtime`, the `needs_price_update` UPDATE, `backfill_related_game`, and `remove_sentinels` are all backfills over pre-existing rows and no-ops on the empty database a baseline builds. If a reviewer asks whether seed data was lost, this is the answer.
- **`duration_manual` defaults to `timedelta(0)`**, which is why `duration_total` does not go NULL for a Session with no manual duration. Do not "fix" that with a second `Coalesce`.
