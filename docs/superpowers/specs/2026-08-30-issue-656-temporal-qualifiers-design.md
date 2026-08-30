# Approximate and uncertain temporal qualifiers

A qualifier says how sure the player is of a date. It does not say which dates
the value covers.

`1984` covers 1984-01-01 through 1984-12-31. `1984~` covers the same days with
the same year precision. The qualifier is a separate fact beside the bounds, and
it never moves them. A reader that wants a wider interval must ask for one.

Issue #656 adds the qualifier to the temporal primitive that #655 delivered in
`timetracker/temporal.py` and `games/migrations/0017_temporal_value_domain.py`.
Issue #893 is the first consumer.

## The grammar

An atom is a day, a month, a year, or a decade. One qualifier symbol may follow
an atom. Nothing else takes a symbol.

```
atom      = YYYY-MM-DD | YYYY-MM | YYYY | NNNX
qualified = atom [ "?" | "~" | "%" ]
endpoint  = qualified | "" | ".."
value     = qualified | endpoint "/" endpoint | NULL
```

`?` is uncertain. `~` is approximate. `%` is both.

| Value | Reads as |
|---|---|
| `1984-06-11~` | approximate day |
| `1984-06?` | uncertain month |
| `1984%` | uncertain and approximate year |
| `198X~` | approximate decade |
| `1984~/1986~` | both endpoints approximate |
| `1984/1986~` | exact start, approximate end |
| `1984?/..` | uncertain start, open end |

A decade takes a symbol. The EDTF Level 1 grammar lists an unspecified-digit
date and a qualified date as two alternatives, and it does not join them, so
`198X~` is outside a strict reading. The charter names "2000s, approximate" as
a worked filter example, and python-edtf writes `186X~` for "ca. 1860s". The
subset therefore accepts it. This is the one deliberate step outside Level 1.

## What the grammar refuses

`_reject_unsupported_family()` loses the blanket refusal of `?~%`. Four precise
refusals replace it. Each raises `TemporalValueParseError` with its own code.

| Input | Code |
|---|---|
| `?1984`, `1984-?06`, `~1984-06-11` | `unsupported_component_qualifier` |
| `1984?~`, `1984~?`, `1984??` | `invalid_qualifier` |
| `~/1986`, `..?/1986`, `1984/%` | `unsupported_endpoint_qualifier` |
| `?`, `%` | `invalid_syntax` |

A symbol before an atom, or inside one, is EDTF Level 2. The subset excludes
Level 2, as it did before.

Two symbols in one position is an error in EDTF as well: a position holds one
symbol, and `%` is the symbol for both. The sentence for `invalid_qualifier`
names `%`.

An open endpoint and an unknown endpoint hold no date. There is nothing for a
symbol to qualify, so a symbol on either one is an error.

An unknown value is `NULL`. It has no text, therefore no symbol.

## The Python value

```python
class TemporalQualifier(StrEnum):
    UNCERTAIN = "uncertain"
    APPROXIMATE = "approximate"
    BOTH = "both"
```

`TemporalValue` gains one field and two properties.

- `qualifier: TemporalQualifier | None` is the atom's symbol. It is `None` on a
  range and on an unknown value, as `precision` already is.
- `is_uncertain` is true for `UNCERTAIN` and for `BOTH`.
- `is_approximate` is true for `APPROXIMATE` and for `BOTH`.

`from_day()`, `from_month()`, `from_year()`, and `from_decade()` each take a
`qualifier` keyword. The default is `None`.

```python
value = TemporalValue.from_year(1984, qualifier=TemporalQualifier.APPROXIMATE)
assert value.canonical == "1984~"
assert value.precision is TemporalPrecision.YEAR
assert value.lower_bound == date(1984, 1, 1)
assert value.upper_bound == date(1984, 12, 31)
assert value.is_approximate
```

`range()` takes no new parameter. A known endpoint already holds a
`TemporalValue`, and that value carries its own symbol.

```python
approximate = TemporalQualifier.APPROXIMATE
start = TemporalEndpoint.known(TemporalValue.from_year(1984, qualifier=approximate))
end = TemporalEndpoint.known(TemporalValue.from_year(1986, qualifier=approximate))
assert TemporalValue.range(start=start, end=end).canonical == "1984~/1986~"
```

`TemporalEndpoint` gains a `qualifier` property that reads its value, beside the
`precision` property that reads it now. `TemporalEndpoint.unknown()` and
`TemporalEndpoint.open()` hold no value, so both answer `None`.

There is no `value.qualified(symbol)` method. On a range such a call cannot say
which endpoint it means, and a second way to write one string is a way for two
call sites to write two strings.

A qualified value and its unqualified twin are two different canonical strings.
`fingerprint_command_input()` reads `value.canonical`, so the two fingerprint
apart. They are two different facts, therefore this is correct.

## The database

Migration `0038_temporal_qualifiers` writes the SQL and adds the columns.

