# PG-01 through PG-06 PostgreSQL Re-verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the six PG-01 through PG-06 compatibility outcomes against the real PostgreSQL 17 pytest topology, and record the result in #599.

**Architecture:** Add one dedicated `tests/test_postgresql_reverification.py` module. It asserts the live backend before exercising the current Django models, sorting path, collation validator, and audited persistence/query surfaces. Existing unit tests remain their owning-contract coverage; this module is the real-server regression record.

**Tech Stack:** Python 3.14, Django 6, pytest 9, pytest-django 4.12, pytest-xdist 3.8, PostgreSQL 17.

## Global Constraints

- Every database-touching new test must prove `connection.vendor == "postgresql"`; a SQLite result is not #811 evidence.
- Keep Makefile-selected `PYTEST_WORKERS`; do not force `PYTEST_WORKERS=0` except for explicit debugging.
- Use Django ORM and the project `DATABASE_URL`; add no custom connection, launcher, service, migration, or Compose configuration.
- Preserve the existing PG-01 through PG-06 unit tests; this issue adds execution evidence rather than moving their ownership.
- An expression-level incompatibility found by a new regression may be repaired here. Stop and file a routed issue before any baseline, provisioning, topology, deployment, data-transfer, API, or ownership change.
- CI remains serial and unchanged; #616 owns its PostgreSQL CI migration.

---

## File structure

- Create `tests/test_postgresql_reverification.py`: the single PostgreSQL-only execution matrix for all six prior outcomes.
- Create `docs/superpowers/plans/2026-08-10-pg-01-06-postgresql-reverification.md`: this implementation record.
- Modify GitHub issue #599: append a dated Plan adjustments entry with the verified results and any explicitly routed defect.

### Task 1: Establish the real-PostgreSQL matrix and re-run generated columns

**Files:**

- Create: `tests/test_postgresql_reverification.py`
- Test: `tests/test_postgresql_reverification.py`

**Interfaces:**

- Consumes: `games.models.Game`, `Purchase`, `PlayEvent`, and `Session` public ORM fields; Django's `django.db.connection`.
- Produces: `assert_postgresql()` for every later test in this module and PostgreSQL regression tests for PG-01, PG-02, and PG-03.

- [ ] **Step 1: Confirm the dedicated evidence module does not exist yet**

  Run:

  ```bash
  make test ARGS="tests/test_postgresql_reverification.py -q"
  ```

  Expected: collection fails because the dedicated #811 module does not yet
  exist.

- [ ] **Step 2: Write the PostgreSQL guard and generated-duration test**

  Create the module with these imports and helper:

  ```python
  from datetime import UTC, date, datetime, timedelta

  import pytest
  from django.db import connection

  from games.models import Game, PlayEvent, Purchase, Session

  pytestmark = pytest.mark.django_db


  def assert_postgresql() -> None:
      assert connection.vendor == "postgresql"
  ```

  Add a parametrized duration test whose rows are `(timestamp_end,
  duration_manual, expected_calculated, expected_total)` and exactly cover:

  ```python
  (
      datetime(2026, 1, 1, 12, tzinfo=UTC),
      timedelta(0),
      timedelta(hours=2),
      timedelta(hours=2),
  )
  (None, timedelta(hours=3), timedelta(0), timedelta(hours=3))
  (
      datetime(2026, 1, 1, 12, tzinfo=UTC),
      timedelta(minutes=30),
      timedelta(hours=2),
      timedelta(hours=2, minutes=30),
  )
  ```

  Each case calls `assert_postgresql()`, creates a `Game` and `Session` with a
  `2026-01-01 10:00 UTC` start, calls `refresh_from_db()`, and asserts both
  generated duration fields equal the expected values.

- [ ] **Step 3: Add PostgreSQL purchase-price and days-to-finish cases**

  Add `test_postgresql_generated_purchase_price()`:

  ```python
  purchase = Purchase.objects.create(
      date_purchased=date(2026, 8, 10), price=12, price_currency="USD"
  )
  purchase.refresh_from_db()
  assert purchase.num_purchases == 0
  assert purchase.price_per_game is None

  purchase.games.set(
      [
          Game.objects.create(name="Celeste"),
          Game.objects.create(name="Hades"),
      ]
  )
  purchase.refresh_from_db()
  assert (purchase.num_purchases, purchase.price_per_game) == (2, 6)
  ```

  In the same test, create a second `Purchase` with `price=12`,
  `converted_price=15`, both currency fields `"USD"`, and two games; refresh
  it and assert `price_per_game == 7.5`.

  Add a parametrized `test_postgresql_generated_days_to_finish(started, ended,
  expected_days)` with these exact cases:

  ```python
  (None, None, 0)
  (None, date(2026, 1, 4), 0)
  (date(2026, 1, 1), None, 0)
  (date(2026, 1, 1), date(2026, 1, 1), 1)
  (date(2026, 1, 1), date(2026, 1, 4), 3)
  (date(2026, 1, 4), date(2026, 1, 1), -3)
  ```

  Each case calls `assert_postgresql()`, creates a uniquely named `Game` and
  `PlayEvent`, refreshes it, and asserts `days_to_finish == expected_days`.

