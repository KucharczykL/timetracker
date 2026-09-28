# Always-on row checkboxes implementation plan

**Goal:** `<selectable-table>` without a mode: row boxes always shown, the
tray shown while the count is not zero, check-all in the first header cell
and in the tray.

**Spec:** [Always-on row checkboxes, tray on selection](../specs/2026-09-28-issue-1316-always-on-selection-design.md)

## Global constraints

- Rebase onto `origin/main` first.
- Everything through `make`. Iterate with `make check-fast` and focused
  `make test-e2e ARGS=…` / `make test-ts TS_ARGS=…`; `make ts` after each
  `.ts` edit before e2e. Never e2e while `make dev` runs. Full `make check`
  once at the end, under the shared `flock` when another worktree is busy.
- `make format`, `make lint-fix`, `make vale` before the commit.
- Complete-word identifiers; comments state present design, no issue refs.

## Task 1 — Components (`common/components/primitives.py`)

- Delete `SelectionToggle`, `SelectionBar`, `_SELECTION_LABEL_INSET_CLASS`,
  and `StyledTable`'s `inner_children.insert(0, SelectionBar())`. Drop the
  two names from `common/components/__init__.py`.
- `_SELECTION_LINE_STICKY_CLASS` becomes `sticky bottom-0 z-10`.
- `SelectionLine`: drop `SelectionToggle(pressed=True)`; tray check-all
  gets the "…, from the tray" name; the announcement region leaves the
  line. The checkbox template stays.
- New `SelectionAnnouncement()` (the `role=status` sr-only div) placed by
  `StyledTable` as a direct child of `_SelectableTable`, outside the line.
- New `_header_check_all()`: `Input(data-selection-check-all, type=checkbox)`
  with the row box's classes plus `[selectable-table:not(:defined)_&]:hidden`,
  labelled "Select every row on this page".
- `_header_cell(selectable=True)`: padding `_HEADER_CONTROL_CELL_CLASS`;
  label becomes `Span("flex items-center")[_header_check_all(), label]`
  for both the static and the sortable branch; the box never inside
  `<sort-header>`. The `trailing` picker wrap keeps working around it.
- `common/layout.py`: `<html>` gets `scroll-pb-[var(--selection-line,0px)]`;
  `make css` so `base.css` holds the utility.
- Update the comments at `SELECTION_RESERVE_PX` (the header box now clears
  the 32px, not `ms-8`).

Tests (`tests/test_components.py`): header box present, first column only,
hidden-while-undefined class, `py-2`; picker sharing the cell when the
first column is last; no `data-selection-bar` / `data-selection-toggle`;
announcement region not inside `[data-selection-line]`; two check-alls.
Remove the `ms-8`, `aria-pressed` and icon pins; the "first check-all"
splits scope to `[data-selection-line]`. `html` carries the scroll padding.

## Task 2 — Element (`ts/elements/selectable-table.ts`)

- Remove `mode`, `toggles`, `setMode`, `showCheckboxes`,
  `HIDDEN_CHECKBOX_CLASS`, the toggle guard at connect (guard on `line`).
- `checkAll` → `checkAlls: HTMLInputElement[]`; each listens `change`,
  `onCheckAll(source)` reads the source's `checked`; `render()` writes all.
- `setState(next)`: normalise zero count to `emptySelection()`; every
  assignment to `this.state` goes through it (toggle, range, check-all, all
  matching, clear, prune, restore). Restore: if normalised empty,
  `forgetSelection`, else `render()`; say nothing.
- `render()`: `line.hidden = count === 0`, then `publishLineHeight()`.
  Returns or records the previous count so the zero-to-some sentence is
  written by the press handlers, not by restore.
- `lineHeight()`: `line.hidden ? 0 : height`.
- `onKeyDown` Escape: guard and deferred check on `count() > 0`.
- `onRowsChanged`: render when `count() > 0` or keys were pruned.
- `clear({ fromTray })`: read `line.contains(document.activeElement)`
  before hiding; after render focus header check-all (`preventScroll`),
  else first row box. Clear button and Escape call it.
- `forgetAndClose` → `forget()`: empty state, render, no focus move.
- `decorateRows`: no `invisible` toggle.
- Announcements: zero-to-some sentence from row toggle, range and
  check-all; check-all otherwise `"{n} selected"`; restore silent.
- Comments: file header, `statement()` docstring. Same sweep in
  `selection-actions.ts` (the line it reads) and `isSelectable` in
  `responsive-table.ts`.

Tests (`ts/elements/selectable-table.test.ts`): replace the mode cases.
New cases: box visible without a press; tray hidden at 0 and shown at 1;
header and tray check-all in step incl. indeterminate; unchecking to 0
under "all matching" empties and forgets; stored "all" fully excepted is
forgotten at connect; Escape at 0 does nothing, at >0 clears; Clear from
tray focuses header check-all, falls back to first row box without a
header; the three sentences and restore silence; region outside the line;
another filter's stored value survives mount and a row mutation; rows
arriving under "all" render checked; submit then `pageshow` shows nothing
selected. `selection-actions*.test.ts` fixtures drop
`data-selection-toggle` and any mode setup.

## Task 3 — End to end

- `e2e/test_selectable_table_e2e.py`: delete `_select_mode`; `_checkboxes()`
  drops `:not(.invisible)`; check-all locators scoped to `thead` /
  `[data-selection-line]` with `exact=True`. Add: boxes visible on load;
  tray appears and hides with the count; both check-alls in step; header,
  row and tray box `x` equal (bounding boxes, `scrollLeft` 0) at desktop
  and 375px; Tab onto the last visible row box leaves it above the tray's
  top; Clear from the tray keeps `scrollY` and focuses the header box;
  scripting off shows no box and no tray.
- Stop pressing "Select rows" / the bar toggle in
  `test_bulk_device_removal_e2e.py`, `test_bulk_edit_e2e.py`,
  `test_bulk_edit_moves_e2e.py`, `test_bulk_game_edit_e2e.py`,
  `test_bulk_game_removal_e2e.py`, `test_bulk_playthrough_acts_e2e.py`,
  `test_bulk_runner_e2e.py`, `test_selection_actions_e2e.py`,
  `test_session_list_mobile_e2e.py`. Where a test waited on the toggle to
  reveal boxes, wait on the element being defined instead.

## Task 4 — Docs and the look

- Merge the spec into `2026-09-19-issue-711-selectable-table-design.md`
  ("The mode" section rewritten) and the wave spec's bullet, step 7 and
  the overturn paragraph; CLAUDE.md has no mode text to change.
- Screenshot the session list at desktop and mobile width.
- Ask the user for an Orca pass: header box, the column header name Orca
  reads for body cells, the tray-appearing sentence, Clear.

## Gotchas

- Two `[data-selection-check-all]` now: Playwright strict mode fails an
  unscoped locator, and `get_by_label` substring-matches both names.
- `writeSelection` with an empty state forgets the path key; never render
  at connect without a restore.
- Read `activeElement` before `hidden`; Chrome moves focus lazily.
- `<selection-actions>`' submit listener must still run before `forget()`;
  it is nested inside `[data-selection-actions]`, so bubbling keeps the order.
- `import`-bearing dist modules stay `ModuleScript`; nothing new here loads
  as a classic script.

## Follow-up issues to file

None known. File one if the Orca pass wants the `th`'s name set
explicitly and that exceeds this PR.
