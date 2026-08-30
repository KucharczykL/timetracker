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

## Every check reads the unqualified token

This is the rule the rest of the parser follows, and it is not optional.

`_reject_unsupported_family()` holds six checks. Five of them are written
against the whole token, and a trailing symbol defeats three of those:

- The decade check (`temporal.py:239-244`) refuses a token that holds `X` unless
  `_DECADE_RE` matches the whole token. `([0-9]{3})X` does not match `198X~`, so
  the check refuses the accept case this issue exists to add.
- The season check (`temporal.py:230`) is a `fullmatch`, so `1984-21~` passes it
  and then fails deeper as `invalid_date` rather than `unsupported_season`.
- The extended-year check (`temporal.py:245-248`) anchors on `$` or `-`, so
  `12345~` passes it and then fails as `invalid_syntax` rather than
  `unsupported_year`.

A new private helper answers the token without its symbol, and every family
check reads that answer instead of the raw token. Each refusal then keeps the
code its unqualified twin already gets.

One new check has no twin: after one trailing symbol is removed, any remaining
`?`, `~`, or `%` anywhere in the token is `invalid_qualifier`. Without it,
`1984??` reaches the atom parser and reports `invalid_syntax`, which does not
tell the writer what is wrong.

## What the grammar refuses

`_reject_unsupported_family()` loses the blanket refusal of `?~%`. These
refusals replace it. Each raises `TemporalValueParseError`.

| Input | Code |
|---|---|
| `?1984`, `1984-?06`, `~1984-06-11` | `unsupported_component_qualifier` |
| `1984?~`, `1984~?`, `1984??`, `1984-06-11~~` | `invalid_qualifier` |
| `~/1986`, `..?/1986`, `1984/%` | `unsupported_endpoint_qualifier` |
| `1984-21~` | `unsupported_season` |
| `12345~`, `0000~` | `unsupported_year` |
| `?`, `~`, `%` | `invalid_syntax` |

A symbol before an atom, or inside one, is EDTF Level 2. The subset excludes
Level 2, as it did before.

Two symbols in one position is an error in EDTF as well: a position holds one
symbol, and `%` is the symbol for both. The sentence for `invalid_qualifier`
names `%`.

An open endpoint and an unknown endpoint hold no date. There is nothing for a
symbol to qualify, so a symbol on either one is an error.

An unknown value is `NULL`. It has no text, therefore no symbol.

`[1984~]`, `{1984~}`, `Y1984~`, `-1984~`, `1984-06-11T00:00~`, and `19X4~` each
keep the code they get today. Those checks read a prefix or a substring, and a
trailing symbol does not reach them.

The new pattern carries `re.ASCII`, as every pattern in the module does.
`tests/test_temporal_domain.py:320-323` feeds Arabic-Indic and full-width
digits, and a pattern without the flag accepts them.

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

A qualified value and its unqualified twin are two different canonical strings.
`fingerprint_command_input()` reads `value.canonical`, so the two fingerprint
apart. They are two different facts, therefore this is correct. The digest reads
the string and not the dataclass, so a new field bumps no
`FINGERPRINT_VERSION`.

## Reading a value apart

A `TemporalValue` is what the application stores and queries. It is not what a
form edits. A form holds independent dimensions — a kind, a precision, some date
parts, a symbol — and the canonical string fuses them into one token.

This issue adds no method that changes a value. It adds the accessors that let a
consumer take one apart without inventing anything:

| Accessor | Answers |
|---|---|
| `year` | the year of a day, month, or year value |
| `month` | the month of a day or month value |
| `day` | the day of a day value |
| `decade_start_year` | the first year of a decade value |

Each answers `None` wherever the precision does not know the part, and on a
range and on an unknown value. `TemporalEndpoint` delegates all four, as it
delegates `precision` now.

