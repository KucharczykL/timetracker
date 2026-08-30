# Approximate and uncertain temporal qualifiers

A qualifier says how sure the writer is of a date. It does not say which days
the value covers. `1984~` covers the days of `1984`, at the precision of `1984`.
A reader that wants a wider interval must ask for one.

The code is in `timetracker/temporal.py`, `games/models.py`,
`common/criteria.py`, and `games/migrations/0038_temporal_qualifiers.py`.

## The grammar

One symbol can follow an atom. An atom is a day, a month, a year, or a decade.

```
atom      = YYYY-MM-DD | YYYY-MM | YYYY | NNNX
qualified = atom [ "?" | "~" | "%" ]
endpoint  = qualified | "" | ".."
value     = qualified | endpoint "/" endpoint | NULL
```

`?` is uncertain. `~` is approximate. `%` is both. A position holds one symbol,
thus `?~` is an error.

A decade takes a symbol. EDTF Level 1 lists an unspecified-digit date and a
qualified date as two alternatives, and it does not join them. `198X~` is one
deliberate step outside Level 1.

A symbol before an atom, or inside an atom, is Level 2. The subset refuses
Level 2. An open endpoint and an unknown endpoint hold no date, thus a symbol on
either one is an error. An unknown value is `NULL` and has no text.

## Every check reads the unqualified token

`_split_qualifier()` removes the trailing symbol. Each family check in
`_reject_unsupported_family()` reads the result. A refusal then keeps the code
its unqualified twin gets: `1984-21~` is `unsupported_season`, and `12345~` is
`unsupported_year`.

One check has no twin. A symbol that stays after one removal is
`invalid_qualifier`.

## The Python value

`TemporalQualifier` holds `UNCERTAIN`, `APPROXIMATE`, and `BOTH`.
`TemporalValue` holds a `qualifier` field, and `is_uncertain` and
`is_approximate` properties. The four constructors take a `qualifier` keyword.
`TemporalEndpoint` delegates to its value.

`TemporalValue` also answers `year`, `month`, `day`, and `decade_start_year`.
Each answers `None` where the precision knows no such part. Do not read a part
off `lower_bound`: `1984-06` has a lower bound of 1984-06-01, and it knows no
day.

## The database

Migration 0038 adds five functions and replaces four. Every function keeps
`SET search_path = pg_catalog, public`, because `pg_dump` opens a dump with an
empty search path.

The change widens the grammar. No stored string carries a symbol, thus every
stored value keeps its verdict, its bounds, and its precision. The domain
constraint stays, and the generated columns are not rebuilt.

`Game.original_release_date` and `Release.release_date` each get three persisted
generated columns: `_qualifier`, `_start_qualifier`, and `_end_qualifier`. The
three `models.Func` wrappers go in `_TEMPORAL_PROJECTION_EXPRESSIONS`, which
keeps a temporal projection out of the filter field picker.

## The queries

`temporal_is_approximate_q()` and `temporal_is_uncertain_q()` each read one
column with an `__in` of two words, behind the kind guard their precision
siblings carry. `endpoint="start"` and `endpoint="end"` read an endpoint column.

`{field}_qualifier` is `NULL` on every range. A consumer that means "approximate
anywhere" must ask all three columns.

## Boundary

This subset owns the qualifier and the accessors. It adds no entry control, no
presentation, and no filter. Issue #893 owns structured entry.

`save_legacy_game_form()` writes both temporal fields from the integer year
columns, at no qualifier. A legacy save thus clears a qualifier.

`%` is reserved in a URL query string. The wave that writes the filter owns the
encoding.
