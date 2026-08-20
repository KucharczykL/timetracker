# Exact and Imprecise Temporal-Value Primitives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable, fail-closed temporal value that preserves canonical
day/month/year/decade/range/unknown representation precision and exposes stored
typed query bounds plus shared component/exactness predicates.

**Architecture:** `timetracker.temporal` owns the immutable Python value,
canonical scalar serialization, Django field, and generated-expression wrappers.
A reversible PostgreSQL migration creates the matching `temporal_value` domain
and immutable parser/projection functions; future consumers store the canonical
domain value plus seven persisted generated columns.

**Tech Stack:** Python 3.14 standard library, Django 6, PostgreSQL 18,
pytest/pytest-django.

**Spec:**
`docs/superpowers/specs/2026-08-20-issue-655-temporal-value-primitives-design.md`

## Global Constraints

- Work only on issue #655 from `origin/codex/catalog-wave`; target the final PR
  to `codex/catalog-wave`.
- Preserve only canonical day, month, year, decade, closed/open/unknown-endpoint
  range, and standalone unknown values. Do not implement qualifiers, UI,
  overlap criteria, or legacy migration from #656–#659.
- Reject component-level unspecified `X` values; the decade form is #655's sole
  supported use of `X`. Treat precision as representation granularity rather
  than a cumulative component-knowledge guarantee so later EDTF support does
  not contradict the API.
- Serialize a temporal value as its canonical string or `null`; never serialize
  caller-controlled derived bounds.
- Use Gregorian years 0001–9999 and reject seasons, sets, extended/negative
  years, timestamps, `000X`, ranges without a known endpoint, and
  non-canonical spellings.
- Keep generated query values typed as two nullable PostgreSQL dates, one
  non-null overall precision token, two nullable endpoint-kind tokens, and two
  nullable endpoint-precision tokens.
- Add no dependency: the parser uses `datetime.date`, `calendar.monthrange`,
  enums, and anchored regular expressions from the Python standard library.
- Keep the Makefile's default `PYTEST_WORKERS` for focused and full verification.
- Keep implementation within the approved forecast of two runtime subsystems,
  fewer than 40 files, and fewer than 2,000 non-generated changed lines; stop
  and re-slice if reality crosses a threshold.

## File Structure

| File | Responsibility |
| --- | --- |
| Create `timetracker/temporal.py` | Precision enum, immutable value/parser, stable errors, Django field, and generated-expression wrappers. |
| Create `games/migrations/0017_temporal_value_domain.py` | Immutable SQL parser/projection functions and the `temporal_value` domain, with reverse SQL. |
| Create `tests/test_temporal.py` | Pure value/validation/serialization tests plus isolated Django field and generated-column integration tests. |
| Create `tests/test_temporal_domain.py` | PostgreSQL domain/function parity, raw-write rejection, metadata, and migration reversal/reapplication tests. |

---

### Task 1: Lock the Python temporal-value contract

**Files:** create `tests/test_temporal.py`; create `timetracker/temporal.py`.

**Interfaces:**

- Produces `TemporalPrecision(StrEnum)` values `DAY`, `MONTH`, `YEAR`,
  `DECADE`, `RANGE`, and `UNKNOWN` with lowercase serialized values.
- Produces `TemporalEndpointKind(StrEnum)` values `KNOWN = "known"`,
  `UNKNOWN = "unknown"`, and `OPEN = "open"`.
- Produces immutable `TemporalEndpoint` properties `kind`,
  `value: TemporalValue | None`, `precision: TemporalPrecision | None`,
  `is_known`, `is_unknown`, `is_open`, `has_known_year`, `has_known_month`, and
  `has_known_day`, plus `known(value)`, `unknown()`, and `open()` constructors.
- Produces immutable `TemporalValue` properties `canonical: str | None`,
  `lower_bound: date | None`, `upper_bound: date | None`,
  `precision: TemporalPrecision`, `is_complete_day`, `is_exact_day`, `is_range`,
  `has_known_year`, `has_known_month`, `has_known_day`, and
  `start`/`end: TemporalEndpoint | None`.
- Produces `TemporalValue.parse(value: str | None) -> TemporalValue`,
  `TemporalValue.unknown()`, `TemporalValue.from_day(value: date)`,
  `TemporalValue.from_month(year: int, month: int)`,
  `TemporalValue.from_year(year: int)`,
  `TemporalValue.from_decade(start_year: int)`, and the following range
  constructor:

  ```python
  TemporalValue.range(
      start: TemporalEndpoint,
      end: TemporalEndpoint,
  ) -> TemporalValue
  ```
