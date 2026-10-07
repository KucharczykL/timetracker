# Plan: calendar bottom sheet on narrow viewports (#516)

Spec: `docs/superpowers/specs/2026-10-07-issue-516-calendar-bottom-sheet-design.md`.
Implementation inline, TDD per task. Iterate with `make test-ts TS_ARGS=…`,
focused `make test ARGS=…` under the shared lock.

## Task 1 — attachMenu owns its open state; opener on MenuController

Files: `ts/elements/menu-behavior.ts`, `ts/elements/drop-down.ts`,
`ts/elements/menu-behavior*.test.ts` (find the existing test file).

- `let opened = false`; `isOpen()` and `reposition` read it; `open()` sets it
  after `showInTopLayer` succeeds, `close()` clears it.
- `MenuController.open(opener?: HTMLElement)`. attachMenu stores the opener;
  `restoreFocus` focuses `opener ?? toggle` when focus is in the menu. Clear
  the stored opener on close.
- `DropdownElement.open(opener?)` passes through; add `isOpen()`.
- Tests: isOpen stays false when the panel is unhidden by a third party;
  Escape returns focus to the opener.

## Task 2 — top-layer release helpers

File: `ts/elements/surface-stack.ts` (+ test).

- `releaseFromTopLayer(panel)`: hide from top layer if showing, then remove
  `popover` and `hidden`. `returnToTopLayer(panel)`: set `popover="manual"`,
  `hidden`. Names from `CLOSED_POPOVER`'s pair — check how Python spells it
  and whether TS has a constant.

## Task 3 — split attachSheet

Files: `ts/elements/sheet-controller.ts`, `sheet-controller.test.ts`.

- `attachSheetCore(host, dialog, {initialFocus, beforeHide, afterHide})`
  returns `{open(opener?), close, isOpen, focusFirst, state}`. Owns modal,
  slide, `data-sheet-state`, show/hide events. Requires `[data-sheet-panel]`.
- `attachSheet` = core + toggle click + `aria-expanded` + `isReachable`
  guard + same-page nav (`afterHide`). `open()` passes `toggle` as opener.
- Existing sheet tests must pass unchanged. Add core tests: no toggle
  listener, hook order (beforeHide → dropdown:hide → afterHide).

## Task 4 — generated attribute names + Python shell

Files: `common/components/custom_elements.py`, `common/components/modal.py`,
`games/management/commands/gen_element_types.py`, tests in
`tests/test_custom_elements.py`, `tests/test_modal_dialog.py`.

- `DROPDOWN_SHEET_ATTRIBUTES` mapping (roles: sheet, wide, host, body,
  title); codegen to `ts/generated/dropdown-sheet-attributes.ts`.
  Check `make check-static` drift guard picks the file up.
- `ModalPanelHeader`/`titled_header`: `title_id: ElementId | None`.
  `TitledHeader.labelled_by` becomes optional or the caller skips it —
  pick the shape that keeps BottomSheet markup byte-identical.
- `sheet_dialog(...)` private helper shared by `BottomSheet` and
  `dropdown_sheet(title)`. Dropdown sheet: no `data-bottom-sheet`,
  `max-h-[90dvh]`, empty body, title carries the title role attribute.
- `dropdown_sheet(title) -> Fragment(sheet dialog, sentinel)`.
- `_assemble`/`Dropdown` take `sheet_title: Child | None = None`.
- Test: BottomSheet markup unchanged (existing pins); dropdown sheet has no
  id, no `data-menu`, no `data-bottom-sheet`.

## Task 5 — narrow-sheet switch

Files: new `ts/elements/narrow-sheet.ts` + `narrow-sheet.test.ts`;
`ts/elements/drop-down.ts`, `ts/elements/dropdown-behaviors.ts`.

- `attachNarrowSheet(host, menu, anchored, {dialog, sentinel, sheetFocus})`
  → `MenuController`.
