# PG-03 Days-to-Finish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `PlayEvent.days_to_finish` a PostgreSQL-safe persisted generated column while preserving its existing integer day-count semantics.

**Architecture:** Introduce a serializable `DatabaseDateDifference` expression. Its default compiler emits native typed date subtraction for PostgreSQL, while its SQLite compiler uses integer-cast `julianday` subtraction. Compose it with Django `Case` and `Coalesce` so same-day values remain one and missing dates remain zero, then replace the stored generated column using a remove-and-add migration.

**Tech Stack:** Python 3.14, Django 6 `GeneratedField`, Django migrations, pytest-django, GNU Make.

## Global Constraints

- Scope is limited to PG-03: do not add PostgreSQL runtime configuration, a migration baseline, a SQLite transfer, or changes to PlayEvent write paths, filters, presets, APIs, statistics, ownership, or user isolation.
- Preserve the persisted `days_to_finish` column name and its `IntegerField` output type.
- Preserve all values: missing endpoint → `0`; equal dates → `1`; distinct dates → the signed whole-day difference.
- The model expression must be typed Django expressions over `started` and `ended`; it must not use `RawSQL`, SQLite `date()`, or SQLite `julianday()` directly.
- Use `make` targets for every project command. The final verification gate is `make check`.

---

## File structure

- Create `tests/test_generated_days_to_finish.py`: database-backed semantic and model-schema regression coverage for `PlayEvent.days_to_finish`.
- Modify `games/expressions.py`: add the backend-aware, serializable `DatabaseDateDifference` expression.
- Modify `games/models.py`: replace only the `PlayEvent.days_to_finish` generated expression and imports.
- Create `games/migrations/0036_alter_playevent_days_to_finish.py`: remove-and-add migration for the changed stored expression.

### Task 1: Define and apply the portable days-to-finish expression

**Files:**
- Create: `tests/test_generated_days_to_finish.py`
- Modify: `games/expressions.py:1-22`
- Modify: `games/models.py:9-15,441-467`
- Create: `games/migrations/0036_alter_playevent_days_to_finish.py`

**Interfaces:**
- Consumes: `PlayEvent.started: date | None` and `PlayEvent.ended: date | None`.
- Produces: `DatabaseDateDifference(lhs, rhs)`, a serializable integer expression that compiles to `lhs - rhs` on PostgreSQL and `CAST(julianday(lhs) - julianday(rhs) AS integer)` on SQLite; `PlayEvent.days_to_finish: int` remains a stored generated value.

- [ ] **Step 1: Write the failing semantic and schema tests**

Create `tests/test_generated_days_to_finish.py`. Each expectation is hand-derived from calendar dates and exercises the persisted generated column after refresh. The schema test catches reintroduction of model-level SQLite raw SQL and confirms both source columns remain the only field dependencies.

```python
from datetime import date

import pytest
from django.db import connection, models
from django.db.models import F
from django.db.models.expressions import RawSQL

from games.models import Game, PlayEvent

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("started", "ended", "expected_days"),
    [
        (None, None, 0),
        (None, date(2026, 1, 4), 0),
        (date(2026, 1, 1), None, 0),
        (date(2026, 1, 1), date(2026, 1, 1), 1),
        (date(2026, 1, 1), date(2026, 1, 4), 3),
        (date(2026, 1, 4), date(2026, 1, 1), -3),
    ],
)
def test_generated_days_to_finish(started, ended, expected_days):
    event = PlayEvent.objects.create(
        game=Game.objects.create(name=f"Game {started}-{ended}"),
        started=started,
        ended=ended,
    )
    event.refresh_from_db()

    assert event.days_to_finish == expected_days


def test_days_to_finish_uses_typed_source_columns():
    field = PlayEvent._meta.get_field("days_to_finish")
    references = {
        expression.name
        for expression in field.expression.flatten()
        if isinstance(expression, F)
    }
    sql, _ = field.generated_sql(connection)

    assert field.db_persist is True
    assert isinstance(field.output_field, models.IntegerField)
    assert not isinstance(field.expression, RawSQL)
    assert references == {"started", "ended"}
    assert "JULIANDAY" in sql.upper()
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
make test ARGS="tests/test_generated_days_to_finish.py -x"
```

Expected: the value cases pass against the current SQLite-only expression, but `test_days_to_finish_uses_typed_source_columns` fails because `field.expression` is `RawSQL`.