The parts are readable from `lower_bound` today, and that is the reason to add
them. `TemporalValue("1984-06").lower_bound` is 1984-06-01, so a caller that
reads `.day` off the bound gets 1 from a value that never knew a day. The
accessors answer `None` there, which is the charter's first principle: never
invent precision.

There is no `with_qualifier()` and no other transformer. A form that wants an
independently editable symbol wants a draft type holding all four dimensions as
fields, and one function that builds a `TemporalValue` from it. That type serves
a form, so #893 owns it, and #893 is the issue that can see the form. These
accessors are what such a draft needs on its first day, and they commit this
issue to none of its shape. #601 deferred #909 and closed #913 on the same
reasoning: a helper promoted from one call site states a convention rather than
removing it.

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

The schema holds twelve functions today. It holds seventeen after.

Every function keeps `SET search_path = pg_catalog, public`. Migration 0034 adds
that setting because `pg_dump` opens a dump with an empty search path, and
without the setting no dump of this schema restores. A new function that omits
it reopens that failure.

### PostgreSQL accepts the replacement

`CREATE OR REPLACE` on `_timetracker_temporal_atom_precision`, `_atom_lower`,
`_atom_upper`, and `timetracker_temporal_is_valid` is accepted while
`games_game` and `games_release` hold sixteen persisted generated columns that
read them, and `ADD COLUMN … GENERATED ALWAYS AS … STORED` over a new function
is accepted on a populated table carrying the domain. Verified against
PostgreSQL 18.6 in a rolled-back transaction: the stored projections were
unchanged across the replacement, and the new columns projected `1984~` to
`approximate`, `1984-06?` to `uncertain`, and `198X%` to `both`.

### Nothing is rebuilt

The domain constraint stays. The sixteen generated columns that exist now stay.

This change widens the grammar. No string the database holds can contain a
symbol: the parser refuses one and the domain enforces the refusal. Every string
that parsed before therefore parses now, to the same bounds, the same kind, and
the same precision, and a parser that removes a trailing symbol first cannot
reinterpret any of them.

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

Each is a persisted generated column, `null=True`, `editable=False`,
`serialize=False`, with a `CharField(max_length=11)` output field. `approximate`
is eleven characters, and `serialize=False` is what keeps a generated column out
of `serializers.serialize`, which `tests/test_catalog_hierarchy.py:348` asserts.

Three `models.Func` wrappers carry the functions into the ORM:
`TemporalQualifierValue`, `TemporalStartQualifier`, and `TemporalEndQualifier`.

All three go into `_TEMPORAL_PROJECTION_EXPRESSIONS` in `common/criteria.py`.
`_maybe_group_for()` reads that tuple to keep a temporal projection out of the
filter field picker. A wrapper missing from it becomes a comparable `CharField`
column that the nested filter builder renders, which is a filter surface this
issue's boundary excludes. `tests/test_catalog_hierarchy.py:353` guards this for
`Game`, `Session`, `Purchase`, `PlayEvent`, and `Platform`; `Release` is absent
from that list and gains a case.

`LibraryEvent.effective_time` gains nothing. It projects no column today. Three
qualifier columns beside no bounds, no kind, and no precision would state a
contract that the other eight columns do not state there.

### The migration reverses

The `RunSQL` carries a `reverse_sql`: it replaces the four function bodies with
their 0017 and 0034 forms and drops the five new functions. The
`AddField` operations reverse themselves.

This is not for a deployment. One database runs this schema, the deployment is
rehearsed with `make verify-dump`, and #599 ends in a squash. It is for the test
suite, which reverses on every run. Six modules call
`MigrationExecutor.migrate()` down to an earlier node, and an irreversible
operation above that node raises `IrreversibleError` in their fixtures:

| Module | Reverses to |
|---|---|
| `tests/test_temporal_domain.py` | `0016` |
| `tests/test_catalog_hierarchy_migration.py` | `0017` |
| `tests/test_playergame_backfill_migration.py` | `0032` |
| `tests/test_catalog_uuid_primary_key.py` | `0012` |
| `tests/test_session_playhistory_uuid_primary_key.py` | `0013` |
| `tests/test_session_fk_uuid.py` | `0010` |