- Produces `serialize() -> str | None`,
  `parse_temporal_value(value: object) -> TemporalValue`, and
  `validate_temporal_value(value: object) -> None`.
- Produces `TemporalValueParseError(ValueError)` with stable `code` values
  `invalid_type`, `invalid_syntax`, `invalid_date`, `invalid_range`,
  `unsupported_qualifier`, `unsupported_season`, `unsupported_set`,
  `unsupported_year`, and `unsupported_timestamp`.

The implementation keeps derived state private and frozen:

```python
from __future__ import annotations


class TemporalPrecision(StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    DECADE = "decade"
    RANGE = "range"
    UNKNOWN = "unknown"


class TemporalEndpointKind(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    OPEN = "open"


@dataclass(frozen=True, slots=True, init=False)
class TemporalEndpoint:
    kind: TemporalEndpointKind
    value: TemporalValue | None


@dataclass(frozen=True, slots=True, init=False)
class TemporalValue:
    canonical: str | None
    lower_bound: date | None
    upper_bound: date | None
    precision: TemporalPrecision
    start: TemporalEndpoint | None
    end: TemporalEndpoint | None

    def __init__(self, canonical: str | None) -> None:
        parsed = _parse_canonical(canonical)
        object.__setattr__(self, "canonical", parsed.canonical)
        object.__setattr__(self, "lower_bound", parsed.lower_bound)
        object.__setattr__(self, "upper_bound", parsed.upper_bound)
        object.__setattr__(self, "precision", parsed.precision)
        object.__setattr__(self, "start", parsed.start)
        object.__setattr__(self, "end", parsed.end)
```

- [ ] **Step 1: Write the failing supported-value matrix tests.** Parameterize
  `None`, leap and ordinary days/months, years, decades, closed ranges,
  mixed-precision ranges, both open directions, and both unknown-endpoint
  directions. Assert canonical value, exact lower/upper dates, precision,
  endpoint values/kinds/precision, independent component helpers,
  `is_complete_day`, `is_exact_day`, and
  `TemporalValue.parse(value.serialize()) == value` for every row.
- [ ] **Step 2: Run the focused test with default workers and verify it fails.**
  Run `make test-fast ARGS="tests/test_temporal.py -q"`; expect collection to
  fail because `timetracker.temporal` does not exist.
- [ ] **Step 3: Implement the minimal immutable parser and constructors.** Use
  full-match regular expressions only to classify the canonical grammar; use
  `date(...)` and `monthrange(...)` to validate and derive real bounds. Keep
  derived attributes out of the public constructor and make unknown's scalar
  representation `None`.
- [ ] **Step 4: Run the focused test and verify the supported matrix passes.**
  Run `make test-fast ARGS="tests/test_temporal.py -q"`.
- [ ] **Step 5: Add failing validation and constructor-invariant tests.** Cover
  whitespace/case changes, empty string, invalid leap/month/day, `0000`, `000X`,
  reversed ranges, `../..`, `../`, `/..`, `/`, multiple slashes, qualifiers,
  seasons, sets, extended/negative years, timestamps, nested/standalone-unknown
  endpoint values, incoherent endpoint kind/value pairs, wrong Python types,
  invalid constructor arguments, and attempted mutation. Assert exact stable
  codes and useful messages.
- [ ] **Step 6: Implement fail-closed classification and error mapping.** Detect
  excluded EDTF families before the generic syntax error, reject booleans as
  integers in constructors, map known/empty/`..` range tokens to immutable
  `TemporalEndpoint` objects, and enforce range order by the known start's lower
  bound and known end's upper bound. Atomic component helpers derive from the
  components known by the accepted atom; range and unknown return false and
  delegate endpoint questions to `start`/`end`. Keep representation precision,
  component knowledge, complete-day status, and exact-day status as separate
  predicates even though the #655 grammar makes day precision, complete day,
  and exact day equivalent for accepted atomic values.
- [ ] **Step 7: Run the focused test with default workers.** Run
  `make test-fast ARGS="tests/test_temporal.py -q"`; expect all pure tests to
  pass.
- [ ] **Step 8: Commit the Python contract.** Stage only
  `timetracker/temporal.py` and `tests/test_temporal.py`; commit as
  `feat: define temporal value contract`.

### Task 2: Add the PostgreSQL domain and stored query projections