- [ ] **Step 4: Run the generated-column PostgreSQL evidence**

  Run:

  ```bash
  make test ARGS="tests/test_postgresql_reverification.py -q"
  ```

  Expected: all PG-01 through PG-03 cases pass against PostgreSQL. If any
  assertion fails, keep the failing case, identify whether the repair is only
  a model/query expression, and stop for a routed issue before changing a
  migration or any out-of-scope surface.

- [ ] **Step 5: Commit the generated-column evidence**

  ```bash
  git add tests/test_postgresql_reverification.py
  git commit -m "test: reverify PostgreSQL generated columns"
  ```

### Task 2: Re-run ordering and the live collation contract

**Files:**

- Modify: `tests/test_postgresql_reverification.py`
- Test: `tests/test_postgresql_reverification.py`

**Interfaces:**

- Consumes: `games.filters.FindFilter`, `games.sorting.apply_sort`,
  `GAME_SORTS`, `GAME_DEFAULT_SORT`, and
  `timetracker.postgres_contract.validate_postgres_collation_contract`.
- Produces: PostgreSQL regression tests for PG-04 and PG-05.

- [ ] **Step 1: Write the nullable direct/aggregate ordering test**

  Add imports:

  ```python
  from games.filters import FindFilter
  from games.models import Platform
  from games.sorting import GAME_DEFAULT_SORT, GAME_SORTS, apply_sort
  ```

  Add `test_postgresql_nullable_sorting_is_null_last_and_tie_stable()` that:

  1. Calls `assert_postgresql()` and creates one `Platform` plus games named
     `Unknown`, `Early`, `Late`, `First`, and `Second` in that creation order.
  2. Gives `Early` and `Late` `year_released` values 1990 and 2000,
     respectively; leaves `Unknown` NULL.
  3. Calls `apply_sort(Game.objects.all(), FindFilter(sort="year"),
     GAME_SORTS, GAME_DEFAULT_SORT)` and asserts `[early, late, unknown]`.
  4. Repeats with `sort="-year"` and asserts `[late, early, unknown]`.
  5. Calls `apply_sort(Game.objects.filter(pk__in=[second.pk, first.pk]),
     FindFilter(sort="status"), GAME_SORTS, GAME_DEFAULT_SORT)` and asserts
     `[first, second]` to prove primary-key tie-breaking.
  6. Adds same-day and next-day `PlayEvent` rows for `Early` and `Late`, then
     asserts the `finished` sort is `[early, late, unknown, first, second]`
     ascending and `[late, early, unknown, first, second]` descending. This
     re-executes the nullable aggregate path, while `first` and `second` share
     NULL and expose its deterministic PK order.

- [ ] **Step 2: Write the live collation-contract test**

  Add:

  ```python
  from timetracker.postgres_contract import validate_postgres_collation_contract
  ```

  Add `test_postgresql_connection_satisfies_collation_contract()`:

  ```python
  assert_postgresql()
  connection.ensure_connection()
  contract = validate_postgres_collation_contract(connection.connection)
  assert contract.server_version_num // 10_000 == 17
  assert contract.encoding == "UTF8"
  assert contract.locale_provider == "b"
  assert contract.locale == "C.UTF-8"
  ```

  Do not weaken the encoding, provider, or locale assertions; PostgreSQL patch
  releases may change only `server_version_num`'s final digits.

- [ ] **Step 3: Run the PG-04 and PG-05 PostgreSQL evidence**

  Run:

  ```bash
  make test ARGS="tests/test_postgresql_reverification.py -q"
  ```

  Expected: direct and aggregate values are NULL-last in both directions,
  equal values are PK-stable, and the test database matches the PostgreSQL 17
  `UTF8`/`builtin`/`C.UTF-8` contract.

- [ ] **Step 4: Commit ordering and contract evidence**

  ```bash
  git add tests/test_postgresql_reverification.py
  git commit -m "test: reverify PostgreSQL ordering and collation"
  ```

### Task 3: Re-run the PG-06 audited runtime surfaces

**Files:**

- Modify: `tests/test_postgresql_reverification.py`
- Test: `tests/test_postgresql_reverification.py`

**Interfaces:**

- Consumes: `Session.objects.only_manual()`, `Session.objects.without_manual()`,
  `FilterPreset`, Django's user model, `IntegrityError`, and `transaction.atomic`.
- Produces: PostgreSQL regression tests for the PG-06 timestamp/duration, JSON,
  declarative-constraint, and catalog-validator audit findings.

