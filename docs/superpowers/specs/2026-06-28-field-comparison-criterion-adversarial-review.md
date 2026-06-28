# Field-to-field comparison criterion — adversarial review and edge cases

**Status:** completed
**Date:** 2026-06-28
**Original Design Spec:** [Design Spec](./2026-06-28-field-comparison-criterion-design.md)

---

## 1. Adversarial Analysis & Deep Edge Cases

During an adversarial architectural audit of the field-to-field comparison implementation, several subtle edge cases, semantic behaviors, and potential extensions were identified.

### 1.1 Asymmetric NULL Negation of Django's ~Q
Django translates negation on field-to-field conditions using ~Q(left=F(right)) into standard SQL as:
`NOT (left = right AND left IS NOT NULL)`

This translates logically to:
`left != right OR left IS NULL`

While correct for simple single-field NULL handling, this generates an **asymmetric behavior** when comparing two nullable fields:
* **Case 1: Left is NULL, Right is NOT NULL (e.g., left is NULL, right is 5)**
  * left IS NOT NULL is FALSE, so (left = right AND left IS NOT NULL) is FALSE.
  * NOT (FALSE) is TRUE, so the row is INCLUDED.
* **Case 2: Left is NOT NULL, Right is NULL (e.g., left is 5, right is NULL)**
  * left IS NOT NULL is TRUE.
  * left = right is UNKNOWN (since right is NULL).
  * (left = right AND left IS NOT NULL) resolves to (UNKNOWN AND TRUE) -> UNKNOWN.
  * NOT (UNKNOWN) resolves to UNKNOWN (treated as FALSE in SQL WHERE clauses).
  * **Result:** Row is EXCLUDED.

#### Recommendation & Mitigation
This asymmetric behavior is an artifact of Django's native ORM negation translation. Developers must be aware that using NOT_EQUALS on two nullable fields will behave differently depending on which field holds the NULL value. It is recommended to keep fields non-nullable where logical, or explicitly handle NULL checks if symmetric negation is required.

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

#### Recommendation & Mitigation
Since `SlugField` behaves identically to `CharField` at the database level and represents string-based data, it should be mapped to the "string" comparison group:
```python
    "CharField": "string",
    "TextField": "string",
    "SlugField": "string",  # Map SlugField to enable string-to-string comparisons
```

---

## 3. Database Performance & Indexing

### 3.1 Table Scanning Characteristics
Standard B-Tree database indexes on single columns (e.g., separate indexes on `date_refunded` and `date_purchased`) are designed to optimize literal scans (e.g., `date_refunded < '2026-06-28'`). 

When executing a column-to-column comparison like `Q(date_refunded__lt=F('date_purchased'))`, database engines (such as SQLite) cannot utilize individual indexes to narrow down the query. Instead, the database must perform a **full table scan** (sequential scan) to evaluate the comparison for every row in the dataset.

#### Recommendation & Mitigation
For the current scale of the application, full table scans are extremely fast. However, if any table (e.g., `Session` or `Purchase`) grows significantly, saved filter presets utilizing field comparisons should be kept out of high-frequency UI paths or backed by a composite expression index (e.g., on SQLite/PostgreSQL where expression indexes are supported).

---

## 4. Future Extensions

### 4.1 String Substring Containment Modifiers
The initial implementation supports `EQUALS`, `NOT_EQUALS`, `GREATER_THAN`, and `LESS_THAN`. 

Because Django supports `F()` expressions inside string containment lookups, future iterations could support:
* `INCLUDES` -> `Q(**{f"{left}__contains": F(right)})`
* `EXCLUDES` -> `~Q(**{f"{left}__contains": F(right)})`

These operators would allow robust text-to-text containment checks natively within the filter bar.