A probe migration carrying one irreversible `RunSQL` turns a green run of those
six modules into thirty-seven failures and errors. `RunSQL.noop` clears the
error and leaves the widened functions behind, which lets
`test_temporal_domain_migration_reverses_and_reapplies` pass for the wrong
reason. Write the real reverse.

## The queries

Two helpers, shaped like the three that `_temporal_component_q()` already
serves, reusing its `TemporalEndpointName` alias:

```python
temporal_is_approximate_q("release_date")
temporal_is_approximate_q("release_date", endpoint="start")
temporal_is_uncertain_q("release_date", endpoint="end")
```

Each answers a `Q` over one column with an `__in` of two words, and each carries
the kind guard its siblings carry, so a negated call does not match a range or
an unknown value:

```python
Q(release_date_kind="atomic") & Q(release_date_qualifier__in=("approximate", "both"))
```

One column holds the symbol, because the canonical text holds one symbol per
position. Two boolean columns would be two functions of that one token, and
every later change to the SQL would have to keep the two agreeing.

The atom-level call does not see a range's endpoints. `{field}_qualifier` is
`NULL` on every range by construction, so `temporal_is_approximate_q("release_date")`
answers false for `1984~/1986~`. A consumer that means "approximate anywhere"
must ask all three columns. This issue states the rule; the wave that writes the
filter owns the operator.

The `NULL` in these columns carries two meanings, as it does in `precision`:
no symbol, and no such slot. The sibling `_kind` column resolves both.
`qualifier IS NULL AND kind = 'atomic'` is an unqualified atom.

## The tests

`tests/test_temporal.py`, `tests/test_temporal_field.py`, and
`tests/test_temporal_domain.py` each refuse a qualifier today. Those cases
become accepting cases, and the refusal table above becomes new cases.

`tests/test_temporal_domain.py` runs eight projection functions against the
Python parser over one table of values. That parity test is what stops the two
halves from drifting. It grows to eleven, and the table grows the qualified
values.

`tests/test_temporal_domain.py:132-137` guards the `search_path` setting, and it
reads a hand-maintained list of names. A function absent from the list is not
checked, and the functional test beside it cannot catch the omission either: it
calls `timetracker_temporal_is_valid`, which carries the setting, and a nested
helper inherits its caller's. The failure appears only where a generated column
calls a public function directly under an empty search path, which is the
`pg_dump` restore that 0034 exists to fix. So a forgotten setting would pass
`make check` and break `make verify-dump`. The guard changes to enumerate
`pg_proc` by name pattern, and a new function can no longer be forgotten.

`tests/test_catalog_hierarchy.py` reads the generated columns on `Game` and
`Release`. It gains the three new columns, and `Release` joins the
comparable-column guard at line 353.

## Boundary

This issue owns the qualifier: its place in the canonical string, its parsed
form, its columns, its query helpers, and its validation. It owns the accessors
that read a value apart.

It adds no entry control and no presentation. It adds no criterion, no filter
dataclass, no quick facet, and no TypeScript. It migrates no legacy fact.
Structured entry and presentation are #893. Filters belong to each consuming
domain wave.

Two facts about the world this issue does not change:

- `save_legacy_game_form()` in `games/catalog_compat.py:20-28` writes both
  temporal fields from the integer year columns on every legacy Game form save,
  through `TemporalValue.from_year()`, which states no symbol. A qualifier
  stored by #893 is erased by the next legacy save. That path is #889's and
  #893's to retire.
- `%` is reserved in a URL query string, so a canonical value such as `198X%`
  cannot ride a `?filter=` parameter unencoded. The wave that writes the filter
  owns the encoding.

## Forecast

`timetracker/temporal.py`, `games/models.py`, `common/criteria.py`, one
migration, and four test files. One runtime subsystem. Inside the re-slice
limits.