**Files:** modify `timetracker/temporal.py` and `tests/test_temporal.py`; create
`games/migrations/0017_temporal_value_domain.py` and
`tests/test_temporal_domain.py`.

**Interfaces:**

- Produces PostgreSQL domain `temporal_value` over `varchar(64)`.
- Produces immutable SQL functions `timetracker_temporal_is_valid(text) ->
  boolean`, `timetracker_temporal_lower(text) -> date`,
  `timetracker_temporal_upper(text) -> date`, and
  `timetracker_temporal_precision(text) -> text`.
- Produces immutable SQL functions `timetracker_temporal_start_kind(text) ->
  text`, `timetracker_temporal_end_kind(text) -> text`,
  `timetracker_temporal_start_precision(text) -> text`, and
  `timetracker_temporal_end_precision(text) -> text`.
- Produces `TemporalValueField`, storing the domain scalar and returning
  `TemporalValue` instances; defaults are `null=True`, `blank=True`,
  `default=None`, and `editable=False`.
- Produces Django expressions `TemporalLowerBound(expression)`,
  `TemporalUpperBound(expression)`, `TemporalPrecisionValue(expression)`,
  `TemporalStartKind(expression)`, `TemporalEndKind(expression)`,
  `TemporalStartPrecision(expression)`, and
  `TemporalEndPrecision(expression)` with typed output fields.
- Produces shared ORM predicates
  `temporal_has_known_year_q(field_name: str, *, endpoint: Literal["start", "end"] | None = None) -> models.Q`,
  `temporal_has_known_month_q(field_name: str, *, endpoint: Literal["start", "end"] | None = None) -> models.Q`,
  `temporal_has_known_day_q(field_name: str, *, endpoint: Literal["start", "end"] | None = None) -> models.Q`, and
  `temporal_exact_day_q(field_name: str) -> models.Q`. The first three own all
  atomic/endpoint component-knowledge rules; the last owns strict atomic-day
  exactness and is the extension point for #656 qualifiers.

The public SQL functions use three private immutable atom functions with exact
roles:

```text
_timetracker_temporal_atom_lower(text) -> date
_timetracker_temporal_atom_upper(text) -> date
_timetracker_temporal_atom_precision(text) -> text

null canonical       -> lower null, upper null, precision "unknown"
single atom           -> atom bounds/precision; endpoint metadata null
start/end range       -> known kinds and each atom's precision
../end open range     -> start kind open; end kind/precision known
start/.. open range   -> start kind/precision known; end kind open
/end unknown range    -> start kind unknown; end kind/precision known
start/ unknown range  -> start kind/precision known; end kind unknown
```

Each atom helper branches over exactly `YYYY-MM-DD`, `YYYY-MM`, `YYYY`, and
`YYYX`; it constructs a real date rather than using PostgreSQL's normalizing
`to_date()`. The public functions accept exactly one empty endpoint as unknown,
distinguish it from `..`, and reject multiple slashes, ranges without a known
endpoint, and a bounded start lower date after the bounded end upper date.

- [ ] **Step 1: Write failing migration/domain contract tests.** Assert the
  domain base type and constraint, exact function return types and immutable
  volatility, SQL results for the same supported matrix as Python, `null ->
  (null, null, unknown)`, identical unbounded projections without canonical
  collapse but different endpoint kinds for open versus unknown endpoints,
  nullable endpoint metadata for atomic values, and database rejection for
  every invalid expression.
- [ ] **Step 2: Run the focused domain tests and verify they fail.** Run
  `make test-fast ARGS="tests/test_temporal_domain.py -q"`; expect missing
  domain/function failures.
- [ ] **Step 3: Add migration `0017_temporal_value_domain`.** Create the two
  private atom functions named above plus a private atom-precision function,
  then all seven projection functions, then `timetracker_temporal_is_valid`,
  then the domain. Reverse in the exact opposite order. Implement `is_valid` as
  an immutable PL/pgSQL exception boundary that calls all seven public
  projections and returns false for any rejected value; the domain check is
  `VALUE IS NULL OR timetracker_temporal_is_valid(VALUE)`.
- [ ] **Step 4: Run domain tests and compare SQL with Python.** Run
  `make test-fast ARGS="tests/test_temporal_domain.py -q"`; expect the shared
  valid/invalid fixture matrices to agree.
