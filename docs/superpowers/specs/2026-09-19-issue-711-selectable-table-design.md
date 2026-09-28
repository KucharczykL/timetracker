# A selectable table

`<selectable-table>` is the personality `StyledTable` gains to act on many
rows at once. It holds `<responsive-table>`, which keeps the column drop. The
wave is [Selectable tables](2026-09-19-selectable-tables-wave-design.md).

## Always shown

Selection is not a mode. Each row shows a checkbox at all times. The element
makes the row checkboxes when it connects. A page with no scripting shows no
checkbox, and the line stays hidden. Escape clears the selection. An overlay
that closes on that Escape keeps it, because each marks such a press spent.
The table reads that mark in the task after the press, because an overlay
may answer before this table or after it.

## The checkbox

The checkbox leads the row the identity cell states for the name, and that
cell stays a `<th scope="row">` and keeps its pin above `md`. The row is
what the box centres on: the cell also holds the summary under the name
below `md`, so a box placed in the cell would centre on both lines and sit
below the name it marks. A cell that states no such row takes the box
itself. It is not a column: the drop
classes and `MAX_DATA_TABLE_COLUMNS` count as before. It carries the row name
and a touch target. The name floor below `md` budgets its 32px.

The first header cell holds the page's check-all, in the same column. It
takes `py-2`, so the header row keeps its height. It stands outside the sort
link, and it is hidden while the element is undefined.

Only the checkbox selects, because the row holds links and immediate
controls. Shift and a click, or Shift and Space, takes the range from the
last checkbox. A row that comes in keeps the mark its key held.

## The line

The shell holds a second region below the rows, the selection line above the
pagination row, and each can stand alone. The general footer slot still
refuses pagination.

The line shows while one row or more is selected. It holds a second
check-all, under the row checkboxes, the count and its scope, Clear and the
actions slot. The two check-alls show one state. When the line hides with focus in
it, focus moves to the header check-all, or the first row checkbox, without
a scroll.
"Select all N matching" reads N from the paginator, so a table with none
offers no such control: its page is the set. Below `sm` the line wraps rather
than push a control past the shell.

The line sticks to the foot of the window and stops at the end of its
table. A sticky child needs a shell that does not scroll, thus
the shell clips instead of hiding. The line stays under the menus and states
its height, so the toasts stand off that corner, and the rows' scroll
margin keeps a focused control above it. The build stamp is the
page's last line, which nothing sticky can bury.

## The statement

A selection is one value: the keys, or `all` beside the filter of the list,
the count seen, and the keys unmarked since. A row unmarked under `all`
records an exclusion and keeps the scope. A selection of no rows is the
empty value. The element dispatches each change as
`selectable-table:change`.

The value waits in the tab under the library, the table and the path, so its
other pages restore it, and neither the next person at that
browser nor the table beside it inherits it. A key of another page stays; a
key this page held and holds no longer leaves, while an exclusion stays,
because its row may be restored. A filter change restores nothing, and so
does a page that states no count under a kept scope. Clear, the last row
unmarked, and an act on the selection forget the value. The element never
writes an empty selection it did not make, because an empty write forgets
the value another filter keeps. What is kept is bounded by
the clicking, never by the rows.

## What a view declares

`make_row(..., key=...)` names the row, and `TableData` carries the filter;
the count is the paginator's. A nameless row is refused at render, always, by
the row itself, so a row swapped into a selectable table is refused the same
way; one name on two rows is refused by the table, which alone sees it. `make_row(..., summary=...)` is text under the identity
content, shown below `md` alone — text and not a cell, because a link there
repeats the row's own.

## The announcement

The element owns one `role="status"` region, outside the line, because a
hidden region does not speak. It speaks when the line appears ("N selected.
Selection actions follow the table."), and at check-all, all matching and
Clear. A checkbox reports itself, and a restored selection says nothing,
because the page arrived that way.

## Proof

Vitest covers the selection model and what it keeps. One end-to-end page
proves the steady rows, the aligned checkboxes, the keyboard, focus, the
sticky line, the region, the selection that survives the next page, and the
stacked cell at 390 px.

> This spec is over the 200 to 500 word band. It holds six rules the code
> keeps: the checkboxes and their column, the line and where it sticks, the
> statement grammar, what outlives a page and what forgets it, what a view
> declares, and the announcement. Cutting to the band drops a rule rather
> than a word.
