# PG-02 Generated Purchase-Price Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Purchase.price_per_game` a PostgreSQL-safe persisted generated column when a Purchase has not yet been linked to any games.

**Architecture:** Keep `Purchase.price_per_game` as a stored Django `GeneratedField` and retain `converted_price` as its preferred numerator. Replace its direct `num_purchases` denominator with `NullIf(F("num_purchases"), 0)`, so the initial unlinked row stores `NULL` and the existing M2M signal recalculates its normal per-game value after links are added. Replace the generated column through a Django remove-and-add migration.

**Tech Stack:** Python 3.14, Django 6 `GeneratedField`, Django migrations, pytest-django, GNU Make.

## Global Constraints

- Scope is limited to PG-02: do not add PostgreSQL runtime configuration, a migration baseline, a SQLite transfer, or changes to Purchase write paths, `num_purchases` signals, price conversion, filters, presets, APIs, statistics, ownership, or user isolation.
- Preserve the persisted `price_per_game` column name and its `FloatField` output type.
- The expression must be `Coalesce(F("converted_price"), F("price"), 0) / NullIf(F("num_purchases"), 0)`.
- An unlinked Purchase must persist `price_per_game=NULL`; linked Purchases must retain converted-price precedence and division by the M2M-maintained count.
- Use `make` targets for every project command. The final verification gate is `make check`.

---

## File structure

- Create `tests/test_generated_purchase_price_columns.py`: database-backed behavior and schema regression tests for `Purchase.price_per_game`.
- Modify `games/models.py`: import `NullIf` and guard only the generated field denominator.
- Create `games/migrations/0035_alter_purchase_price_per_game.py`: remove-and-add migration for the new stored generated expression.

### Task 1: Guard the persisted per-game price against an empty M2M count

**Files:**
- Create: `tests/test_generated_purchase_price_columns.py`
- Modify: `games/models.py:12,194-199`
- Create: `games/migrations/0035_alter_purchase_price_per_game.py`

**Interfaces:**
- Consumes: `Purchase.games` and its existing `m2m_changed` receiver, which persists `num_purchases = instance.games.count()` after `post_add`/`post_remove`/`post_clear`.
- Produces: `Purchase.price_per_game: float | None`, a persisted generated value that is `None` when `num_purchases == 0`, otherwise `Coalesce(converted_price, price, 0) / num_purchases`.

- [ ] **Step 1: Write the failing behavior and schema tests**

Create `tests/test_generated_purchase_price_columns.py` with these exact tests. The first test captures the PostgreSQL insert failure as a schema-level regression and confirms the existing M2M signal still causes recalculation. The second preserves converted-price precedence. The third prevents a future direct denominator or generated-column dependency.

```python
from datetime import date

import pytest
from django.db import connection, models
from django.db.models import F

from games.models import Game, Purchase

pytestmark = pytest.mark.django_db


def test_price_per_game_is_null_until_games_are_linked():
    purchase = Purchase.objects.create(
        date_purchased=date(2026, 8, 9),
        price=12,
        price_currency="USD",
    )
    purchase.refresh_from_db()

    assert purchase.num_purchases == 0
    assert purchase.price_per_game is None

    purchase.games.set(
        [Game.objects.create(name="Hades"), Game.objects.create(name="Celeste")]
    )
    purchase.refresh_from_db()

    assert purchase.num_purchases == 2
    assert purchase.price_per_game == 6


def test_price_per_game_still_prefers_converted_price():
    purchase = Purchase.objects.create(
        date_purchased=date(2026, 8, 9),
        price=12,
        converted_price=15,
        price_currency="USD",
        converted_currency="USD",
    )
    purchase.games.set(
        [Game.objects.create(name="Hollow Knight"), Game.objects.create(name="Tunic")]
    )
    purchase.refresh_from_db()

    assert purchase.price_per_game == 7.5


def test_price_per_game_uses_guarded_source_columns():
    field = Purchase._meta.get_field("price_per_game")
    references = {
        expression.name
        for expression in field.expression.flatten()
        if isinstance(expression, F)
    }
    sql, _ = field.generated_sql(connection)

    assert field.db_persist is True
    assert isinstance(field.output_field, models.FloatField)
    assert references == {"converted_price", "price", "num_purchases"}
    assert "NULLIF" in sql.upper()
```

