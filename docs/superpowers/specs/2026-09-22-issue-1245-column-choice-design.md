# A person chooses which columns a list shows

Three mechanisms decide what a list shows today, and none of them is the person:
`<responsive-table>` drops what does not fit, a view hides a column whose content
it judges meaningless, and the rest is fixed in the view's source. This issue
adds the person, and removes the second mechanism.

The control is one more piece of furniture on the quick filter bar's row, beside
Load preset and the Apply group, on the seven list views that state a `*_SORTS`
map and a filter mode: games, sessions, purchases, playthroughs, historical
playtime, devices and platforms.

## Where the choice lives

`ListColumnChoice` holds one row per person per mode, unique on `(user, mode)`,
with a `UUIDv7Field` key. `mode` names `FilterPreset.MODE_CHOICES`, the seven
modes already spelled once. `hidden` is a JSON list of column keys.

The choice is the person's. `FilterPreset` is keyed on the library because a
saved filter describes the rows; which columns a person reads those rows with is
theirs, and stays theirs if a library is ever shared.

A key on `auth.User` is a bigint, so the row states two inventory lines: its
`user_id` in `RESIDUAL_INTEGER_RELATIONS` under `NEVER_CONVERTS`, beside
`games_userpreferences.user_id`, which is the same fact about the same table;
and the column in `EXPECTED_RELATION_COLUMNS`, which every new foreign key
states. The `UUIDv7Field` key keeps the row out of
`RESIDUAL_INTEGER_PRIMARY_KEYS` and out of its pinned twin.

`choices` names the vocabulary for a form and for the admin. It is not a database
refusal: Django reads it in `full_clean()` and not in `save()`. The one writer is
this issue's own module, which refuses a mode it does not know.

`games/list_columns.py` is the one reader and the one writer. The row is read
directly, not through the settings registry, which refuses a user-scoped setting
that declares no widget: a per-mode map of column keys has no text, select or
model control and does not belong on the settings page. Per-mode structured data
also wants a row it can be read, written and removed by, which an untyped bag
does not give.

Nothing here is a command and nothing appends an event. The choice names no
aggregate and no replay reproduces it.

## The default is the declared list

A list's default is every column it declares, which is what it renders today.
There is no per-column default flag.

The store holds what the person turned off. A column added later is absent from
every stored list and appears for everybody, which is the rule each reference
states: a column is hidden only where its key is present.

A key no column claims any more hides nothing. The reader ignores it.

Reset to defaults removes the row. An absent row and an empty list read the same,
and the row a person reset holds nothing worth keeping.

## A column's identity

`Column` states a `key`. A label is not an identity: the game list's playtime
header is computed per request and reads `Playtime`, `Playtime (matching)` or
`Playtime (matching sessions)` depending on the filter.

```python
type ColumnKey = str  # the picker's identity for a column, e.g. "playthrough"
```

Each of the seven lists states a key on every column. A test holds that, and
holds the keys of one list distinct.

## Which columns refuse to hide

`Column.hideable` is true by default and false for two kinds:

- the first column, which is the `<th scope="row">` that names every row and is
  pinned above `md`. `<responsive-table>` never drops it, nor the highest-priority
  column beside it, so a table never reads as names alone;
- the Actions column of the games, purchases, devices and platforms lists, which
  carries every act on the row.

Two kinds refuse, so a person who unchecks every box is left a table that still
names its rows and still acts on them. The floor needs no rule of its own.

The panel lists a refusing column with its box checked and disabled, rather than
leaving it out. The list is then the whole table, and a person reads that Name is
pinned instead of wondering whether the panel forgot it.

The selection checkbox is not a column and the row menu is not a column. Neither
reaches the picker.

## Narrowing is a parameter, not a filter

A function over a finished `TableData` cannot do this. `exclude_columns` drops
columns and cells today, and it also decides what the stacked line below `md`
says: `playthrough_rows.py` reads `with_game` from it, `historical_playtime.py`
reads `with_when` from it and swaps between two different summaries, and
`session_row_data` builds its summary from `run_name` inside itself. A pass over
the output would drop the Playthrough cell and leave the run named in the
summary, which is the one thing this design forbids.

So the hidden set is a parameter each builder takes, beside the rows. A shared
helper does the mechanical half — drop each hidden column and the cell at its
index in every row, the walk `playthrough_rows.py` and `historical_playtime.py`
each write by hand today — and each builder reads the same set for its summary.