- connect: stamp counter id on `[title role]` and dialog `aria-labelledby`.
- open(opener): wide → `anchored.open(opener)`. Narrow → remember parent +
  nextSibling, move, `releaseFromTopLayer`, set host attr, `core.open(opener)`;
  `try/finally` restore when not open.
- core `beforeHide` → restore (insertBefore recorded sibling, still a child
  of parent, else append), `returnToTopLayer`, drop host attr.
- resize listener (window, rAF-throttled) only while open; on mismatch set
  `pendingMove`, close current; on `dropdown:hide` with pendingMove, re-read
  sentinel, open that host with the saved opener. `close()` clears
  pendingMove; DropdownElement.disconnectedCallback calls close.
  Gotcha: the move's own close must not clear pendingMove — use an internal
  close path.
- `isOpen = anchored.isOpen() || core.isOpen()`; `focusFirst` delegates.
- `DropdownBehavior.sheetFocus?(menu)`; date-calendar registers
  `[data-date][aria-selected=true]` then `[data-date][aria-current=date]`;
  core default falls back to the dismiss button.
- DropdownElement: if own sheet + sentinel exist: a `createController`
  behavior → `reportClientError`, no wrap; else wrap.
- Tests (jsdom, stub `getClientRects` like section-nav.test.ts, stub
  `showModal`/`showPopover` as existing sheet tests do): wide/narrow open,
  move + attribute restore, refused open restores, throwing open restores,
  resize move both directions, close drops pending move, distinct ids for
  two instances.

## Task 6 — calendar host wiring

Files: `ts/elements/date-calendar-core.ts` (+ tests in
`date-picker.test.ts`/`date-range-picker.test.ts`).

- `isOpen` → `dropdownHost.isOpen()` (type the closest as DropdownElement).
- `open()` passes `toggleButton` as opener.
- sync `aria-expanded` on `dropdown:show` too.

## Task 7 — calendar sheet look + pickers render the sheet

Files: `common/components/date_range_picker.py`, `date_picker.py`,
`date_time_picker.py`; regenerate `ts/generated/calendar-classes.ts`.

- Shell: `group/calendar` + `data-[dropdown-host=sheet]:` border-0,
  rounded-none, bg-transparent, backdrop-blur-none, flex-col.
- Grid `w-77` + sheet `w-full`; `_DAY_CELL_GEOMETRY_CLASS` and weekday get
  `group-data-[dropdown-host=sheet]/calendar:w-auto`. Verify Tailwind sees
  the class strings (Python sources are in its content globs?).
- Presets: sheet `flex-row flex-wrap border-e-0 border-b`; preset buttons
  sheet `w-auto`.
- Pickers: `_Dropdown(...)[picker, dropdown_sheet(label)]`.
- Tests: each picker renders one sheet titled by label + sentinel;
  YearPicker none. `tests/test_node_tree.py` media tuple unchanged.

## Task 8 — form-dialog baseline

File: `ts/elements/form-dialog/unsaved.ts` (+ test).

- `formsOf` keeps forms whose `parentElement.closest("dialog")` equals the
  body's nearest dialog. Test: a form inside a nested dialog is ignored.

## Task 9 — e2e

File: new `e2e/test_calendar_sheet_e2e.py`.

- 375×812: add-session (or the playthrough form) date field → sheet open
  (`dialog[data-dropdown-sheet][open]`), pick day → closed, value set, focus
  on calendar button. Range picker in filter builder → footer visible.
  Date field inside a form dialog → two open modals, sheet on top.
  Resize 375 → 1024 with calendar open → anchored panel visible.
- Desktop: popup anchored, no sheet open.
- Run `test_touch_targets_e2e.py`, all date e2e files, modal/top-layer e2e.

## Gotchas

- `make ts` after TS edits before e2e; never with `make dev` up.
- `make gen-element-types` after Python class/attribute changes; drift guard.
- `make lint-fix` for imports.