Two new private functions:

- `_timetracker_temporal_atom_qualifier(text)` answers `uncertain`,
  `approximate`, `both`, or `NULL`, and raises on a malformed symbol.
- `_timetracker_temporal_atom_unqualified(text)` answers the atom without its
  symbol.

Three new public functions: `timetracker_temporal_qualifier(text)`,
`timetracker_temporal_start_qualifier(text)`, and
`timetracker_temporal_end_qualifier(text)`.

Four functions are replaced. `_timetracker_temporal_atom_precision`,
`_timetracker_temporal_atom_lower`, and `_timetracker_temporal_atom_upper` each
remove the symbol before they read the atom. `timetracker_temporal_is_valid`
performs the three new functions as well.

Every function keeps `SET search_path = pg_catalog, public`. Migration 0034 adds
that setting because `pg_dump` opens a dump with an empty search path, and
without the setting no dump of this schema restores. A new function that omits
it reopens that failure.

### Nothing is rebuilt

The domain constraint stays. The sixteen generated columns that exist now stay.

This change widens the grammar. Every string that parsed before parses now, to
the same bounds, the same kind, and the same precision. The stored values are
therefore still valid, and the stored projections still hold the answers these
functions still give.

Migration 0017 warns that a later migration which changes these functions must
drop and re-add the domain constraint and rebuild the generated columns. That
warning covers a change of verdict. A widening changes no verdict on any string
the database holds. Migration 0034 made the same argument for the same shape of
change.

### The new columns

Three columns for each temporal field that already carries projections:

| Model | Field | Columns |
|---|---|---|
| `Game` | `original_release_date` | `_qualifier`, `_start_qualifier`, `_end_qualifier` |
| `Release` | `release_date` | `_qualifier`, `_start_qualifier`, `_end_qualifier` |

Each is a persisted generated column, `null=True`, `editable=False`, with a
`CharField(max_length=11)` output field. `approximate` is eleven characters.

Three `models.Func` wrappers carry the functions into the ORM:
`TemporalQualifierValue`, `TemporalStartQualifier`, and `TemporalEndQualifier`.

`LibraryEvent.effective_time` gains nothing. It projects no column today. Three
qualifier columns beside no bounds, no kind, and no precision would state a
contract that the other eight columns do not state there.

### The migration is one way

The `RunSQL` carries no `reverse_sql`. A downgrade fails and says so.

A reverse would drop the columns and restore the old function bodies. It would
not re-check the domain, so a qualified row would stay, and the Python parser
would raise on the next read of it. A guard against that costs code for a path
nobody takes: one database runs this schema, the deployment is rehearsed with
`make verify-dump`, and #599 ends in a squash.

## The queries

Two helpers, shaped like the three that `_temporal_component_q()` already
serves:

```python
temporal_is_approximate_q("release_date")
temporal_is_approximate_q("release_date", endpoint="start")
temporal_is_uncertain_q("release_date", endpoint="end")
```

Each answers a `Q` over one column with an `__in` of two words:

```python
Q(release_date_start_qualifier__in=("approximate", "both"))
```

One column holds the symbol, because the canonical text holds one symbol per
position. Two boolean columns would be two functions of that one token, and
every later change to the SQL would have to keep the two agreeing.

## The tests

`tests/test_temporal.py`, `tests/test_temporal_field.py`, and
`tests/test_temporal_domain.py` each refuse a qualifier today. Those cases
become accepting cases, and the two refusal tables above become new cases.

`tests/test_temporal_domain.py` runs the eight public functions against the
Python parser over one table of values. That parity test is what stops the two
halves from drifting. It grows to eleven functions, and the table grows the
qualified values.

`tests/test_catalog_hierarchy.py` reads the generated columns on `Game` and
`Release`. It gains the three new columns.

## Boundary

This issue owns the qualifier: its place in the canonical string, its parsed
form, its columns, its query helpers, and its validation.

It adds no entry control and no presentation. It adds no criterion, no filter
dataclass, no quick facet, and no TypeScript. It migrates no legacy fact.
Structured entry and presentation are #893. Filters belong to each consuming
domain wave. This is the boundary the issue states.

## Forecast

`timetracker/temporal.py`, `games/models.py`, one migration, and four test
files. One runtime subsystem. Inside the re-slice limits.

## The open risk

PostgreSQL must accept `CREATE OR REPLACE FUNCTION` on
`_timetracker_temporal_atom_precision` while a persisted generated column reads
it through `timetracker_temporal_precision`. Migration 0034 replaced
`timetracker_temporal_is_valid`, which the domain constraint reads, so the
pattern has precedent one level up. The first implementation step verifies the
private helper against a real database.

If PostgreSQL refuses, the migration drops the sixteen generated columns,
replaces the functions, and adds all twenty-two back. The tables are small and
the result is the same. Only the migration's length changes.
