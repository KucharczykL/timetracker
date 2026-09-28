# Always-on row checkboxes, tray on selection

Issue #1316, superseding #1212. Changes
[A selectable table](2026-09-19-issue-711-selectable-table-design.md) and the
[Selectable tables wave](2026-09-19-selectable-tables-wave-design.md). No
server-side change: statements, the bulk runner and every act stay as they
are.

## What changes

Selection stops being a mode. A selectable table shows a checkbox on every
row at all times. The selection line, the tray, appears while at least one
row is selected, and hides when none is.

The mode existed to keep boxes out of sight until asked for. Its column was
reserved anyway, so rows would not move when the mode turned on, and that
reserve stood empty on every list, which #1212 was filed to fix. Its two
options each cost something: collapsing the reserve moves every row when
the mode turns on, and a trailing box sits beside the row's ⋯ menu in a
column nobody scans. With no mode, the reserve holds the boxes it was
reserved for, and neither cost is paid. Nothing moves: an `invisible` box
already takes its space.

This overturns two settled points of the wave: "selection is a mode" and
"there is no header checkbox", which followed PatternFly, Carbon, Polaris,
Helios and SABnzbd's Glitter. The charter's header checkbox returns. Gmail
and GitHub's issue list are the prior art for boxes that are always there.

## Costs accepted

- Every row box is a tab stop at all times; `visibility: hidden` kept them
  out of the order before. A keyboard reader passes one box per row, and
  the tray, after the rows, is reached past them. Gmail and GitHub pay the
  same. A roving tabindex is not worth its keyboard model here.
- The first tick can show the tray over rows near the viewport's foot,
  where the press was made. Focus is kept clear of it (below); the pointer
  scrolls.
- "Select all N matching" lives in the tray, so it is reached after a
  first tick, most directly the header check-all.

## Removed

- `SelectionToggle` and `SelectionBar`, the strip above the table, and the
  toggle that ends the tray. Their exports go too.
- The `data-selection-mode` attribute. The tray's sticky classes apply
  unconditionally: a hidden tray renders nothing to stick.
- In the element: `mode`, `toggles`, `setMode`, `showCheckboxes`, the
  `invisible` class `decorateRows` toggles, and the connect guard on
  toggles, which would otherwise disable the element. Every read of the
  mode becomes a read of the count: the Escape guard and its deferred
  check, and `onRowsChanged`, which renders when the count is not zero or a
  key was pruned.
- The announcements "Selecting rows." and "Selection off."
- `_SELECTION_LABEL_INSET_CLASS`. The header check-all takes the 32px.
- Comments stating the mode: the element's file comment, `statement()`'s
  docstring, `selection-actions.ts` on the line it reads, and
  `isSelectable` in `responsive-table.ts`.

## Check-all, twice

Check-all is one state drawn in two places, both marked
`data-selection-check-all`: the first column's header cell and the tray.
The first column, not "name": Game detail's historical table leads with
another. The element keeps a list and renders checked and indeterminate
onto each; a change on either sets the page.

Both stand in the row boxes' column. The header box is the row box's look
(`CHECKBOX_LOOK_CLASS`, `w-6 h-6`, `me-2`) and leads the label in a flex
row, outside `<sort-header>`'s link, so a press never sorts. Box and gap
are 32px, the width `ms-8` cleared, so the label stays over the names and
`SELECTION_RESERVE_PX` and `SELECTION_CHECKBOX_COST_PX` keep their meaning.
Header cell, body `th` and tray share `px-2 sm:px-3 lg:px-6`, and the table
has no border spacing, so the three columns of boxes share one `x` by
construction, at `scrollLeft` 0. Below `md` nothing is pinned, and a
horizontally scrolled table moves header and rows off the tray's box.

The first header cell takes `_HEADER_CONTROL_CELL_CLASS` (`py-2`) while
selectable: `py-2` and a 24px box make the 40px that `py-3` and a 16px
label make, so the header keeps its height. Where the first column is also
the last and no menu slot exists, the column picker trails the same cell.

The header box is server-rendered and hidden with
`[selectable-table:not(:defined)_&]:hidden`, as the tray is. With no
scripting there is no box, and the label stands at the cell's inset.

Names: "Select every row on this page" in the header, and "…, from the
tray" in the tray; locators take `exact`. A labelled box inside a
`<th scope="col">` may enter the column header's name that Orca reads
beside each cell. The Orca pass judges this; the fallback is an explicit
name on the `th`.

## The tray

State changes go through one `setState`, which makes a state whose count
is zero `emptySelection()`, so an "all matching" scope with every row
excepted is neither shown nor stored as "all". The restore path goes
through it too, and a stored value it empties is forgotten.

`render()` sets the tray's `hidden` from the count, then republishes
`--selection-line`, which `lineHeight()` reads from the tray's `hidden`.
`Page()` puts `scroll-pb-[var(--selection-line,0px)]` on `<html>`, so a box
reached by Tab scrolls clear of the tray (WCAG 2.4.11).

Connect renders only on restore, as today. A render with an empty state
forgets the path's storage key, and the key names no filter: a render at
every mount would erase the selection another filter keeps for a reader
who goes back. The server renders the tray `hidden`, which is the state a
fresh page needs.

Clear, and Escape, empty the state. When focus was inside the tray, read
before `hidden` is set, it moves to the header check-all with
`preventScroll`, or to the first row box where the header is not shown. An
act's submit empties the state and renders (`forgetAndClose` becomes
`forget`): `<selection-actions>` latches the statement at the press, before
this listener runs, and a Back from bfcache shows no stale selection.

The announcement region moves out of the tray, to the element's own child:
a `display: none` live region is never spoken. Sentences:

- A press from zero to some: "{n} selected. Selection actions follow the
  table." Check-all from zero says this, not its own sentence.
- Check-all otherwise: "{n} selected"; all matching and Clear as today.
- A restore at connect says nothing.

## Unchanged

Shift-click and Shift-Space ranges; rows arriving through the
`MutationObserver`; pruning keys that left; storage per path with the
filter inside the value; `statement()` for the slot that upgrades later.
Every selectable table gets the change, Game detail's two included.

## Verification

Vitest (`selectable-table.test.ts`): mode cases go; add the tray following
the count, both check-alls in step, zero normalising on a press and on
restore, Escape at zero and above, Clear's focus target and fallback, the
three announcements, the region outside the tray, another filter's stored
value surviving a mount and a row mutation, `onRowsChanged` under "all",
and submit then `pageshow`. `selection-actions*.test.ts` fixtures drop the
toggle.

`tests/test_components.py`: the header box, its hidden-while-undefined
class, `py-2`, the picker sharing the cell, no bar, no toggle, the region
outside the tray. Its `ms-8`, `aria-pressed` and first-check-all splits
go.

End to end (`e2e/test_selectable_table_e2e.py`): boxes visible on load,
the tray appearing and hiding, both check-alls in step (locators scoped to
`thead` and `[data-selection-line]`), one `x` for three box columns at
desktop and mobile width, a tabbed box not under the tray, Clear's focus
and scroll position, no box with scripting off. `_checkboxes()` loses its
`:not(.invisible)`. The nine other files that press "Select rows" stop.
Looked at on the session list at both widths; an Orca pass over the header
box, the column header's name, and the tray appearing.
