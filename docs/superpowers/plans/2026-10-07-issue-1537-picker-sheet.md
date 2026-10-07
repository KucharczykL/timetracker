# Issue #1537 plan: a picker opens as a bottom sheet on a phone

Spec: `docs/superpowers/specs/2026-10-07-issue-1537-picker-sheet-design.md`.
Implementation inline, TDD per task. Iterate with `make check-fast` and focused
`make test`/`make test-ts`, under the shared lock.

## Task 1 — switch: `lent`, `sheetOpener`, retry, viewport

Files: `ts/elements/narrow-sheet.ts`, `ts/elements/dropdown-behaviors.ts`,
`ts/elements/drop-down.ts`, `ts/elements/narrow-sheet.test.ts`.

- `NarrowSheetOptions.lent?: HTMLElement` (default `menu`); `PanelPlace`
  records the lent node's place; `openSheet`/`returnPanel` move `lent`, stamp
  `SHEET_ATTRIBUTES.host` on `lent` and `menu`, release/return only `menu`.
  Stamp before the move in; remove after the move back.
- `NarrowSheetOptions.opener?: () => HTMLElement | null`, used when
  `open()` / a host move states none.
- Refused open while a modal leaves: listen once for the layer's settle
  (`MODAL_CHANGE` or a modal-layer export; check which exists) and retry once.
- Viewport: on sheet show, subscribe `visualViewport` `resize`/`scroll`
  (rAF-coalesced), write `--sheet-keyboard-inset` and `--sheet-visible-height`
  on the dialog; unsubscribe and clear on hide.
- `DropdownBehavior.sheetLent?(host, toggle, menu)`,
  `sheetOpener?(host)`; `DropdownElement` passes them.
- Tests: lent node moves and returns to its place; stamps; menu released;
  opener fallback; retry after leave; viewport properties set and cleared;
  no `visualViewport` → no properties.

## Task 2 — sheet panel reads the viewport properties

Files: `common/components/custom_elements.py` (`_sheet_dialog` /
`_DROPDOWN_SHEET_HEIGHT_CLASS`), `tests/test_dropdown_sheet.py`.

- Dropdown sheet panel: `mb-[var(--sheet-keyboard-inset,0px)]` and
  `max-h-[min(90dvh,calc(var(--sheet-visible-height,100dvh)*0.9))]`.
  Literal classes (Tailwind scans). Check compiled CSS after `make css`.

## Task 3 — Python markup: face, host sheet, presets, time zone

Files: `common/components/search_select.py`, `common/components/time_zone_row.py`,
`tests/test_search_select.py`, `tests/test_dropdown_sheet.py`,
`tests/test_time_zone_row.py`.

- `_inline_combobox_host(widget, face)` adds `face` and `dropdown_sheet("")`.
- `_SearchSelectFace(...)`: `Div(data_search_select_face, class "hidden
  max-sm:flex …")` with an outline `ControlButton` open button
  (`data-search-select-face-open`, `aria-haspopup="dialog"`,
  `aria-expanded="false"`, value span `data-search-select-face-value`, muted
  when placeholder, chevron), a × (`data-search-select-face-clear`, `hidden`
  as the widget's ×) when clearable, a second `_dialog_create_link` variant
  (`data-search-select-face-create`) when `dialog_create`.
- Server label: single → selected label / `none_label` / placeholder; multi
  and `FilterSelect` → joined labels / placeholder.
- Container class gains `max-sm:not-data-[dropdown-host=sheet]:hidden`;
  widget's + gains `in-data-[dropdown-host=sheet]:hidden`; listbox gains
  `group-data-[dropdown-host=sheet]/dropdown:max-h-none!` (literal).
- `presets_member` Dropdown `sheet_title=PRESETS_LABEL`; `TimeZoneRow`
  `ComboboxDropdown(sheet=True)`.
- Fix `test_serializer_contract_is_layout_invariant` (drop face/sheet/modal
  hooks); `test_every_quick_facet_carries_a_sheet` counts only facet hosts'
  own sheets. New: host renders face + sheet; face label per state; no ×
  when `clearable=False`; + only with `dialog_create`; presets and time zone
  carry a sheet.
- `make gen-element-types` if any prop changes (none planned).

## Task 4 — widget: lent mode, face sync, pick closes

Files: `ts/elements/search-select.ts`, `ts/elements/behaviors/inline-combobox.ts`,
new `ts/elements/search-select.sheet.test.ts`, `ts/test-setup/search-select-host.ts`.

- `inline-combobox`: `sheetLent` → toggle; `sheetFocus` → host's
  `[data-search-select-search]`; `sheetOpener` → face open button.
- `lent()` reads the stamp on the container. While lent: `hidePanel` keeps
  the host open; `focusout` does no leave work, notes `wasLent`; host
  `dropdown:hide` after `wasLent` runs the leave work once.
- Person picks close: option click / Enter / none row / create row for a
  single-select call `closeAfterPick()` (host close when lent). Code commits
  do not.
- Face: find via `ownChild(dropdownHost, "[data-search-select-face]")`,
  optional. Open click → `dropdownHost.open(openButton)`. `syncFace` beside
  `syncClearButton`: value text/muted, × mirrors widget × hidden; × click →
  widget × click → focus open button. `MutationObserver` on search box for
  `disabled`, `aria-invalid`, `aria-required`, `aria-describedby`.
  `syncExpanded` writes open button `aria-expanded`. Labels: `search.labels`
  → id it if missing, open button `aria-labelledby="<label> <value>"`, label
  click below sm (face visible) → open. Sheet title text on connect.
- `rewriteDialogCreate` queries the host for both links; no report when
  only one exists; listen `form-dialog:created` on the face too.
- Tests: hand-built host with face and sheet; sync per state; × proxy;
  disabled mirror; lent `hidePanel`; sole-option commit keeps sheet; pick
  closes; multi pick keeps; leave work after hide.

## Task 5 — form-dialog hands a face link's row to its picker

Files: `ts/elements/form-dialog.ts`, `ts/elements/form-dialog.test.ts`.

- `handOver`: picker = `link.closest(PICKER) ?? ownChild(link.closest("drop-down"), PICKER)`.
- Test: face link with no listener → declined report.

## Task 6 — e2e

Files: `e2e/test_game_form_catalog_e2e.py` (390 px helpers open the face
first), new `e2e/test_picker_sheet_e2e.py`.

- 375 px: form picker face → sheet, box focused, pick closes, face shows
  value, focus on face; face × clears; sole-option picker stays open
  (session form run picker); builder `FilterSelect` sheet; presets sheet;
  desktop width anchored unchanged; no console errors.

## Gotchas

- `make ts` before e2e; never run e2e beside `make dev`.
- `make lint-fix` sorts imports; `make vale` on comments.
- Face buttons sit inside forms: `type="button"` via `ControlButton` default.
- Filter builder clones templates: no server ids in face/sheet.
- Manual iOS Safari pass: hand to the user with a recipe.
