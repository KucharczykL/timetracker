# Field-to-field comparison criterion — design spec (#129)

**Status:** implemented (T1–T5 merged on `issue-129-field-comparison`)
**Date:** 2026-06-28

---

## 1. Context / problem

The filter algebra in `common/criteria.py` compared a model column against a
literal value only. Issue #129 adds **column-to-column comparison** as a
first-class, general capability: e.g. "find purchases where `date_refunded` <
`date_purchased`" (a data-quality check) or "find sessions where `timestamp_end`
< `timestamp_start`" (a clock-error check).

---

## 2. Design decisions

### 2.1 Self-describing list on the base filter, not a flag on existing criteria

Field comparisons are expressed as a dedicated `field_comparisons:
list[FieldComparisonCriterion]` field declared directly on `OperatorFilter`.
Every concrete filter subclass inherits it with no re-declaration.

Rationale: a column-to-column comparison is structurally different from a
column-to-literal criterion — its two operands are field names, not typed
values. Bolting an "other field" flag onto `DateCriterion` etc. would conflate
two orthogonal concerns and require every criterion type to carry dead fields
most of the time. The separate list keeps the algebra clean and future-proof
(multiple comparisons can coexist in one filter node).

### 2.2 Compare raw model columns — no `__date` truncation, no hours conversion

`_field_comparison_to_q` builds `Q(left__op=F(right))` directly on the raw
column names. No `__date` lookup is appended for datetime fields and no
`timedelta` conversion is done for durations.

Rationale: simplicity **and** correctness. The primary use case is error
detection (e.g. `timestamp_end < timestamp_start`). Truncating both sides to
date would make two timestamps on the same calendar day appear equal, missing
the case where a session recorded `23:00 → 22:00` on the same day. Raw
comparison preserves full precision and lets the database resolve the operands
with its native column semantics.

### 2.3 Comparable-field set derived by Django model introspection, gated per filter by a one-line hook

`_comparison_group_for(model, column)` calls `model._meta.get_field(column)` to
resolve the column's Django field type and maps it to a `ComparisonGroup` string
via `_GROUP_BY_INTERNAL_TYPE`. For `GeneratedField` columns it reads
`output_field` to get the underlying type.

Each concrete filter enables this by overriding the one-line `_comparison_model`
hook to return its primary model. The base `OperatorFilter._comparison_model`
returns `None` (comparisons unsupported), so a filter that hasn't opted in fails
fast with a clear `FilterError`.

There is no registry of comparable fields and no per-field declaration — the
full set of comparable columns on a model is discovered at query time, which
means new model fields become comparable automatically as long as their type
maps to a group.

### 2.4 Type groups

`_GROUP_BY_INTERNAL_TYPE` defines six groups:

| group | field types |
|-------|-------------|
| `date` | `DateField` |
| `datetime` | `DateTimeField` |
| `duration` | `DurationField` |
| `number` | `IntegerField`, `PositiveIntegerField`, `PositiveSmallIntegerField`, `SmallIntegerField`, `BigIntegerField`, `FloatField`, `DecimalField` |
| `string` | `CharField`, `TextField` |
| `bool` | `BooleanField` |

**`date` and `datetime` are separate groups** — comparing a `DateField` to a
`DateTimeField` is a type mismatch and raises `FilterError`.

Relations (FK, M2M, reverse accessors), `AutoField` / `BigAutoField`, and any
field type absent from the table (e.g. `JSONField`) are excluded; they raise
`FilterError` when named as an operand.

### 2.5 Modifier set by group

`Modifier.for_field_comparisons()` returns four ordered/equality modifiers:
`EQUALS`, `NOT_EQUALS`, `GREATER_THAN`, `LESS_THAN`. `BETWEEN` and `NOT_BETWEEN`
are not supported (they require a scalar bound, not a second column).

`_allowed_comparison_modifiers(group)` restricts further:
- `bool`: equality only (`EQUALS`, `NOT_EQUALS`)
- all other groups: the full four-modifier set

### 2.6 Validation on the `to_q()` path

All validation (column existence, type-group check, modifier check, self-compare
check) happens inside `_apply_operators`, which is called by `to_q()`. Errors
surface as `FilterError`.

`filter_from_json` calls `to_q()` eagerly after parsing, so a bad
`field_comparisons` entry in a `?filter=` URL or saved preset raises
`FilterError` at parse time and is caught by the view layer (warn-and-ignore) or
the API layer (HTTP 400) before any queryset is evaluated.

### 2.7 NULL operand semantics

For the ordered comparisons (`<`, `>`) and `EQUALS`, if either `left` or `right`
is `NULL` on a row the SQL comparison yields `UNKNOWN`, which Django excludes —
the correct default for data-quality queries.

