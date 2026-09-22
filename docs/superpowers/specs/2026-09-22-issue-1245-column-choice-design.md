# The columns a list shows

A person selects the columns of seven lists. The control is an icon in the header
row, not on the quick filter bar: the bar selects rows. No preset keeps a column
choice.

## The store

`ListColumnChoice` keeps one row for each person and mode. `shown` maps column
key to a boolean, and holds only the keys that differ from the default.
`games/list_columns.py` is the only reader and writer. The choice is the property
of the person; a filter selects rows and is the property of the library.

## The default

`Column.hidden_by_default` starts a column off: the created timestamp on all
seven lists, Wikidata on games, Infinite and Refunded on purchases, References on
platforms.

A key that is absent reads its column's default, thus a new column starts where
it declares. A choice equal to the defaults removes the row, and Reset removes
it.

No row is written until a person makes a selection. A row written when a person
is created becomes incorrect: a column added later carries no default, and each
person needs a migration.

## The columns

`Column.key` is the identity of a column. A label is not: the playtime header has
three possible labels.

`Column.hideable` is false for the first column, which names each row, and for
the Actions column. Neither can start off.

`drop_columns` removes a named column and its cell in each row. It does not read
`hideable`: a page can exclude a column that a person cannot, and Game detail
removes the Name column that the list keeps. The view reads `hideable` first. One
parameter carries both sets, and the row builders read it also for the summary
below `md`, which must not keep a removed cell's data.

## The control

`IconTrigger` is the button, in the shape the row menu uses, in the last header
cell: the row-menu cell, or the Actions header. The panel is a `<drop-down
behavior="column-picker">` on the shared dropdown surface, which opens
`position: fixed` because the shell of the table clips, and which sets the layer.
A panel with no layer opens below the device selector of each row.

The panel holds a `<form method="post">`, one checkbox for each column, Apply and
Reset. A column that refuses to hide shows a checked and disabled box. An
unchecked box sends nothing, thus the sent keys are the full set of shown
columns, and a pinned column stays shown. Reset is a named submit button, read
before the boxes. The route accepts POST at `lists/<mode>/columns/` and is
`ORIGIN_AWARE`. Without scripts the panel does not open, but the server still
sends the person's columns.

The Playthrough column of the session list is always declared. No page decides if
a run is important, and a person who hides it sees no run name.

## Not in this work

A preset with its own columns
([#1261](https://github.com/KucharczykL/timetracker/issues/1261)), the choice
without scripts
([#1262](https://github.com/KucharczykL/timetracker/issues/1262)), column order
and width ([#521](https://github.com/KucharczykL/timetracker/issues/521)), and
the controls of the quick filter bar
([#1267](https://github.com/KucharczykL/timetracker/issues/1267)).
