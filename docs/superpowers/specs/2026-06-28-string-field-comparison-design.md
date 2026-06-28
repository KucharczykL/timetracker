# String-contains field comparison (INCLUDES/EXCLUDES) — design (#164)

## Context

Field-to-field comparison (#129) lets a filter compare two model columns via Django
`F()` expressions (`left <op> right`), with the operands type-checked against the
filter's model. The initial implementation supported four modifiers: `EQUALS`,
`NOT_EQUALS`, `GREATER_THAN`, `LESS_THAN`.

The #129 adversarial review (§4.1) flagged a zero-machinery extension: Django accepts an
`F()` expression as the RHS of a string-containment lookup
(`name__icontains=F("sort_name")` compiles to valid `LIKE`/`ILIKE` SQL). This change
(#164) adds **INCLUDES / EXCLUDES** as field-comparison modifiers, gated to **string**
operands. Concrete use case: find games whose `name` contains their `sort_name`.

Independent of #162 (numeric/date `>=`/`<=` ordering operators).

## Decisions

- **Case-insensitive `__icontains`** (not `__contains`) — matches `StringCriterion.INCLUDES`
  and keeps PostgreSQL `ILIKE` parity.
- **String keeps all six operators.** String columns already allowed lexicographic
  `GREATER_THAN`/`LESS_THAN` field comparison; that stays. The new branch adds
  `INCLUDES`/`EXCLUDES` on top → string = EQUALS, NOT_EQUALS, GREATER_THAN, LESS_THAN,
  INCLUDES, EXCLUDES. Numeric/date/datetime/duration groups stay ordered-only (no
  containment); bool stays equality-only.
- **Backend-only.** Filter algebra + tests + docs. No filter-bar UI widget (matches
  #129's deferral).

## Implementation

Three touch-points in `common/criteria.py`, all on the existing `FieldComparisonCriterion`
(no new criterion class):

1. **`Modifier`** — split the field-comparison vocabulary into an ordered subset and a
   full set, so there are no duplicated literals:
   - `for_ordered_field_comparisons()` → `[EQUALS, NOT_EQUALS, GREATER_THAN, LESS_THAN]`
     (valid for every comparable group).
   - `for_field_comparisons()` → ordered subset + `[INCLUDES, EXCLUDES]` (the full,
     string-eligible set).

2. **`_allowed_comparison_modifiers(group)`** — per-group gating:
   - `bool` → `[EQUALS, NOT_EQUALS]`
   - `string` → `for_field_comparisons()` (all six)
   - otherwise (number/date/datetime/duration) → `for_ordered_field_comparisons()`

3. **`_field_comparison_to_q(left, right, modifier)`** — two new cases:
   - `INCLUDES` → `Q(**{f"{left}__icontains": F(right)})`
   - `EXCLUDES` → `~Q(**{f"{left}__icontains": F(right)})`

The existing `OperatorFilter._apply_operators` validation (same-group requirement,
modifier-allowed check, self-compare/relation/unknown-column rejection) already covers the
new modifiers: a `INCLUDES` on a non-string comparison raises `FilterError` because the
modifier is not in that group's allowed set, and both operands must share the `string`
group, so no cross-type containment is possible.

## NULL & empty-string semantics

- **INCLUDES** (`left__icontains=F(right)`) — `LIKE` is NULL/unknown when either operand is
  NULL, so NULL rows are **excluded** (same as `EQUALS`/ordered).
- **EXCLUDES** (`~Q(left__icontains=F(right))`) — mirrors `NOT_EQUALS`: Django appends an
  `IS NOT NULL` guard per *nullable* operand, so a NULL on a nullable side **includes** the
  row (symmetric when both are nullable). When both operands are non-nullable, EXCLUDES is
  the exact complement of INCLUDES.
- **Empty string** — an empty `right` (`""`, not NULL) is a substring of every non-NULL
  `left`, so INCLUDES then matches all rows with a non-NULL `left`. Documented in the
  `FieldComparisonCriterion` docstring because `sort_name` (and similar) default to `""`.

## Tests (`tests/test_filters.py`, extending existing T1–T5 classes)

- **T1** — `_field_comparison_to_q` helper cases for INCLUDES/EXCLUDES; updated
  `for_field_comparisons()` (now six) and new `for_ordered_field_comparisons()` (four).
- **T2** — `_allowed_comparison_modifiers`: string group adds containment (and keeps
  ordering); number group excludes containment; date group updated to the ordered subset.
- **T3** — INCLUDES on a string-group comparison builds the expected Q; INCLUDES on a
  number-group comparison raises `FilterError`.
- **T5** — DB-backed `Game.name` INCLUDES/EXCLUDES `Game.sort_name`: containment match,
  non-match (EXCLUDES complement), case-insensitivity, empty-string semantics, and a JSON
  round-trip through `parse_game_filter`.

## Verification

- `uv run --with pytest-django pytest tests/test_filters.py` — all green.
- `make typecheck` (mypy) and `make lint` (ruff) — clean.

## Out of scope

- Filter-bar UI widget for field comparisons (deferred, as in #129).
- Numeric/date `>=`/`<=` operators (#162).