- [ ] **Step 3: Add the portable date-difference expression and use it in the model**

Extend `games/expressions.py` with `DatabaseDateDifference`. Calling `Expression.resolve_expression()` directly is required so date subtraction is not transformed into Django's `TemporalSubtraction`/`DurationField` expression.

```python
class DatabaseDateDifference(CombinedExpression):
    def __init__(self, lhs, rhs):
        super().__init__(lhs, "-", rhs, output_field=models.IntegerField())

    def as_sqlite(self, compiler, connection):
        lhs_sql, lhs_params = compiler.compile(self.lhs)
        rhs_sql, rhs_params = compiler.compile(self.rhs)
        return (
            f"CAST(julianday({lhs_sql}) - julianday({rhs_sql}) AS integer)",
            [*lhs_params, *rhs_params],
        )

    def resolve_expression(
        self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False
    ):
        return Expression.resolve_expression(
            self, query, allow_joins, reuse, summarize, for_save
        )
```

In `games/models.py`, replace the `RawSQL` expression with this typed expression and add only the imports it needs:

```python
from django.db.models import Case, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce

from games.expressions import DatabaseDateDifference, DatabaseDurationSum

# ...

days_to_finish = GeneratedField(
    expression=Coalesce(
        Case(
            When(ended=F("started"), then=Value(1)),
            default=DatabaseDateDifference(F("ended"), F("started")),
            output_field=models.IntegerField(),
        ),
        Value(0),
    ),
    output_field=models.IntegerField(),
    db_persist=True,
    editable=False,
    blank=True,
)
```

Remove the now-unused `RawSQL` import. Do not modify PlayEvent consumers: filters, sorting, API schemas, and views keep using the same persisted field.

- [ ] **Step 4: Generate, rewrite, and inspect the generated-column migration**

Run:

```bash
make makemigrations
```

Expected: Django produces `games/migrations/0036_alter_playevent_days_to_finish.py` with an `AlterField`. Replace it with ordered remove-and-add operations:

```python
operations = [
    migrations.RemoveField(
        model_name="playevent",
        name="days_to_finish",
    ),
    migrations.AddField(
        model_name="playevent",
        name="days_to_finish",
        field=models.GeneratedField(
            db_persist=True,
            expression=django.db.models.functions.comparison.Coalesce(
                django.db.models.expressions.Case(
                    django.db.models.When(
                        ended=models.F("started"), then=models.Value(1)
                    ),
                    default=games.expressions.DatabaseDateDifference(
                        models.F("ended"), models.F("started")
                    ),
                    output_field=models.IntegerField(),
                ),
                models.Value(0),
            ),
            output_field=models.IntegerField(),
        ),
    ),
]
```

Confirm the migration depends on `("games", "0035_alter_purchase_price_per_game")`, imports `games.expressions` plus each serialized Django expression module, and contains no `RunPython`, `RunSQL`, or data-copy operation. The database recalculates each stored value from `started` and `ended`.

- [ ] **Step 5: Run focused tests after the model and migration change**

Run:

```bash
make test ARGS="tests/test_generated_days_to_finish.py -x"
```

Expected: PASS. The six cases yield `0`, `0`, `0`, `1`, `3`, and `-3`; the field remains a persisted integer generated column over `started` and `ended`, and its SQLite-generated SQL contains `JULIANDAY` only through the helper's compiler branch.

- [ ] **Step 6: Run the full project verification gate**

Run:

```bash
make check
```

Expected: PASS, including formatting, linting, mypy, TypeScript checks/tests, and the complete Python/e2e suite.

- [ ] **Step 7: Commit the implementation**

```bash
git add games/expressions.py games/models.py games/migrations/0036_alter_playevent_days_to_finish.py tests/test_generated_days_to_finish.py
git commit -m "fix: make days-to-finish PostgreSQL-compatible"
```

## Plan self-review

- Spec coverage: Task 1 covers portable compilation, missing-date, same-day, multi-day, and signed reverse-date values; source-field and non-raw-expression constraints; remove-and-add migration; automatic reversibility; focused verification; and the final `make check` gate.
- Scope: no task changes PlayEvent consumers, PostgreSQL runtime configuration, SQLite transfer tooling, filters, saved presets, APIs, statistics, ownership, or user isolation.
- Type consistency: `DatabaseDateDifference` and `PlayEvent.days_to_finish` consistently produce integers; every expression and migration uses only `started` and `ended` source columns.
