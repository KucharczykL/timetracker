# Field-to-field comparison criterion — adversarial review and edge cases

**Status:** completed
**Date:** 2026-06-28
**Original Design Spec:** [Design Spec](./2026-06-28-field-comparison-criterion-design.md)

---

## 1. Adversarial Analysis & Deep Edge Cases

During an adversarial architectural audit of the field-to-field comparison implementation, several subtle edge cases, semantic behaviors, and potential extensions were identified.

### 1.1 Symmetric and Asymmetric NULL Negation of Django's ~Q

Under Django 6, negation of a field-to-field comparison (using `~Q(left=F(right))`) is compiled dynamically based on the **nullability declarations** of the fields in the model schema.

Django's SQL compiler appends an `IS NOT NULL` clause for each field it knows to be nullable from the model definition.

#### Case A: Both Fields Nullable (Fully Symmetric)
If both `left` and `right` are nullable fields, Django 6 generates the SQL:
`WHERE NOT (left = right AND left IS NOT NULL AND right IS NOT NULL)`

Expanding this expression using De Morgan's laws:
`left != right OR left IS NULL OR right IS NULL`

This truth table shows that the query is **perfectly symmetric**:
* **left is NULL, right is NULL:** Evaluates to `UNKNOWN OR TRUE OR TRUE` -> `TRUE` (Row is **INCLUDED**).
* **left is NULL, right is 5:** Evaluates to `UNKNOWN OR TRUE OR FALSE` -> `TRUE` (Row is **INCLUDED**).
* **left is 5, right is NULL:** Evaluates to `UNKNOWN OR FALSE OR TRUE` -> `TRUE` (Row is **INCLUDED**).
* **left is 5, right is 5:** Evaluates to `FALSE OR FALSE OR FALSE` -> `FALSE` (Row is **EXCLUDED**).
* **left is 5, right is 10:** Evaluates to `TRUE OR FALSE OR FALSE` -> `TRUE` (Row is **INCLUDED**).

Thus, for dual-nullable fields, negation is mathematically symmetric and matches intuitive expectations.

#### Case B: Mixed Nullability (Potential Asymmetry in Case of Database/Schema Drift)
If `left` is nullable (e.g., `date_refunded`) but `right` is non-nullable (e.g., `date_purchased`), Django optimizes the query by omitting the null-check on the non-nullable field, compiling to:
`WHERE NOT (left = right AND left IS NOT NULL)`

Under normal operations, this works flawlessly. However, if **database-to-schema drift** occurs (e.g., during database migrations, direct SQL manual manipulation, or raw inserts where `right` physically contains `NULL` in the database despite being declared as non-nullable in Django), an **asymmetrical edge case** arises:
* **left is NULL, right is NULL (corrupted state):**
  * `left IS NOT NULL` is `FALSE` -> `left = right AND left IS NOT NULL` is `FALSE`.
  * `NOT (FALSE)` is `TRUE` -> **Row is INCLUDED**.
* **left is 5, right is NULL (corrupted state):**
  * `left IS NOT NULL` is `TRUE`.
  * `left = right` is `UNKNOWN`.
  * `(left = right AND left IS NOT NULL)` resolves to `UNKNOWN AND TRUE` -> `UNKNOWN`.
  * `NOT (UNKNOWN)` resolves to `UNKNOWN` (treated as `FALSE` in SQL `WHERE` clauses).
  * **Result:** **Row is EXCLUDED**.

#### Recommendation & Mitigation
In Django 6, field comparison negation is logically robust and symmetric for declared nullable fields. Developers should ensure model nullability configurations (`null=True`) strictly match actual physical database constraints to prevent optimization-induced asymmetries in corrupt or drifted states.

---

## 2. Introspection Limitations

### 2.1 The SlugField Omission
In `games/models.py`, the `Platform` model contains an `icon` field of type `models.SlugField`.
Because `SlugField` has `get_internal_type() == "SlugField"`, it is not listed in `_GROUP_BY_INTERNAL_TYPE`.

```python
# Currently in common/criteria.py:
_GROUP_BY_INTERNAL_TYPE: dict[str, ComparisonGroup] = {
    "CharField": "string",
    "TextField": "string",
    ...
}
```

Any attempt to compare `Platform.icon` directly against standard string fields (`Platform.name` or `Platform.group`) will fail with:
`FilterError: Platform.icon is not a comparable type (SlugField)`

#### Recommendation & Mitigation — IMPLEMENTED
`SlugField` behaves identically to `CharField` at the database level and represents string-based data, so it is mapped to the "string" comparison group:
```python
    "CharField": "string",
    "TextField": "string",
    "SlugField": "string",  # SlugField.get_internal_type() is "SlugField", not "CharField"
```
This was verified empirically (`Platform.icon` is the only omitted string-like field in the project's models) and added to `_GROUP_BY_INTERNAL_TYPE` with a regression test (`TestComparisonGroupResolver::test_slug_field_is_string`).

---

## 3. Database Performance & Indexing

### 3.1 Table Scanning Characteristics
Standard B-Tree database indexes on single columns (e.g., separate indexes on `date_refunded` and `date_purchased`) are designed to optimize literal scans (e.g., `date_refunded < '2026-06-28'`). 

When executing a column-to-column comparison like `Q(date_refunded__lt=F('date_purchased'))`, database engines (such as SQLite) cannot utilize individual indexes to narrow down the query. Instead, the database must perform a **full table scan** (sequential scan) to evaluate the comparison for every row in the dataset.

#### Recommendation & Mitigation
For the current scale of the application, full table scans are extremely fast (SQLite scans a few-thousand-row table in well under a millisecond), and field comparisons have no UI surface yet — they are reachable only via a hand-crafted `?filter=` or a saved preset. No action is warranted.

**Note on the mitigation:** a *composite* B-tree index (e.g. on `(date_refunded, date_purchased)`) does **not** help a column-to-column predicate — there is still no fixed seek value, so the planner full-scans the index at the same cost. Only an *expression* index helps (e.g. `CREATE INDEX ... ON purchase (date_purchased - date_refunded)`), and only if the **query is rewritten** to use that exact expression — Django's ORM does not emit the expression-indexed form for a plain `Q(left__lt=F(right))`. So if scale ever demanded it, the fix would be a bespoke expression index plus a matching query rewrite, not a drop-in composite index.

---

## 4. Future Extensions

### 4.1 String Substring Containment Modifiers — ✅ implemented (#164)
The initial implementation supports `EQUALS`, `NOT_EQUALS`, `GREATER_THAN`, and `LESS_THAN`. `INCLUDES`/`EXCLUDES` for string operands were added in #164 — see `docs/superpowers/specs/2026-06-28-string-field-comparison-design.md`.

Because Django supports `F()` expressions inside string containment lookups (verified — `name__icontains=F("sort_name")` compiles to valid `LIKE` SQL on SQLite), future iterations could support:
* `INCLUDES` -> `Q(**{f"{left}__icontains": F(right)})`
* `EXCLUDES` -> `~Q(**{f"{left}__icontains": F(right)})`

Use `__icontains` (not `__contains`) to match `StringCriterion.INCLUDES` and keep case-insensitivity parity on PostgreSQL (`ILIKE`). The change is small (~3 touch-points: `Modifier.for_field_comparisons`, the `string` branch of `_allowed_comparison_modifiers`, and two cases in `_field_comparison_to_q`). Tracked as a dedicated follow-up issue (independent of #162, which is scoped to numeric/date ordering operators).