`exclude_columns` is that parameter. It is not replaced and not kept beside the
new one: it is generalised, re-keyed from labels to `ColumnKey`, and states both
what a page excludes and what a person hid. Game detail passes its own
exclusions, the seven lists pass the person's, and one vocabulary serves both.

Two rules bind the helper: column and cell drop in lockstep, and column 0 is
never dropped, because it must stay `shrinkable` while any row carries a summary.
`StyledTable` raises on either under `DEBUG` and renders a ragged table in
production, so a test holds them rather than the guard alone. The menu slot sits
outside `columns` and is counted on neither side.

## The control

A `<drop-down>` beside Load preset holds one checkbox for each hideable column,
checked where the column shows, and Apply beside Reset to defaults.

The form is **not** inside the panel. The quick bar wraps every row child in one
`<form>`, and a nested `<form>` start tag is dropped by the HTML parser, so a
form written there would not exist and its controls would be owned by the bar,
whose submit is turned into a navigation by `ts/elements/quick-filter-bar.ts`.
Instead the real `<form id="column-picker" method="post">` renders as a sibling
of the bar's form, and each checkbox and the submit button state
`form="column-picker"`. The controls are then owned by the picker, and the submit
is ordinary HTML that reads no script.

The route is POST only, carries `?origin=`, and is `ORIGIN_AWARE` in
`games/views/returns.py`.

The picker renders in both of the bar's branches. `QuickFilterBar` answers
`_degraded()` for any filter its facets cannot state — an operator key, a
relation, a field comparison — and a picker written into the editable branch
alone would disappear under exactly the filters a person builds deliberately.

An unchecked box posts nothing, so the saved value is the declared keys less the
posted keys, computed from the live column list at each save. A hidden column's
box renders unchecked and stays hidden; a key a rename orphaned is gone after the
next save.

With no scripting the panel does not open. The server still renders the person's
stored columns, because it reads them before it renders.

## The session list

Playthrough is declared always, at priority 3 after Name, and is on by default.
The mixed list gains a column it did not have.

`sole_game` goes, and `ambiguous_run_labels` with it. `every_run_label` is the
list's one reader of a run's name; `games/bulk_move.py` reads it as well, for the
Move act's own rows, and that reader does not change.

A person who turns the column off is named no run anywhere: not beside the name,
and not in the stacked summary below `md`. Two sessions at one game on one day,
on different runs, then read alike. That is the cost of the rule, and the rule is
that a column which moves its content into another column when hidden is the same
judgement this issue removes, wearing other clothes.

The narrowed list is no longer a different table from the mixed one, so the
labels cost the same on both. `_labelled_runs` already reads on every load,
through whichever branch the view took.

## Tests that change

- `tests/test_session_list.py` — `test_a_list_naming_two_games_keeps_the_name_cells_label`
  asserts a mixed list shows name-cell labels and no Playthrough column. Both
  halves stop being true. `_run_column` becomes unconditional.
- `tests/test_uuid_identity_audit.py` — one line in `EXPECTED_RELATION_COLUMNS`.
- `tests/test_player_session_reads.py` — the `sole_game` tests go with the read.
- `tests/test_session_run_labels.py` — the `ambiguous_run_labels` tests go with
  the reader.
- `e2e/test_session_list_mobile_e2e.py` still passes and now describes a column
  that is always declared rather than one the view chose to add.

## What does not change

`<responsive-table>` drops for width among the columns that are left.
`MAX_DATA_TABLE_COLUMNS` counts what renders, the menu slot included.

A hidden column still orders the list where the URL names it in the sort, and
still filters it where the quick bar names it in a facet. What a person shows and
what a person asks of the rows are two questions. A sort on a hidden column
therefore orders by a criterion with no header to un-sort it from, which
`warn_unknown_sort` does not warn about, because the sort key is known.

`<selectable-table>` keys its storage on the scope and the path and fills its
checkbox into `th[scope="row"]`, and `data-selection-key` rides the `<tr>`.
None of that moves when a column goes.

## What this leaves

`FilterPreset.ui_options` is a field that no application code reads or writes;
one test writes one. A preset carries no columns, and loading a preset changes
which rows show and nothing else.
[#1261](https://github.com/KucharczykL/timetracker/issues/1261) holds the preset
that carries its own.

[#1262](https://github.com/KucharczykL/timetracker/issues/1262) holds the choice
a person states with no scripting. The bar this picker joins reads a script to
apply anything at all, which makes the bar that issue's real subject.

Reordering columns, per-column width and print styles stay outside, as
[#521](https://github.com/KucharczykL/timetracker/issues/521) holds them.