`NOT_EQUALS` is the exception: Django emits `~Q(left=F(right))` as
`NOT (left = right AND left IS NOT NULL)`, i.e. `left != right OR left IS NULL`,
so it **includes** rows where `left` is `NULL`. This is Django's documented
negation behaviour (not SQL's bare three-valued logic); it is verified by a DB
test and called out in the `FieldComparisonCriterion` docstring so callers are
not surprised.

### 2.8 Surface: JSON filter + saved presets + API; no filter-bar UI widget this round

`field_comparisons` serializes and deserializes through the existing
`from_json`/`to_json` paths and therefore works with `FilterPreset` (saved
filter configurations) and the `?filter=` query parameter. No filter-bar UI
widget is introduced in this release; that is a deferred follow-up.

---

## 3. JSON shape

A `field_comparisons` list is an optional top-level key alongside criteria and
operator sub-filters. An empty list is omitted from the serialized form.

```json
{
  "field_comparisons": [
    {
      "left": "date_refunded",
      "right": "date_purchased",
      "modifier": "LESS_THAN"
    }
  ]
}
```

Multiple entries in the list are AND-combined (each comparison must hold).
`modifier` is one of the four allowed values: `"EQUALS"`, `"NOT_EQUALS"`,
`"GREATER_THAN"`, `"LESS_THAN"`.

---

## 4. Architecture / files changed

**No model changes. No migrations.**

### `common/criteria.py`

- `FieldComparisonCriterion` — new `_Criterion` subclass with `left`, `right`,
  `modifier` fields. `to_q` delegates to `_field_comparison_to_q`; ignores the
  `field_name` argument (operands are self-contained). `to_json` always emits
  `left` and `right` even when empty (same pattern as `BoolCriterion.value`).
- `_field_comparison_to_q(left, right, modifier)` — builds `Q(left__op=F(right))`
  for the four supported modifiers; raises `FilterError` for anything else.
- `_comparison_group_for(model, column)` — resolves a column to a `ComparisonGroup`
  via `Model._meta.get_field`; handles `GeneratedField` via `output_field`;
  rejects relations, AutoField, and unmapped types.
- `_GROUP_BY_INTERNAL_TYPE` — `dict[str, ComparisonGroup]` mapping Django internal
  type names to the six groups.
- `_allowed_comparison_modifiers(group)` — returns the modifier list for a group.
- `Modifier.for_field_comparisons()` — classmethod returning the four ordered/equality
  modifiers.
- `OperatorFilter.field_comparisons` — `list[FieldComparisonCriterion]` field on
  the base class (default empty list).
- `OperatorFilter._comparison_model()` — hook returning `None` by default.
- `OperatorFilter._apply_operators()` — extended to validate and apply
  `field_comparisons` after AND/OR/NOT sub-filters.
- `OperatorFilter.from_json()` — extended to parse the `field_comparisons` key
  (mirrors the operator-field branch: null/absent → `[]`, single item tolerated).
- `OperatorFilter.to_json()` — extended to emit `field_comparisons` when non-empty.
- `_COMPARISON_FIELD = "field_comparisons"` — sentinel constant keeping the
  branching logic isolated from `_OPERATOR_FIELDS`.
- `ComparisonGroup` — new transparent type alias (`type ComparisonGroup = str`).
- `FieldComparisonCriterion` registered in `_CRITERION_TYPES`.

### `games/filters.py`

Six concrete filters each add a one-line `_comparison_model` override returning
their primary model via a lazy import:

| filter | model |
|--------|-------|
| `GameFilter` | `Game` |
| `SessionFilter` | `Session` |
| `PurchaseFilter` | `Purchase` |
| `DeviceFilter` | `Device` |
| `PlatformFilter` | `Platform` |
| `PlayEventFilter` | `PlayEvent` |

---

## 5. Testing

All tests are in `tests/test_filters.py`, organized by task:

**T1 — `_field_comparison_to_q` and `FieldComparisonCriterion`**
(`TestFieldComparisonCriterion`): unit tests for all four supported modifiers;
`FilterError` on `BETWEEN`; `to_q` delegation; `field_name` ignored;
`to_json` always emits `left`/`right`; roundtrip for `LESS_THAN` and the default
`EQUALS` modifier; `Modifier.for_field_comparisons()` return value.

**T2 — Introspection (`_comparison_group_for`, `_allowed_comparison_modifiers`)**
(`TestComparisonGroupResolver`): concrete field → group for each group type
(date, datetime, duration via `GeneratedField`, number float/int, string, bool);
`FilterError` for FK relation, M2M relation, `AutoField`, and nonexistent column;
bool group is equality-only; date group is fully ordered.

**T3 — `OperatorFilter` wiring** (`TestFieldComparisonWiring`): happy-path Q;
serialization (non-empty emits key, empty omits); roundtrip restores equal
object; `FilterError` for unknown column, cross-group pair, disallowed modifier
for bool, self-compare, M2M relation, FK relation; no-model base raises with
message "does not support field comparisons"; integration test (JSON string →
`from_json` → `to_q` happy path and bad-column path).

**T4 — `_comparison_model` overrides** (`TestFilterComparisonModels`): single
test asserts all six real filters return their correct model class; DB-backed
tests for `PurchaseFilter` happy path, JSON parse roundtrip, cross-group error
through `parse_purchase_filter`, and `SessionFilter` comparison.

**T5 — End-to-end DB** (`TestFieldComparisonEndToEnd`): four DB-backed tests:
(a) `date_refunded < date_purchased` finds the anomalous purchase and excludes
both normal and NULL-refund rows; (b) `timestamp_end < timestamp_start` on the
same calendar day is caught only by raw-datetime comparison (would be missed with
`__date` truncation — the `23:00 → 22:00` case); (c) `duration_total >
duration_manual` with a `GeneratedField` operand; (d) JSON round-trip through
`filter_to_json` + `parse_purchase_filter` queries identically.

---

## 6. Follow-ups

Three items were deferred and will be tracked as separate GitHub issues:

1. **Filter-bar UI widget** — a client-side widget for building
   `field_comparisons` entries in the filter bar (select left field, modifier,
   right field). Needs the `FilterField` descriptor work (item 2) to enumerate
   comparable fields at render time.

2. **`FilterField` descriptor refactor ("Z")** — replace the per-filter
   `_comparison_model` hook with a first-class `FilterField` descriptor that
   declares each criterion's target column, type group, and comparability in one
   place. Eliminates the implicit coupling between `games/filters.py`'s field
   names and `games/models.py`'s column names.

3. **Optional `compare-by-date` modifier for datetime fields** — an opt-in
   `__date` truncation modifier for comparing two `DateTimeField` columns at date
   granularity (i.e. "same calendar day"), distinct from the raw-datetime default.
   Deferred pending a concrete use case.
