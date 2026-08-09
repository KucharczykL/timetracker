# PG-06: PostgreSQL Compatibility Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Repair PostgreSQL-incompatible interval filtering and record the audit boundary for timestamps, durations, JSON, constraints, raw SQL, and direct cursors.

**Architecture:** Preserve the existing SessionQuerySet public methods and replace their case-insensitive interval lookup with direct timedelta equality. The approved issue specification is the committed audit record; tests exercise QuerySet results, while a final static review confirms that migration-only SQLite RawSQL remains assigned to PG-07.

**Tech Stack:** Python 3.14, Django 6 ORM, pytest, SQLite current runtime, Make.

## Global Constraints

- Related issue: https://github.com/KucharczykL/timetracker/issues/608.
- Use timedelta(0), never __iexact, for equality on the DurationField-backed duration_calculated expression.
- Preserve the names and behavior of SessionQuerySet.only_manual() and without_manual().
- Do not modify migrations, generated expressions, database configuration, JSON storage, constraints, raw-SQL migration 0008, filters, presets, statistics, APIs, or user isolation.
- PG-07 owns replacement of migration 0008 and the fresh PostgreSQL migration baseline.
- Completion requires make check.

---

## File structure

- Modify: games/models.py:270-285 — make custom SessionQuerySet duration comparisons type-correct.
- Create: tests/test_session_querysets.py — prove calculated-zero and nonzero Sessions partition through both QuerySet methods.
- Inspect: docs/superpowers/specs/2026-08-09-pg-06-postgresql-compatibility-audit-design.md — the approved permanent audit record.
- Inspect only: games/migrations/0008_game_original_year_released_gamestatuschange_and_more.py, games/expressions.py, games/filters.py, games/views/stats_data.py, timetracker/postgres_contract.py — confirm audit ownership and avoid scope expansion.

### Task 1: Define interval partitioning with failing QuerySet tests

**Files:**

- Create: tests/test_session_querysets.py
- Modify: games/models.py:281-285

**Interfaces:**

- Consumes: Session.objects.only_manual() and Session.objects.without_manual().
- Produces: QuerySets where only_manual() contains exactly Sessions whose generated duration_calculated equals timedelta(0), while without_manual() contains every Session whose generated duration_calculated differs from timedelta(0).

- [ ] **Step 1: Write the failing partition test**

Create the test file with this code. The manual-only row has equal endpoints, so duration_calculated is zero but duration_manual is nonzero; the elapsed row proves a normal interval remains outside only_manual().

~~~python
from datetime import UTC, datetime, timedelta

import pytest

from games.models import Game, Platform, Session

pytestmark = pytest.mark.django_db


def test_session_duration_querysets_partition_calculated_zero_rows():
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Hades", platform=platform)
    manual_only = Session.objects.create(
        game=game,
        timestamp_start=datetime(2024, 1, 1, 12, tzinfo=UTC),
        timestamp_end=datetime(2024, 1, 1, 12, tzinfo=UTC),
        duration_manual=timedelta(minutes=30),
    )
    elapsed = Session.objects.create(
        game=game,
        timestamp_start=datetime(2024, 1, 2, 12, tzinfo=UTC),
        timestamp_end=datetime(2024, 1, 2, 13, tzinfo=UTC),
    )

    assert list(Session.objects.only_manual()) == [manual_only]
    assert list(Session.objects.without_manual()) == [elapsed]
~~~

- [ ] **Step 2: Run the test before implementation**

Run:

~~~powershell
make test ARGS="tests/test_session_querysets.py::test_session_duration_querysets_partition_calculated_zero_rows -v"
~~~

Expected: FAIL on the current duration_calculated__iexact lookup, which attempts a case-insensitive operation on a duration value. If SQLite accepts the lookup, inspect query compilation and retain this test as the PostgreSQL regression contract; do not alter the expected partition.

### Task 2: Replace the invalid interval lookup

**Files:**

- Modify: games/models.py:281-285
- Test: tests/test_session_querysets.py

**Interfaces:**

- Consumes: Task 1's regression test and the existing duration_calculated GeneratedField.
- Produces: unchanged SessionQuerySet method names with ordinary Django interval equality.

- [ ] **Step 1: Replace both case-insensitive lookups**

Import already exists at games/models.py:2. Replace the two method bodies exactly:

~~~python
    def without_manual(self):
        return self.exclude(duration_calculated=timedelta(0))

    def only_manual(self):
        return self.filter(duration_calculated=timedelta(0))
~~~

Do not compare the generated field to integer 0, cast it to text, or modify duration_calculated itself.

- [ ] **Step 2: Run focused QuerySet and generated-duration coverage**

Run:

~~~powershell
make test ARGS="tests/test_session_querysets.py tests/test_generated_duration_columns.py -v"
~~~

Expected: PASS. The new test proves result partitioning; generated-column tests prove the query-layer repair did not change the PG-01 expression contract.

- [ ] **Step 3: Commit the code and test**

~~~powershell
git add games/models.py tests/test_session_querysets.py
git commit -m "fix: compare session durations as intervals"
~~~

Expected: the commit contains only the type-correct custom QuerySet comparison and its regression test.

### Task 3: Verify audit scope and repository gate

**Files:**

- Inspect: docs/superpowers/specs/2026-08-09-pg-06-postgresql-compatibility-audit-design.md
- Inspect: games/migrations/0008_game_original_year_released_gamestatuschange_and_more.py
- Inspect: games/models.py
- Inspect: tests/test_session_querysets.py

**Interfaces:**

- Consumes: Task 2 commit and the approved audit specification.
- Produces: an issue-ready branch with a precise runtime repair and a documented PG-07 baseline handoff.

- [ ] **Step 1: Confirm the static audit boundary**

Run:

~~~powershell
rg -n "RawSQL|\.raw\(|\.extra\(" games timetracker -g "*.py"
rg -n "cursor\(" timetracker games common -g "*.py"
~~~

Verify that migration 0008 is the only SQLite julianday RawSQL result; timetracker.postgres_contract is the intentional PG-05 cursor consumer; and the health-check cursor contains no backend-specific SQL. If any additional runtime RawSQL is found, stop and update the approved specification before modifying it.

- [ ] **Step 2: Review the change scope**

Run:

~~~powershell
git diff HEAD~1 -- games/models.py tests/test_session_querysets.py
git diff --check HEAD~1
rg -n "__iexact" games/models.py
~~~

Expected: direct timedelta equality appears in both methods; __iexact has no remaining duration usage; migrations, JSON fields, constraints, settings, and request handlers are unchanged.

- [ ] **Step 3: Run the repository gate**

Run:

~~~powershell
make check
~~~

Expected: exit code 0. This verifies current-runtime lint, formatting, typing, generated artifacts, TypeScript, unit, and E2E coverage. PostgreSQL fresh-baseline verification remains PG-07's gate.

- [ ] **Step 4: Confirm handoff metadata**

Run:

~~~powershell
git status --short
git log -1 --oneline
~~~

Expected: clean worktree and the Task 2 implementation commit at HEAD. The PR body must link https://github.com/KucharczykL/timetracker/issues/608, include Closes #608, and state that migration 0008 remains owned by PG-07.

## Spec coverage review

- Task 1 proves the behavior that the invalid case-insensitive interval lookup must preserve.
- Task 2 replaces the only runtime compatibility defect without changing a schema or data.
- Task 3 records and enforces the audit handoff for timestamps, generated durations, JSON, constraints, RawSQL, and cursors.
- No data reconciliation is necessary because this issue changes no persisted values.

