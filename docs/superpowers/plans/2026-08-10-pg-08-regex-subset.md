# PostgreSQL-Native Regex Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PostgreSQL the sole regex parser and execution contract.

**Architecture:** Keep value-shape and length checks in `StringCriterion`; use a
parameterized PostgreSQL expression for syntax validation. The existing
transaction-local statement timeout remains the runtime safeguard.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 17, pytest.

## Global Constraints

- No schema migration or preset-data migration.
- Regex values are capped at 200 characters.
- PostgreSQL error `2201B` is a user filter error; other database errors propagate.
- Keep default pytest-xdist worker configuration.

---

### Task 1: Replace the application regex grammar

**Files:**
- Delete: `common/regex_patterns.py`
- Modify: `common/criteria.py`
- Modify: `tests/test_filters.py`

**Interfaces:** `StringCriterion.from_json()` raises `FilterError` for a
non-string, overlong, or PostgreSQL-invalid regex.

- [ ] Write a failing test that accepts PostgreSQL inline flags and rejects a
  PostgreSQL-invalid pattern through `parse_game_filter()`.
- [ ] Implement parameterized `SELECT '' ~ %s` validation and translate only
  SQLSTATE `2201B` into `FilterError`.
- [ ] Remove the handwritten parser and its private `re._parser` dependency.
- [ ] Run `make test ARGS='tests/test_filters.py tests/test_filter_execution.py'`.

### Task 2: Document and verify the PostgreSQL contract

**Files:**
- Modify: `docs/configuration.md`
- Modify: `tests/test_filter_execution.py`

- [ ] Replace the portable-subset documentation with PostgreSQL syntax and the
  statement-timeout safety boundary.
- [ ] Retain ORM and timeout coverage, adding a PostgreSQL-native accepted
  pattern.
- [ ] Run `make check` with default workers.
