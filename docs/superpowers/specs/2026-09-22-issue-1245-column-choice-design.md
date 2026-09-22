# The columns a list shows

A person selects the columns of seven lists: games, sessions, purchases,
playthroughs, historical playtime, devices and platforms. The control is an icon
in the header row of the table, not on the quick filter bar. The bar selects
rows. A column choice is not in `?filter=`, no preset keeps it, and it changes no
result set.

## The store

`ListColumnChoice` keeps one row for each person and each mode. `shown` is a map
from column key to a boolean, and holds only the keys that differ from the
default of the column. `games/list_columns.py` is the only reader and writer.

The choice is the property of the person. A saved filter selects rows and is the
property of the library.

## The default

Each column declares where it starts. `Column.hidden_by_default` starts a column
in the off state: the created timestamp on all seven lists, Wikidata on games,
Infinite and Refunded on purchases, References on platforms.

A key that is absent from the map reads the default of its column. Thus a new
column starts in the state that it declares. A choice equal to the defaults
removes the row, and Reset also removes it.

No row is written until a person makes a selection. A row written at the creation
of the person is a copy of the declaration that becomes incorrect: a column added
later could carry no default, and each person who exists would need a data
migration.

## The columns

`Column.key` is the identity of a column. A label is not an identity: the
playtime header of the game list has three possible labels.

`Column.hideable` is false for the first column, which names each row, and for
the Actions column, which holds the operations on the row. A column that refuses
to hide cannot start hidden.

`drop_columns` removes a named column and its cell in each row. It does not read
`hideable`, because a page can state exclusions that a person cannot: Game detail
removes the Name column that the list keeps. The view reads `hideable` and
reduces the set of the person first. One parameter carries both sets, and the two
row builders read it also for the summary line below `md`. A table that removes a
cell must not keep the same data in the summary.

## The control

`IconTrigger` is the button, in the last header cell: the row-menu cell, or the
Actions header. The row menu uses the same shape.

The panel is a `<drop-down behavior="column-picker">` on the shared dropdown
surface. That surface opens with `position: fixed`, because the shell of the
table clips its content, and it sets the layer. A panel with no layer opens below
the device selector of each row.

The panel holds a `<form method="post">`, one checkbox for each column, Apply and
Reset. A column that refuses to hide shows a checked and disabled box. A box that
is not checked sends nothing, thus the route reads the sent keys as the full set
of shown columns, and a pinned column stays shown. Reset is a named submit
button, read before the boxes.

The route accepts POST at `lists/<mode>/columns/` and is `ORIGIN_AWARE`. Without
scripts the panel does not open, but the server sends the columns of the person.

## Related behavior

The Playthrough column of the session list is always declared. A person who hides
it sees no run name, also not in the summary. `<responsive-table>` removes
columns for width from the columns that stay. A hidden column keeps its sort key
and its filter facet. The purchase refund route sends one row from outside the
list and reads the same choice.

## Not in this work

[#1261](https://github.com/KucharczykL/timetracker/issues/1261) a preset with its
own columns, [#1262](https://github.com/KucharczykL/timetracker/issues/1262) the
choice without scripts,
[#521](https://github.com/KucharczykL/timetracker/issues/521) column order, width
and print styles, and
[#1267](https://github.com/KucharczykL/timetracker/issues/1267) the group of
controls on the quick filter bar.
