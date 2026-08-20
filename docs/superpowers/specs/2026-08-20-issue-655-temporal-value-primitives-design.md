# TIME-01 (#655): exact and imprecise temporal-value primitives

Status: awaiting approval 2026-08-20. Parent phase: #600. This design is
governed by the
[timetracker overhaul charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md)
and the
[catalog foundation delivery wave](2026-08-20-catalog-wave-design.md).

## Outcome and boundary

TIME-01 introduces the final reusable value and persistence contract for exact
calendar days and the imprecise month, year, decade, range, and unknown values
that later catalog and player-history models will store. The canonical EDTF
expression remains the source representation. Parsed lower and upper calendar
bounds plus a stable precision token are persisted as typed generated columns,
so normal queries never reparse the canonical expression.

This issue does not add a model that consumes the primitive. In particular, it
does not add `Edition` or `Release`, change either legacy Game year field, or
migrate any existing fact. Those belong to #649 and #650. Approximate and
uncertain qualifiers remain #656; entry and presentation UI remains #657;
overlap-filter criteria and saved-filter contracts remain #658; broad legacy
temporal migration remains #659. Seasons, sets, extended or negative years,
timestamps, day parts, and raw user-authored EDTF remain unsupported.

## Canonical contract

The supported expressions are a deliberately small generated subset of the
[Library of Congress EDTF specification](https://www.loc.gov/standards/datetime/).
The application accepts only canonical spelling; it does not trim, case-fold,
or silently normalize input.

| Precision | Canonical value | Lower bound | Upper bound |
| --- | --- | --- | --- |
| unknown | JSON/Python/SQL `null` | `null` | `null` |
| day | `2024-02-29` | `2024-02-29` | `2024-02-29` |
| month | `2024-02` | `2024-02-01` | `2024-02-29` |
| year | `2024` | `2024-01-01` | `2024-12-31` |
| decade | `199X` | `1990-01-01` | `1999-12-31` |
| closed range | `1999/2001-03` | `1999-01-01` | `2001-03-31` |
| open-start range | `../2001-03` | `null` | `2001-03-31` |
| open-end range | `1999/..` | `1999-01-01` | `null` |

Four-digit Gregorian years from 0001 through 9999 are supported. A decade has
exactly one rightmost `X`; `000X` is rejected because Python and PostgreSQL
calendar dates have no year zero. Range endpoints may independently use day,
month, year, or decade precision. A range's own precision token is always
`range`, even when both endpoints have the same precision or name the same day.
`../..` is rejected because it carries no information beyond unknown.

Unknown is serialized as `null`, not an invented date or the open-end marker
`..`. Empty interval endpoints are not accepted in this slice: EDTF distinguishes
an unknown endpoint from an open endpoint, while the approved charter asks this
primitive for open ranges and a standalone unknown date. A later requirement
for unknown range endpoints must make that semantic distinction explicit.

Day precision is exact for this primitive. Month, year, decade, range, and
unknown are imprecise. Exact zoned timestamps remain ordinary `datetime`
values outside this calendar primitive.

## Python value and serialization

`timetracker.temporal` owns:

- `TemporalPrecision`, a `StrEnum` with `day`, `month`, `year`, `decade`,
  `range`, and `unknown`;
- an immutable `TemporalValue` whose public construction path accepts only a
  canonical scalar and derives `lower_bound`, `upper_bound`, and `precision`;
- named constructors for day, month, year, decade, range, and unknown values;
- `TemporalValueParseError`, carrying a stable error code and a precise human
  message; and
- `parse_temporal_value()` and `validate_temporal_value()` entry points for
  non-model callers.

The #649/#650 handoff is therefore direct: a non-null legacy release year uses
`TemporalValue.from_year(year)`, while a blank legacy year uses
`TemporalValue.unknown()`. Neither path invents a month or day.

The object cannot be constructed with caller-supplied derived values. This
prevents an expression and its bounds from disagreeing in memory. Its wire/event
serialization is the canonical scalar alone: a string for a known expression
or `null` for unknown. Parsing that scalar recreates the same immutable value,
including precision and bounds. Derived fields are deliberately omitted from
the wire form because accepting them would create a second source of truth.

Validation distinguishes at least invalid input type, non-canonical syntax,
invalid calendar date, invalid/reversed range, unsupported qualifier,
unsupported season, unsupported set, unsupported extended year, and unsupported
timestamp. Range order is possible-time order: when both sides are bounded, the
start endpoint's earliest possible day must not follow the end endpoint's latest
possible day. This admits mixed-precision intervals such as `2020/2020-01`
without pretending either endpoint is more precise than written.

## Django and PostgreSQL persistence

The persistence contract mirrors the existing `UUIDv7Field`/`uuid_v7` domain
boundary:

1. `TemporalValueField` stores only the canonical scalar in a PostgreSQL
   `temporal_value` domain backed by `varchar(64)`. It normalizes values during
   model validation/database preparation and converts database-loaded values to
   `TemporalValue`. It defaults to nullable unknown and is non-editable so an
   automatic `ModelForm` cannot expose the explicitly deferred raw-EDTF
   interface.
2. The domain rejects malformed or unsupported non-null strings even when a
   write bypasses Django. SQL validation covers the same accepted grammar,
   real Gregorian dates, range endpoint rules, and range ordering as Python.
3. Immutable PostgreSQL functions derive lower bound, upper bound, and precision
   from the canonical value. Django `Func` wrappers expose them as
   `TemporalLowerBound`, `TemporalUpperBound`, and `TemporalPrecisionValue`.
4. A consumer declares three persisted `GeneratedField`s with typed
   `DateField`, `DateField`, and `CharField` outputs. Parsing therefore happens
   when a row is written, not whenever it is filtered or sorted. The stored
   columns can receive ordinary B-tree indexes and direct ORM lookups.

The consumer shape is explicit rather than hidden behind a descriptor:

```python
release_date = TemporalValueField()
release_date_lower = models.GeneratedField(
    expression=TemporalLowerBound("release_date"),
    output_field=models.DateField(),
    db_persist=True,
    editable=False,
)
release_date_upper = models.GeneratedField(
    expression=TemporalUpperBound("release_date"),
    output_field=models.DateField(),
    db_persist=True,
    editable=False,
)
release_date_precision = models.GeneratedField(
    expression=TemporalPrecisionValue("release_date"),
    output_field=models.CharField(max_length=7),
    db_persist=True,
    editable=False,
)
```

Explicit fields cost four declarations per temporal fact, but preserve normal
Django migration state, introspection, field naming, and index control. The
primitive defines the values and expressions; each owning domain issue chooses
the semantic prefix and indexes its own query paths.

## Migration and reversibility

Migration `0017_temporal_value_domain` creates the immutable validation and
projection functions, then the `temporal_value` domain. It adds no table or
column and touches no data. Reverse SQL drops the unused domain and functions.
Once #649 adds consuming columns, ordinary dependency order requires those
columns to be reversed before this foundation can be removed.

The migration test reverses to `0016_library_config_uuid_primary_key`, proves
the domain and functions are absent, reapplies `0017`, proves their signatures
and volatility, and restores all graph leaf migrations in `finally`. A fresh
database build is covered by the normal migration and `make check` gates.

## Alternatives considered

**A shared `TemporalValue` table** was rejected. It would give a derived value
an identity and lifecycle, force joins for ordinary bounds queries, require
deduplication/orphan policy, and couple unrelated catalog and player facts.

**A JSONB custom field** was rejected. It is compact at the model declaration,
but date bounds become strings or query-time casts, coherence is difficult to
enforce at the database boundary, and future overlap indexes become opaque
expression indexes rather than ordinary typed columns.

**A magical multi-column descriptor** was rejected. Injecting four fields from
one pseudo-field hides migration state and makes deconstruction, generated-field
dependencies, admin/form behavior, and per-consumer indexes harder to inspect.
The explicit four-column consumer contract is repetitive but unsurprising.

## Verification and complexity forecast

Pure tests cover every supported precision, leap-year/month-end boundaries,
open and mixed-precision ranges, scalar serialization round-trips, constructor
invariants, equality/hash behavior, and every stable validation code. Django
tests cover field deconstruction, PostgreSQL-only enforcement, model/dump-data
round-trips, typed generated values, ORM queries over the stored bounds and
precision, and database rejection of invalid raw inserts. Migration tests cover
domain/function creation, parity between Python and SQL over the shared fixture
matrix, reversibility, and reapplication.

The final gate is `make check` with the Makefile's default parallel workers,
then `git diff --check` and full diff review against this specification.

Forecast: two independent runtime subsystems (Python/Django and PostgreSQL),
four implementation/test files, and 700–1,000 non-generated changed lines.
The issue therefore stays below all re-slice thresholds: it does not cross three
runtime subsystems, 40 files, or 2,000 non-generated lines.