- [ ] **Step 1: Write the timestamp and interval-query test**

  Add `test_postgresql_interval_querysets_partition_sessions()` that calls
  `assert_postgresql()`, creates one game, then creates:

  ```python
  manual_only = Session.objects.create(
      game=game,
      timestamp_start=datetime(2026, 1, 1, 12, tzinfo=UTC),
      timestamp_end=datetime(2026, 1, 1, 12, tzinfo=UTC),
      duration_manual=timedelta(minutes=30),
  )
  elapsed = Session.objects.create(
      game=game,
      timestamp_start=datetime(2026, 1, 2, 12, tzinfo=UTC),
      timestamp_end=datetime(2026, 1, 2, 13, tzinfo=UTC),
  )
  ```

  Assert `list(Session.objects.only_manual()) == [manual_only]` and
  `list(Session.objects.without_manual()) == [elapsed]`. This executes the
  PostgreSQL interval equality repair rather than inspecting generated SQL.

- [ ] **Step 2: Write JSON persistence and declarative-constraint tests**

  Add imports:

  ```python
  from django.contrib.auth import get_user_model
  from django.db import IntegrityError, transaction

  from games.models import FilterPreset
  ```

  Add `test_postgresql_json_persistence_and_preset_constraint()` that calls
  `assert_postgresql()`, creates a user named `postgres-reverify`, and creates:

  ```python
  preset = FilterPreset.objects.create(
      user=user,
      name="PostgreSQL",
      mode="games",
      find_filter={"sort": "-year"},
      object_filter={"year": {"modifier": "EQUALS", "value": 2026}},
      ui_options={"per_page": 50},
  )
  ```

  Refresh `preset` and assert each JSON field equals its original dictionary.
  Then, inside `with pytest.raises(IntegrityError), transaction.atomic():`,
  create another preset for the same user, mode, and name. This proves the
  runtime JSON fields round-trip and the declared unique constraint is enforced
  by PostgreSQL.

- [ ] **Step 3: Run the complete dedicated matrix and its original focused suites**

  Run:

  ```bash
  make test ARGS="tests/test_postgresql_reverification.py -q"
  make test ARGS="tests/test_generated_duration_columns.py tests/test_generated_purchase_price_columns.py tests/test_generated_days_to_finish.py tests/test_sorting.py tests/test_postgres_contract.py tests/test_session_querysets.py -q"
  ```

  Expected: both commands pass using the Makefile's normal worker count. If a
  new PostgreSQL test finds an expression-level defect, add its minimal repair
  and re-run both commands; otherwise make no production edit.

- [ ] **Step 4: Commit the PG-06 evidence**

  ```bash
  git add tests/test_postgresql_reverification.py
  git commit -m "test: reverify PostgreSQL audited surfaces"
  ```

### Task 4: Record the verified findings and run the complete gate

**Files:**

- Modify: GitHub issue #599 body, `Plan adjustments` section
- Test: complete repository quality gate

**Interfaces:**

- Consumes: passing output from Tasks 1–3 and the current #599 issue body.
- Produces: a dated, reviewable #811 record and final repository verification.

- [ ] **Step 1: Add the clean-result finding to #599**

  After all Task 3 commands pass without a defect, append this exact entry to
  the existing `## Plan adjustments` section of GitHub issue #599:

  ```markdown
  ### 2026-08-10 — PG-01 through PG-06 re-verified on PostgreSQL (#811)

  With PG-13's pytest-xdist topology, #811 executed the prior compatibility
  outcomes against PostgreSQL 17 rather than relying on SQLite/static evidence.
  Generated session durations, generated purchase prices (including `NULLIF`),
  generated days-to-finish values, NULL-last ordering and PK tie-breaking, the
  `UTF8`/`builtin`/`C.UTF-8` collation contract, and the audited timestamp,
  interval, JSON, unique-constraint, and catalog-validator surfaces all passed.
  No repair or follow-up issue was required.
  ```

  If a defect was repaired or routed, replace only the final sentence with a
  factual sentence naming the repair commit or newly filed issue; retain the
  list of confirmed outcomes.

- [ ] **Step 2: Run the full quality gate**

  Run:

  ```bash
  make check
  ```

  Expected: PASS with the Makefile-selected worker count. On Windows Codex
  desktop, run through the managed hidden-process procedure and wait for its
  final log and exit status.

- [ ] **Step 3: Inspect the final change set**

  Run:

  ```bash
  git diff --check main...HEAD
  git status --short
  git log --oneline main..HEAD
  ```

  Expected: only the new PostgreSQL re-verification module, this approved spec
  and plan, and any narrowly justified expression-level repair are present;
  no CI, topology, provisioning, migration-baseline, or deployment changes.

- [ ] **Step 4: Commit the plan and verification evidence**

  ```bash
  git add docs/superpowers/plans/2026-08-10-pg-01-06-postgresql-reverification.md
  git commit -m "docs: plan PostgreSQL compatibility reverification"
  ```
