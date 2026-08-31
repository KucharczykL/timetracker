# A date at the precision it is known

A release date is not always a day. It can be a year, a month, a decade, a
range, or a year somebody is not sure of. One column holds all of it:
`TemporalValueField` in `timetracker/temporal.py`, a PostgreSQL `temporal_value`
domain over text, checked in the database by `timetracker_temporal_is_valid`.

This page states the grammar, where a value is refused, the one rule that keeps
a stored value safe, the wire a form posts it on, what works with no script, and
what a page must thread to host the control.

## The grammar

A stored value is one canonical string, a subset of EDTF:

| What it says | Written | Read as |
|---|---|---|
| A day | `1984-06-22` | 22 June 1984 |
| A month | `1984-06` | June 1984 |
| A year | `1984` | 1984 |
| A decade | `198X` | the 1980s |
| A range | `1984/1986` | 1984 to 1986 |
| An open start | `../1986` | up to 1986 |
| An unknown end | `1984/` | from 1984 |
| Approximate | `1984~` | about 1984 |
| Uncertain | `1984?` | 1984, perhaps |
| Both | `1984%` | about 1984, perhaps |

A range carries its own precision and its own qualifier at each end, because the
ends are two facts. `1984-06/1986` is a month and a year, and `1984/1986~` says
nothing about the start. A save never spreads one end's qualifier onto the
other.

`TemporalPrecision`, `TemporalValueKind`, `TemporalEndpointKind` and
`TemporalQualifier` are the four words the code uses for this, and
`TemporalValue.from_year`, `.from_month`, `.from_day` and `.from_decade` build
the common ones.

## Where a value is refused

`parse_temporal_value()` raises `TemporalValueParseError`, which carries a
`code`: `invalid_syntax`, `invalid_date`, `invalid_range`, `invalid_year`,
`incomplete_day`, `incomplete_month`, `decade_with_year`, `invalid_kind` and the
rest live at their raise sites. The model field turns each one into a Django
`ValidationError` with the same code, so a form shows the sentence and the
column never takes a string the database would refuse.

A refused draft re-renders the characters a person typed.
`TemporalWidget.value_from_datadict` returns the raw posted text rather than a
parsed draft, so a day nobody can parse comes back as itself, next to the
sentence that says why.

## Precision goes one way

A form never widens a stored value. If the column holds `1984-06-22` and the
control can only say a year, the day stays.

This is the rule that killed the reconciliation the legacy Game form used to
carry. That code compared the posted year against the persisted integer column
and guessed which one to believe. The reliable answer is to give the form the
same grammar as the column, which `TemporalField()` does, and to let the flat
integer columns follow the graph rather than argue with it. See
[Catalog](catalog.md) for the mirror that replaced it.

## The wire

One field name yields several inputs. `temporal_input_name(name, key)` builds
each name from `TEMPORAL_INPUT_SUFFIXES`:

```text
temporal_input_name("release_date", "start_year")  # "release_date-year"
temporal_input_name("release_date", "kind")        # "release_date-kind"
```

The keys are `kind`, then `start_year`, `start_month`, `start_day`,
`start_decade`, `start_approximate`, `start_uncertain`, and the same six again
with `end_`. `kind` states the shape and is not optional: an empty `kind` reads
as unknown, and the form asks a person to pick a shape or clear the date.

`TemporalDraftData` is the posted text, `TemporalDraft` is what that text says,
and `temporal_draft_from_data()` turns one into the other. `TemporalWidget` in
`games/forms.py` reads it back.

Two temporal fields on one page must carry distinct field names, because the
names are derived from them. The Add Game form has two: `original_release_date`
for the work, and `release_date` for the one Release it states inline.

## With no script

The whole value round-trips with scripting off. The control is a shape select,
then four number inputs and two checkboxes per endpoint. The server rebuilds the
value from what they post.

`<temporal-field>` (`ts/elements/temporal-field.ts`) only enhances. It hides the
number inputs and shows a segmented date, offers a whole-decade box and an
open-start box, gives the end a three-way shape radio group, and folds the
second endpoint behind a disclosure. Nothing it does is needed to save a value,
and the precision is never picked from a menu — it is derived from which parts a
person filled.

The element uses `Temporal`, which arrives in Node 26. On an older runtime the
formatters return null and the vitest assertions fail; see the environment notes
in `CLAUDE.md`.

## Hosting one

A widget renders to text, so the node tree ends at the widget and the element's
`Media` never reaches `collect_media()`. The hosting view threads the script
itself:

```text
scripts=ModuleScript("dist/elements/temporal-field.js")
```

Two views do: `games/views/game.py` (Add and Edit Game) and
`games/views/catalog.py` (Add and Edit Release).

## Storage notes

The domain and its helper functions are created by migration, and the functions
carry their own `search_path` since `0034_temporal_functions_search_path`. A
dump taken before that migration needs three-part restore; the commands are in
[Deployment](deployment.md#dumps-taken-before-migration-0034).

`TemporalLowerBound`, `TemporalUpperBound`, `TemporalKind` and
`TemporalPrecisionValue` are the database functions a query sorts and filters
on, so a range and a day compare without a Python round trip.
