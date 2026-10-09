# #1559 plan

Specs: [Motion](../specs/2026-10-09-issue-1559-motion-design.md),
[Sheet by default](../specs/2026-10-09-issue-1559-sheet-by-default-design.md).

Delivery: one `gh stack`, three members, cut by coupling. Each member
passes `make check` alone. Inline implementation, TDD per behaviour.

## Member 1 — motion (`claude/issue-1559-motion`)

### Files
- `common/input.css` `@theme`: the ten tokens.
- `ts/motion.ts` (new): `motionDuration(name): number` (ms; `""`/NaN → 0),
  `holdLeave(element, exitToken, finish): CancelLeave` (stamps
  `data-motion="leaving"`, waits `getAnimations({subtree:true})`
  finished, caps at duration + 100 ms, immediate when `getAnimations`
  absent or duration 0), `settleEntry(element)` (flush computed style,
  drop `data-motion="entering"`), `prefersReducedMotion()` moved here
  from `sheet-controller.ts`.
- `ts/elements/surface-stack.ts`: `showInTopLayer` stamps `entering`,
  cancels a pending leave; `hideFromTopLayer(element, onHidden?)` holds
  the leave; `releaseFromTopLayer` cancels it.
- `ts/elements/anchored-position.ts`: `positionAnchored` writes
  `data-side`/`data-align`; export a `stampSide` used by
  `positionSubmenu`.
- `ts/elements/menu-behavior.ts`: open → show, position, `settleEntry`;
  close → logical state + `dispatchHide` now, `clearAnchoredPosition` +
  listener removal in `onHidden`. Drop both "no animation" notes.
- `ts/elements/tooltip-behavior.ts`, `pop-over.ts`, search-select's
  panel and every other `showInTopLayer` caller (`rg showInTopLayer ts`):
  same split.
- `common/components/custom_elements.py` (`DropdownPanel`), the
  tooltip/popover builders: entry/exit classes — `opacity`, `scale-95`,
  side-keyed `translate-*-1`, `origin-*` from `data-side`/`data-align`,
  `ease-enter`/`ease-exit`, `duration-(--duration-fast)` /
  `duration-(--duration-fast-exit)`, reduced variants (`motion-reduce:`
  scale/translate none, `duration-(--duration-reduced)`). One literal per
  class string.
- `ts/elements/modal-layer.ts`: default `leave` for a modal stating none
  (centred); waits through `holdLeave`. Keep `LEAVE_LIMIT_MS`.
- `common/components/modal.py`: `_MODAL_DIALOG_CLASS` backdrop fade
  in/out; centred panel fade+scale 96 % via `starting:`; split
  `_MODAL_PANEL_CLASS` (cue `transform` + scrim vs sheet `translate` +
  `opacity`); scrim element (`::after` or a child `[data-modal-scrim]`)
  replaces `filter`.
- `ts/elements/modal-stack.ts`: brightness → scrim opacity var.
- `ts/elements/sheet-controller.ts`: leave through `holdLeave`; drop
  `CLOSE_FALLBACK_MS`, `translate` listener.
- `custom_elements.py` `_SHEET_DIALOG_CLASS`/`_SHEET_PANEL_MOTION_CLASS`:
  `ease-sheet`, slow/slow-exit, reduced crossfade.
- `ts/elements/toast-stack.ts`: `LEAVE_CLASS`/`LEAVE_MS` → tokens; entry
  class taken once (`data-entered` after first frame).
- `e2e/conftest.py`: context `reduced_motion="reduce"`.
- `e2e/test_motion_e2e.py` (new): motion on; menu open/close, centred
  form dialog, sheet open/close, toast; nothing left `leaving`.
- `tests/test_motion_tokens.py` (new): no `duration-<digits>`, bare
  `ease-in|ease-out|ease-in-out`, or `motion-safe:` motion class in
  `common/`, `games/`, `ts/` (TS: the `class` strings it builds).

### Tests first
- vitest `motion.test.ts`: zero duration finishes at once; cancel stops
  finish; cap fires; subtree animations awaited (fake `getAnimations`).
- `surface-stack.test.ts`: show during leave cancels it; release cancels
  it; `onHidden` runs once.
- `menu-behavior.test.ts`: `dropdown:hide` at close start; geometry kept
  until hidden.
- `anchored-position` test: flipped panel stamps `top`.
- `sheet-controller.test.ts`: rewrite the `CLOSE_FALLBACK_MS`/`translate`
  cases onto `holdLeave`.
- `tests/test_modal_dialog.py:147`: assertions flip (no `motion-safe:`).

### Gotchas
- jsdom: no `getAnimations` → immediate; most `.hidden` asserts hold.
- Toasts re-parent on `MODAL_CHANGE`: never `@starting-style` there.
- `test_color_tokens.py`: scrim colour from a token.

## Member 2 — sheet levels (`claude/issue-1559-levels`)

### Files
- `ts/elements/modal-layer.ts`: `ModalOptions.cancel` (native cancel;
  default `dismiss`); `closeTogether(dialog)` (marks it and all above
  leaving; runs only the top's `leave`; on its finish finishes the rest
  top first in one task); entries finished by `closeAbove` skip
  `returnFocus`; `markBackdrops` skips a `data-sheet-level` cover.