- [ ] **Step 2: Run the focused test to verify the regression guard fails**

Run:

```bash
make test ARGS="tests/test_generated_purchase_price_columns.py -x"
```

Expected: `test_price_per_game_uses_guarded_source_columns` fails because the current generated SQL divides directly by `num_purchases` and does not contain `NULLIF`. The SQLite behavior tests may pass because SQLite returns `NULL` for the unguarded zero denominator.

- [ ] **Step 3: Use `NullIf` in the model expression**

Modify the existing functions import in `games/models.py` and only the `Purchase.price_per_game` expression:

```python
from django.db.models.functions import Coalesce, NullIf

# ...

price_per_game = GeneratedField(
    expression=Coalesce(F("converted_price"), F("price"), 0)
    / NullIf(F("num_purchases"), 0),
    output_field=models.FloatField(),
    db_persist=True,
    editable=False,
)
```

Do not change the `num_purchases` field or the `update_num_purchases` signal: its existing update supplies the nonzero denominator after game links are written.

- [ ] **Step 4: Generate, rewrite, and inspect the generated-column migration**

Run:

```bash
make makemigrations
```

Expected: Django produces `games/migrations/0035_alter_purchase_price_per_game.py` with an `AlterField`. Replace that operation with the following ordered operations, keeping the generated field definition produced by Django except for the operation type:

```python
operations = [
    migrations.RemoveField(
        model_name="purchase",
        name="price_per_game",
    ),
    migrations.AddField(
        model_name="purchase",
        name="price_per_game",
        field=models.GeneratedField(
            db_persist=True,
            expression=django.db.models.expressions.CombinedExpression(
                django.db.models.functions.comparison.Coalesce(
                    models.F("converted_price"), models.F("price"), 0
                ),
                "/",
                django.db.models.functions.comparison.NullIf(
                    models.F("num_purchases"), 0
                ),
            ),
            output_field=models.FloatField(),
        ),
    ),
]
```

Confirm the migration depends on `("games", "0034_alter_session_duration_total")`, imports the expression/function modules needed by the serialized field, and contains no `RunPython`, `RunSQL`, or data-copy operation. The remove-and-add causes the database to recompute the stored value from the three existing source columns.

- [ ] **Step 5: Run the focused tests after the model and migration change**

Run:

```bash
make test ARGS="tests/test_generated_purchase_price_columns.py -x"
```

Expected: PASS. The unlinked Purchase stores `None`, two links yield `12 / 2 == 6`, the converted value yields `15 / 2 == 7.5`, and the generated SQL contains `NULLIF`.

- [ ] **Step 6: Run the full project verification gate**

Run:

```bash
make check
```

Expected: PASS, including formatting, linting, mypy, TypeScript checks/tests, and the complete Python/e2e suite.

- [ ] **Step 7: Commit the implementation**

```bash
git add games/models.py games/migrations/0035_alter_purchase_price_per_game.py tests/test_generated_purchase_price_columns.py
git commit -m "fix: make generated purchase prices PostgreSQL-compatible"
```

## Plan self-review

- Spec coverage: Task 1 covers the guarded denominator, unlinked-row safety, converted-price precedence, the persisted `FloatField` schema contract, remove-and-add migration, automatic reversibility, focused verification, and the final `make check` gate.
- Scope: no task changes filters, saved presets, APIs, statistics, ownership, PostgreSQL runtime configuration, SQLite transfer tooling, or the existing Purchase write/M2M signal paths.
- Type consistency: `Purchase.price_per_game` is consistently specified as `float | None`; the model and migration use the same three source columns and the same `FloatField` output.