- [ ] **Step 5: Write failing Django-field integration tests.** Under
  `isolate_apps("games")`, declare a temporary model containing
  `TemporalValueField` and seven persisted `GeneratedField`s using the public
  expressions. Assert field deconstruction, PostgreSQL-only behavior, Python
  assignment/full-clean conversion, ORM/database/dump-data round-trips, typed
  generated values, filters over atomic/endpoint precision and endpoint kind
  without canonical-text expressions in their SQL, all shared component-query
  helpers for atomic/start/end values, `temporal_exact_day_q` excluding every
  non-day value, endpoint-argument validation, and raw invalid insert rejection.
- [ ] **Step 6: Implement the Django bridge.** Map parse errors to Django
  `ValidationError` with the same code, return the PostgreSQL domain from
  `db_type`, serialize only the canonical scalar, reject non-PostgreSQL
  backends, give each expression the exact typed `output_field`, and centralize
  the generated-field suffix and currently equivalent precision lists inside
  the shared query helpers. Consumers must never reconstruct those lists.

  ```python
  class TemporalValueField(models.CharField):
      def __init__(self, *args, **kwargs):
          kwargs.setdefault("max_length", 64)
          kwargs.setdefault("null", True)
          kwargs.setdefault("blank", True)
          kwargs.setdefault("default", None)
          kwargs.setdefault("editable", False)
          super().__init__(*args, **kwargs)

      def db_type(self, connection) -> str:
          if connection.vendor != "postgresql":
              raise NotSupportedError("TemporalValueField requires PostgreSQL.")
          return "temporal_value"


  class TemporalLowerBound(models.Func):
      function = "timetracker_temporal_lower"
      output_field = models.DateField(null=True)


  class TemporalUpperBound(models.Func):
      function = "timetracker_temporal_upper"
      output_field = models.DateField(null=True)


  class TemporalPrecisionValue(models.Func):
      function = "timetracker_temporal_precision"
      output_field = models.CharField(max_length=7)


  class TemporalStartKind(models.Func):
      function = "timetracker_temporal_start_kind"
      output_field = models.CharField(max_length=7, null=True)


  class TemporalEndKind(models.Func):
      function = "timetracker_temporal_end_kind"
      output_field = models.CharField(max_length=7, null=True)


  class TemporalStartPrecision(models.Func):
      function = "timetracker_temporal_start_precision"
      output_field = models.CharField(max_length=7, null=True)


  class TemporalEndPrecision(models.Func):
      function = "timetracker_temporal_end_precision"
      output_field = models.CharField(max_length=7, null=True)
  ```
- [ ] **Step 7: Run both focused suites with default workers.** Run
  `make test-fast ARGS="tests/test_temporal.py tests/test_temporal_domain.py -q"`.
- [ ] **Step 8: Prove migration reversibility.** In a transaction-marked test,
  capture graph leaf nodes, migrate to `0016_library_config_uuid_primary_key`,
  assert domain/functions are absent, migrate to `0017`, assert they are
  restored, and restore leaf nodes in `finally` using fresh
  `MigrationExecutor` instances.
- [ ] **Step 9: Commit the persistence contract.** Stage the four implementation
  and test files; commit as `feat: persist temporal query bounds`.

### Task 3: Cross-cutting verification and handoff

**Files:** all issue files; remove this issue's design and plan only after the
approved implementation and verification evidence are complete.

- [ ] **Step 1: Run the complete fast gate.** Run `make check-fast` with the
  Makefile's default workers. If it fails, identify whether the branch diff
  caused the failure; correct an in-scope regression, but stop and report an
  unrelated failure rather than expanding #655.
- [ ] **Step 2: Run the authoritative full gate.** Run `make check` with the
  Makefile's default workers and record its final exit status and worker count.
- [ ] **Step 3: Check migration and diff integrity.** Run `git diff --check`,
  inspect `git diff origin/codex/catalog-wave...HEAD`, and confirm
  `make check-migrations` reports no drift.
- [ ] **Step 4: Reconcile scope against the approved gate.** Record actual
  affected-file and non-generated changed-line totals; confirm no Release,
  Edition, Game year, UI, filter/preset, statistic, qualifier, or broad migration
  change entered the diff. Stop and seek a re-slice if a threshold was crossed.
- [ ] **Step 5: Remove transient planning artifacts.** Delete this design and
  plan in a final documentation cleanup commit, preserving the approved planning
  gate in branch history as established by recent issue branches.
- [ ] **Step 6: Push and open the PR.** Push
  `codex/issue-655-temporal-values`, open a PR targeting `codex/catalog-wave`,
  link #655, summarize the canonical contract and deferred boundaries, and
  include focused/full verification plus forecast-versus-actual totals.