- `ts/elements/modal-stack.ts`: levels out of depth, reserve, trails.
- `ts/elements/sheet-levels.ts` (new): `enclosingSheet(host)`, level
  push/back presentation (WAAPI: incoming 100 %→0, below 0→-30 % + dim,
  height from→to, slow / slow-exit, `ease-sheet`; reduced: crossfade),
  below panel `visibility:hidden` after push, restored before back.
- `ts/elements/narrow-sheet.ts`: `present` asks `enclosingSheet`; a level
  opens its own dialog stamped `data-sheet-level`, skips resize moves,
  `cancel` → back, `dismiss` → `closeTogether(first)`; click on an acting
  menuitem in a level → `closeTogether(first)`.
- `ts/elements/sheet-controller.ts`: `SheetCoreOptions.cancel`, a
  `levelOf` presentation hook, silent leave for a non-top chain member.
- `common/components/modal.py` `ModalPanelHeader(leading=)`;
  `custom_elements.py` `dropdown_sheet`: hidden back control
  `[data-sheet-back]` (‹ + `[data-sheet-back-label]`, `aria-label` set on
  push); `SHEET_ATTRIBUTES` gains `back`, `back_label`, `level` →
  `make gen-element-types` codegen.
- `custom_elements.py` level backdrop: `data-sheet-level:backdrop:opacity-0!`.

### Tests first
- `modal-layer.test.ts`: `cancel` apart from `dismiss`; `closeTogether`
  runs one leave, finishes top first, returns focus once to the first
  opener; `closeAbove` returns no focus; level does not cover.
- `modal-stack.test.ts`: level excluded from depth/reserve/trail.
- `narrow-sheet.test.ts`: nested host inside open sheet opens a level;
  Escape (cancel) backs; × closes all; acting item closes all; resize
  moves only the first.
- e2e (390 px, motion reduced): overflow → facet → ChoicePicker as
  levels; back control text/name; Escape backs; × closes all, focus on
  overflow trigger, picker does not reopen.

## Member 3 — sheet by default (`claude/issue-1559-sheet-default`)

### Files
- `custom_elements.py`: `Dropdown(sheet: SheetSpec)` required;
  `_assemble(sheet)` `None` only with `behavior="sheet"` (ValueError
  otherwise); `ButtonDropdown`, `SplitButtonDropdown(aria_label)`
  required, `SelectDropdown(sheet_title)`, `DropdownSubmenuItem`,
  `RowActionMenu` pass titles.
- `search_select.py` `ComboboxDropdown(sheet)` required; `domain.py`
  "Status"/"Device"; `navigation.py` username; `search_field.py`
  "Match"; `column_picker.py` "Columns"; `icon_picker.py` label;
  `quick_filter.py` overflow `OVERFLOW_LABEL`; `primitives.py`
  selection overflow "More actions", page size `ButtonDropdown`.
- `quick_filter.py` `_facet_apply(divided)`: non-set facets drop the
  border in a sheet (`group-data-[dropdown-host=sheet]/dropdown:` look).
- `ts/elements/behaviors/menu.ts`: `sheetFocus` (first own item, else
  first tabbable); hover no-op while parent menu stamped sheet.
- `ts/elements/menu-behavior.ts`: submenu click/ArrowRight through
  `presenter` (idempotent open).
- `behaviors/select.ts`, `choice-grid.ts`, `column-picker.ts`:
  `sheetFocus`.
- `ts/elements/form-dialog.ts` `openFrom`: before `openDialog`, await
  `whenSettled` when `isModalLeaving()`.
- `tests/html_answers.py`: parsed check, every non-`sheet` `<drop-down>`
  owns a `[data-dropdown-sheet]`.

### Tests to update
- Remove `tests/test_dropdown_sheet.py:57`
  (`test_a_dropdown_without_a_title_carries_no_sheet`); update its
  `dropdown()` helper.
- Pass `sheet=` at `tests/test_dropdown_panel.py:101`,
  `test_top_layer_markup.py:44`, `test_quick_filter_bar.py:593-601`,
  `test_search_select.py:1017`, `test_custom_elements.py:132`,
  `e2e/test_compact_button_e2e.py:16`, `e2e/test_top_layer_e2e.py:43`,
  `e2e/test_selectable_table_e2e.py:80`.
- Phone-width e2e that now open sheets: `test_quick_filter_e2e.py:394`
  (overflow chain, levels), `test_selection_actions_e2e.py:120`, any
  390 px test pressing a row ⋯ or a selector. Run `make test-e2e` and fix
  by `picker_opened`-style settled waits.

### New tests
- e2e 390 px: row ⋯ menu as sheet, first item focused, act closes;
  entry menu submenu as level, act inside closes whole; "Set times
  played…" (Played split button) opens its form dialog over the page
  after the sheet leaves; status selector sheet picks and PATCHes.
- vitest: menu `sheetFocus` fallback; hover guard; submenu presenter.

## Gate
Per member: `make format`, `make lint-fix`, `make format-check`,
`make vale`; full `make check` under the lock once at the end, then
`gh stack submit` (draft).
