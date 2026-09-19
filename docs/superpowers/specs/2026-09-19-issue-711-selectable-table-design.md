# A selectable table

`<selectable-table>` is the personality `StyledTable` gains to act on many
rows at once. It holds `<responsive-table>`, which keeps the column drop. The
wave is [Selectable tables](2026-09-19-selectable-tables-wave-design.md).

## The mode

Selection is a mode. A Select toggle turns it on, and only then is there a
checkbox in each row. The mode is off after each page load, unless the list
holds a selection, and turned off it clears the selection. Escape clears the
selection and keeps the mode; a menu that closes on that Escape keeps it,
because a menu marks such a press spent.

The element makes the checkboxes when it connects and shows them with the
mode, so the mode moves no row. A page with no scripting shows none, and the
line stays hidden until the element is defined. The toggle ends the strip
above the table, and a second ends the line, so the control is at one edge
for a reader at either end of a long table.

## The checkbox

The checkbox is the first child of the identity cell, which stays a
`<th scope="row">` and keeps its pin above `md`. It is not a column: the drop
classes and `MAX_DATA_TABLE_COLUMNS` count as before. It carries the row name
and a touch target, and its column is reserved always, which the header label
clears and the name floor below `md` budgets.

Only the checkbox selects, because the row holds links and immediate
controls. Shift and a click, or Shift and Space, takes the range from the
last checkbox. A row that comes in keeps the mark its key held.

## The footer

The footer holds a second region, the selection line above the pagination
row, and each can stand alone. The general slot still refuses pagination.

The line holds the check-all for the page, under the row checkboxes, the
count and its scope, Clear, the actions slot, and the toggle at its end.
"Select all N matching" reads N from the paginator, so a table with none
offers no such control: its page is the set. Below `sm` the line wraps rather
than push a control past the shell.

While the mode is on, the line sticks to the foot of the window and stops at
the end of its table. A sticky child needs a shell that does not scroll, thus
the shell clips instead of hiding. The line stays under the menus and states
its height, so the toasts stand off that corner; the build stamp is the
page's last line, which nothing sticky can bury.

## The statement

A selection is one value: the keys, or `all` beside the filter of the list,
the count seen, and the keys unmarked since. A row unmarked under `all`
records an exclusion and keeps the scope. The element announces each change
as `selectable-table:change`.

The value waits in the tab under the path of the list, so its other pages
restore it, the mode with it. A key of another page stays; a key this page
held and holds no longer leaves. A filter change is another set and restores
nothing; Clear and the mode turned off forget the value. What is kept is
bounded by the clicking, never by the rows.

## What a view declares

`make_row(..., key=...)` names the row, and `TableData` carries the filter;
the count is the paginator's. A nameless row under such a table is refused at
render, always. `make_row(..., summary=...)` is text under the identity
content, shown below `md` alone — text and not a cell, because a link there
repeats the row's own.

## The announcement

The element owns one `role="status"` region. It speaks at the four changes of
scope: the mode, check-all, all matching, Clear. A checkbox reports itself, and
a restored selection says nothing, because the page arrived that way.

## Proof

Vitest covers the selection model and what it keeps. One end-to-end page
proves the mode, the steady rows, the keyboard, the sticky line, the region,
the selection that survives the next page, and the stacked cell at 390 px.

> This spec is over the 200 to 500 word band. It holds five rules the code
> keeps: the mode and its reserved column, the footer composite, the
> statement grammar and what outlives a page, what a view declares, and the
> announcement. Cutting to the band drops a rule rather than a word.
