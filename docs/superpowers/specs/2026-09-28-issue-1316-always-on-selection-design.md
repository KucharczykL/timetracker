# Always-on row checkboxes, tray on selection

Issue #1316. It replaces #1212. The table contract is
[A selectable table](2026-09-19-issue-711-selectable-table-design.md). The
wave is [Selectable tables](2026-09-19-selectable-tables-wave-design.md).

## Rule

Selection is not a mode. A selectable table shows a checkbox on each row at
all times. The selection line (the tray) shows while one row or more is
selected. It hides when no row is selected.

There is no Select toggle and no strip above the table.

## Why

The mode reserved the checkbox column at all times, so that rows did not
move. While the mode was off, that column was empty. Without the mode, the
column holds its checkboxes and no row moves. Gmail and GitHub's issue list
use the same pattern.

## Check-all

The page has two check-all boxes with one state. One is in the first header
cell. One is in the line. Both are in the column of the row checkboxes. The
header cell, the row header cell and the line use the same inset, so the
boxes align without measurement.

The header box is outside the sort link. The first header cell uses `py-2`,
so the header row keeps its height. With no scripting, the header box is
hidden. A selectable table without a header is refused, because the header
holds the only check-all shown while nothing is selected. Both boxes set
`autocomplete="off"`, so a restored form state does not show a false check.

## The line

The element sets the line's `hidden` from the count. A selection of zero
rows becomes the empty selection, also on restore. The element publishes
the line's height as `--selection-line` only while the line shows. The
rows use it as their bottom scroll margin, so a focused control in a row
does not go under the line. Document padding would also scroll to reveal
the sticky line itself, to the end of its table.

Connect renders only a restored selection. An empty render forgets the
stored value, and that value can belong to another filter of the list.

Clear and Escape empty the selection. A submitted act empties it too. When
the line hides with focus in it, focus moves to the header check-all, with
no scroll. If that box is not shown, focus moves to the first row checkbox.

## Announcements

The `role="status"` region is outside the line, because a hidden region
does not speak. When the line appears, the region says "N selected.
Selection actions follow the table." A restored selection says nothing.

## Costs

- Each row checkbox is a tab stop.
- The first tick can show the line over rows at the foot of the window.
- "Select all N matching" is in the line, so it comes after a first tick.

## Proof

Vitest covers the line and the count, both check-alls, the zero rule, focus,
the region, and stored values. End-to-end tests prove the aligned boxes at
two widths, the line and a tabbed box, Clear's focus and scroll, and a page
with no scripting.
