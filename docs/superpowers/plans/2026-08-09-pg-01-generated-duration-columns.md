# PG-01 Generated Duration Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Session.duration_total` a PostgreSQL-valid persisted generated column without changing the calculated duration values exposed by the application.

**Architecture:** Retain `Session.duration_calculated` as the existing generated elapsed-duration column. Change only `duration_total` so its persisted `GeneratedField` repeats the timestamp subtraction and `Coalesce` directly, then adds `duration_manual`; it must never reference `duration_calculated`. A normal `AlterField` migration updates the database schema and automatically recalculates stored generated values from existing source data.

**Tech Stack:** Python 3.14, Django 6 `GeneratedField`, Django migrations, pytest-django, GNU Make.

## Global Constraints

- Scope is limited to PG-01: do not add PostgreSQL runtime configuration, a migration baseline, a SQLite transfer, or changes to filters, presets, APIs, statistics, ownership, or user isolation.
- Preserve the persisted `duration_calculated` and `duration_total` column names and `DurationField` output types.
- `duration_total` must be `Coalesce(F("timestamp_end") - F("timestamp_start"), 0) + F("duration_manual")`; it must not reference `duration_calculated`.
- Use `make` targets for all project commands. The final verification gate is `make check`.

---

## File structure

- Create `tests/test_generated_duration_columns.py`: database-backed semantic and model-schema regression coverage for the two generated Session durations.
- Modify `games/models.py`: replace only the `Session.duration_total` generated expression.
- Create `games/migrations/0034_alter_session_duration_total.py`: Django-generated `AlterField` migration for the changed persisted expression.

### Task 1: Define and implement the PostgreSQL-safe duration expression

**Files:**
- Create: `tests/test_generated_duration_columns.py`
- Modify: `games/models.py:322-326`
- Create: `games/migrations/0034_alter_session_duration_total.py`

**Interfaces:**
- Consumes: `games.models.Session`, whose persisted generated fields are refreshed with `Session.refresh_from_db()` after inserts.
- Produces: `Session.duration_total: timedelta`, calculated as elapsed timestamp duration (or zero for a missing end) plus `duration_manual`; `Session.duration_calculated: timedelta` remains elapsed timestamp duration (or zero).

- [ ] **Step 1: Write the failing semantic and schema tests**

Create `tests/test_generated_duration_columns.py` with these tests. The parametrized rows cover the complete behavior preserved by the change: ended timed, running/manual-only, and ended-with-manual-addition.

```python
from datetime import UTC, datetime, timedelta

import pytest
from django.db import models
from django.db.models import F

from games.models import Game, Session

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("timestamp_end", "duration_manual", "expected_calculated", "expected_total"),
    [
        (datetime(2026, 1, 1, 12, tzinfo=UTC), timedelta(0), timedelta(hours=2), timedelta(hours=2)),
        (None, timedelta(hours=3), timedelta(0), timedelta(hours=3)),
        (datetime(2026, 1, 1, 12, tzinfo=UTC), timedelta(minutes=30), timedelta(hours=2), timedelta(hours=2, minutes=30)),
    ],
)
def test_generated_duration_values(
    timestamp_end, duration_manual, expected_calculated, expected_total
):
    session = Session.objects.create(
        game=Game.objects.create(name="Hades"),
        timestamp_start=datetime(2026, 1, 1, 10, tzinfo=UTC),
        timestamp_end=timestamp_end,
        duration_manual=duration_manual,
    )
    session.refresh_from_db()
    assert session.duration_calculated == expected_calculated
    assert session.duration_total == expected_total


def test_duration_total_uses_only_source_columns():
    field = Session._meta.get_field("duration_total")
    references = {
        expression.name
        for expression in field.expression.flatten()
        if isinstance(expression, F)
    }
    assert field.db_persist is True
    assert isinstance(field.output_field, models.DurationField)
    assert references == {"timestamp_end", "timestamp_start", "duration_manual"}
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `make test ARGS="tests/test_generated_duration_columns.py -x"`

Expected: the schema test fails because `references` contains `"duration_calculated"` instead of the timestamp source fields. The value cases may pass on SQLite; the schema assertion is the regression guard for PostgreSQL compatibility.

- [ ] **Step 3: Inline the elapsed expression in the model**

In `games/models.py`, replace the existing `duration_total` expression with the following exact expression. Do not alter `duration_calculated`.

```python
duration_total = GeneratedField(
    expression=Coalesce(F("timestamp_end") - F("timestamp_start"), 0)
    + F("duration_manual"),
    output_field=models.DurationField(),
    db_persist=True,
    editable=False,
)
```

- [ ] **Step 4: Generate and inspect the migration**

Run: `make makemigrations`

Expected: Django creates `games/migrations/0034_alter_session_duration_total.py` containing one `AlterField` for `Session.duration_total`, with the same inline `Coalesce(timestamp_end - timestamp_start, 0) + duration_manual` expression. Confirm it depends on `("games", "0033_session_timestamp_end_timezone_and_more")` and contains no data operation.

- [ ] **Step 5: Run focused tests to verify behavior and schema pass**

Run: `make test ARGS="tests/test_generated_duration_columns.py -x"`

Expected: PASS. The three persisted value cases retain their expected durations and the schema test sees exactly `timestamp_start`, `timestamp_end`, and `duration_manual` references.

- [ ] **Step 6: Run the full project gate**

Run: `make check`

Expected: PASS, including lint, formatting, mypy, TypeScript checks/tests, and the complete pytest/e2e suite.

- [ ] **Step 7: Commit the implementation**

```bash
git add games/models.py games/migrations/0034_alter_session_duration_total.py tests/test_generated_duration_columns.py
git commit -m "fix: make generated durations PostgreSQL-compatible"
```
