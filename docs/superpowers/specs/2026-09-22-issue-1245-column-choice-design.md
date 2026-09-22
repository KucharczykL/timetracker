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

`ListColumnChoice` holds one row per person per mode, unique on `(user, mode)`.
`mode` states `FilterPreset.MODE_CHOICES`, the seven modes already spelled once,
so a mode the code does not know is refused by the database. `hidden` is a JSON
list of column keys.

The row carries an integer key, so `identity_models()` does not see it: that read
derives its subjects from a `uuid` column or a UUID primary key. It is no
`ProjectionModel`, so no `games.E0xx` check binds it, and it is absent from
`REMOVABLE_MODELS`, because a preference is not a record a person removes.

`games/list_columns.py` is the one reader and the one writer. It reads the row
itself and never through `timetracker/settings_resolver.py`, which caches the
whole `UserPreferences` table for `SITE_SETTINGS_TTL_SECONDS` and whose
`clear_cache()` has test callers alone. A choice read through that snapshot would
leave a column on screen for five seconds after a person turned it off.

The choice is the person's, not the library's. `FilterPreset` is keyed on the
library and this row on the user. The two are one today, and which columns a
person sees stays theirs if a library is ever shared.

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
header is computed per request, and reads `Playtime` or `Playtime (matching)`
depending on the filter.

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

The selection checkbox is not a column and the row menu is not a column. Neither
reaches the picker.

## Where the drop happens

`narrow_columns(data, hidden)` answers a `TableData` without the hidden columns,
and without the cell at each hidden column's index in every row. The seven views
call it. `paginated_table_content` knows nothing about it.

`games/views/playthrough_rows.py` and `games/views/historical_playtime.py` each
write that index walk by hand today, under `exclude_columns`. One function
replaces both walks.

## The two exclusions are different things

`exclude_columns` stays, and Game detail is its one caller. The Game column on a
game's own page prints one value in every row: the page's identity, not a
judgement about interest. Game detail's sections state no mode, host no quick bar
and hold no paginator, so they carry no picker and need no key.

`sole_game` is the other kind and does not survive. It reads the one game the
filtered rows name and decides the Playthrough column on the list's behalf.

## The control

A `<drop-down>` beside Load preset holds one checkbox for each hideable column,
checked where the column shows, and Apply beside Reset to defaults. The panel's
form is a plain `<form method="post">`: with the panel open, the submit is
ordinary HTML and reads no script. The route is POST only, carries `?origin=`,
and is `ORIGIN_AWARE` in `games/views/returns.py`.

An unchecked box posts nothing, so the saved value is the declared keys less the
posted keys, computed from the live column list at each save. A key a rename
orphaned is gone after the next save.

With no scripting the panel does not open. The server still renders the person's
stored columns, because it reads them before it renders. A person with no
scripting reads their choice and does not state a new one, which is the cost the
selection line already accepts on the same page, on a bar whose own Apply reads a
script as well.

## The session list

Playthrough is declared always, at priority 3 after Name, and is on by default.
The mixed list gains a column it did not have.

`every_run_label` is the one reader of a run's name, and now reads on each load of
the list rather than on the narrowed load alone. It reads the page's rows, so the
page size bounds it. `ambiguous_run_labels` goes with `sole_game`.

A person who turns the column off is named no run anywhere: not beside the name,
and not in the stacked summary below `md`. A column that moves its content into
another column when hidden is the same judgement this issue removes, wearing
other clothes.

## What does not change

`<responsive-table>` drops for width among the columns that are left.
`MAX_DATA_TABLE_COLUMNS` counts what renders.

A hidden column still orders the list where the URL names it in the sort, and
still filters it where the quick bar names it in a facet. What a person shows and
what a person asks of the rows are two questions.

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
