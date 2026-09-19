# A selectable table

`<selectable-table>` is the personality `StyledTable` gains to act on many
rows at once. It holds `<responsive-table>`, which keeps the column drop. The
wave is [Selectable tables](2026-09-19-selectable-tables-wave-design.md).

## The mode

Selection is a mode. A Select toggle in the footer turns it on, and only then
is there a checkbox in each row. The mode is off after each page load, and
turned off it clears the selection. Escape clears the selection and keeps the
mode; a menu that closes on that Escape keeps it, because a menu marks such a
press spent.

The element makes the checkboxes, so a page with no scripting shows none.
The selection line stays hidden until the element is defined.

## The checkbox

The checkbox is the first child of the identity cell, which stays a
`<th scope="row">` and keeps its pin above `md`. It is not a column: the drop
classes and `MAX_DATA_TABLE_COLUMNS` count as before. It carries the row name
and a touch target.

Only the checkbox selects, because the row holds links and immediate
controls. Shift and a click, or Shift and Space, takes the range from the
last checkbox.

A row that comes in while the mode is on gets a checkbox and keeps its mark.
A key the table no longer holds leaves the selection.

## The footer

The footer holds a second region, the selection line above the pagination
row, and each can stand alone. The general slot still refuses pagination.

The line holds the Select toggle, the check-all for the page, the count and
its scope, Clear, and the actions slot. "Select all N matching" reads N from
the paginator, so a table with none offers no such control: its page is the
set.

While the mode is on, the line sticks to the foot of the window and stops at
the end of its own table. A sticky child needs a shell that does not scroll,
thus the shell clips instead of hiding. The line stays under the menus and
states its height, so the toasts and the version stamp stand off that
corner.

## The statement

A selection is one value: the keys, or `all` beside the filter of the list,
the count seen, and the keys unmarked since. A row unmarked under `all` records an
exclusion and keeps the scope. The element holds the value and announces each
change as `selectable-table:change`.

## What a view declares

`make_row(..., key=...)` names the row, and `TableData` carries the filter of
the list; the count is the paginator's. A nameless row under such a table is
refused at render, always.

`make_row(..., summary=...)` is text under the identity content, shown below
`md` alone. It is text and not a cell, because a link there repeats the row's
own. It clips on its own, and the checkbox raises the space the fit keeps for
the name.

## The announcement

The element owns one `role="status"` region. It speaks at the four changes of
scope: the mode, check-all, all matching, Clear. A checkbox reports itself.

## Proof

Vitest covers the selection model. One end-to-end page proves the mode, the
keyboard, the sticky line, the region, and the stacked cell at 390 px. Pytest
pins the row name.
