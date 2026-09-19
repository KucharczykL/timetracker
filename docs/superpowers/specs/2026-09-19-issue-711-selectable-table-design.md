# A selectable table

> This spec is 625 words. The band is 200 to 500. The overrun is an explicit
> exception for this document: it holds one mode, one footer region, one
> statement grammar, a row shape and a keyboard contract, and each is a rule
> the code keeps. It is not a loosening of the band.

`<selectable-table>` is the personality `StyledTable` gains for acting on many
rows at once, around `<responsive-table>`, which keeps the column drop. The
chrome's home is the wave's:
[Selectable tables](2026-09-19-selectable-tables-wave-design.md).

## The mode

Selection is a mode. A Select toggle in the footer turns it on, and only then
is a checkbox in each row. The mode is off on every page load and is held
nowhere else. Turning it off clears the selection; Escape clears the selection
and keeps the mode, unless a menu in the table answered that Escape first.

The element builds the checkboxes, so a page with no scripting renders none,
and the selection line hides until the element is defined.

## The checkbox

The checkbox is the first child of the row's identity cell, which stays a
`<th scope="row">` and keeps its pin above `md`. It is not a column:
`MAX_DATA_TABLE_COLUMNS` and the drop classes count what they did before. It
carries the row's name and the touch target every control holds.

Only the checkbox selects, because the row holds links and immediate controls.
Shift and a click, or Shift and Space, takes the range from the last checkbox
toggled.

A row that arrives while the mode is on is given a checkbox and keeps the mark
its key held; a key the table no longer holds leaves the selection.

## The footer

The footer holds a second region, the selection line above the pagination row,
and either stands alone. The general footer slot keeps refusing to share with
pagination.

The line holds the Select toggle, check-all for the page, the count and its
scope, Clear, and the actions slot #712 fills; with nothing selected it offers
no action. "Select all N matching" reads N from the paginator, so a table with
none offers no such control: its page is the set.

While the mode is on the line sticks to the foot of the window, with the
toggle, and stops at the end of its own table. A sticky child needs a shell
that is not a scroll container, so the shell clips instead of hiding. The line
sits under the menus, because the actions open one, and states its height, so
the toasts and the version stamp stand off the corner they share with it.

## The statement

A selection is one value: the keys, or `all` beside the list's filter, the
count seen and the keys unmarked since, so unmarking a row under `all` records
an exclusion and keeps the scope. The element holds the value and announces
each change as `selectable-table:change`; the field that posts it is #712's.

## What a view declares

`make_row(..., key=...)` names the row, and the row states that name. The
table declares that it is selectable; `TableData` carries the list's filter,
and the count is the paginator's. A row with no name under such a table is
refused at render, always and not in debug alone.

`make_row(..., summary=...)` is text under the identity content, shown below
`md` alone: the stacked cell. It is text and not a cell, because a link there
repeats the row's own. Each line clips on its own, and the checkbox and the
line raise what the fit keeps free for the name below `md`.

## The announcement

The element owns one `role="status"` region, because it owns the selection,
and speaks at the four scope changes: the mode, check-all, all matching,
Clear. A checkbox reports itself.

## Proof

Vitest covers the selection model and the statement: the range, check-all's
three states, the exclusions, a row arriving marked. One e2e page proves the
mode, the keyboard, the sticky line, the region and the stacked cell at
390 px. Pytest pins the row's name and the toggle.
