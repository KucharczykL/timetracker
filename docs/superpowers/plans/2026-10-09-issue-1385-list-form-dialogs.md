# Plan: form pages from lists open in a modal (#1385 slice 1)

Spec: `docs/superpowers/specs/2026-10-09-issue-1385-list-form-dialogs-design.md`.

## Task 1: `isRendered` and focus

- New `ts/rendered.ts` (or beside `utils.ts`): `isRendered(element)`, the
  body of `selectable-table.ts`'s `isShown`, exported. `selectable-table.ts`
  imports it; its own copy goes.
- `ts/elements/modal-layer.ts` `isReachable`: add `isRendered(element)`,
  keep `[hidden], [inert]` and the dialog-open conjunct.
- `ts/elements/form-dialog/opener.ts`: `focusOpener` walks every
  `a[href]` with the key's href and takes the first whose
  `focusReturnTarget` is non-null; by-id first as now.
- Vitest: `rendered.test.ts` (stubbed `checkVisibility` false → false;
  absent → `[hidden]` rule). `opener.test.ts` (exists? else new): two
  links with one href, the first's toggle unrendered (stub) → focus the
  second. `modal-layer.test.ts`: an opener whose `checkVisibility` stub
  answers false falls to its toggle.

## Task 2: `SummaryAction.attributes`

- `common/components/library_kit.py`: `attributes: Attributes = ()` on
  `SummaryAction`; `_summary_action_menu` passes it to
  `DropdownLinkItem(attributes=...)`; the wide `Link` takes it in the
  positional slot.
- `games/views/library.py`: `_actions` marks Add; Add to library marked.
- Test in `tests/test_library_ui_components.py`: both renders carry
  `data-form-dialog`.

## Task 3: mark the links

`attributes=form_dialog_link()` on:

- `session_menu.py`: Edit, Record as historical playtime…
- `playthrough_rows.py` `_row_menu`: Edit
- `historical_playtime.py` `record_row_menu`: Edit
- `device_menu.py`, `platform_menu.py`, `game_menu.py`: Edit
- `entry_menu.py`: both With details…, Edit how it left…, Edit…, Add purchase…
- `purchase_menu.py` `purchase_items`: Edit purchase…
- `library_list.py`: Add to library `ControlButton` (positional slot)
- `common/layout.py` `NavbarLogButton` primary (positional slot)

Unit: one parametrized test (`tests/test_form_dialog_links.py`) renders
each builder and asserts the named links carry `data-form-dialog` and
Remove/Reset/one-click POSTs do not.

## Task 4: e2e

New `e2e/test_list_form_dialogs_e2e.py`, real links only. Per page:
open titled; invalid submit stays with an invalid control; save closes,
reloads (`window.notReloaded` stamp), focus on the row menu toggle.

- Sessions list: Edit (refusal toast: move to a run on an untracked game?
  pick a simple one, e.g. end before start), Record as historical
  playtime.
- Playthroughs list Edit; Historical list Edit; Platforms Edit (field
  refusal: duplicate name); Games list Edit.
- Library list: Edit…, Add purchase… (type into currency mask: lowercase
  becomes uppercase), end With details… → focus `#main-container`.
- Purchases list: Edit purchase….
- Library page: Add device at wide width → focus on the wide link.
- Navbar Log game from the Games list.
- Phone width: entry menu level → With details… → sheet closed, dialog open.

Existing to rework: `test_bulk_device_removal_e2e.py:52`,
`test_bulk_platform_removal_e2e.py:51`, `test_library_tab_e2e.py:189`,
`test_dropdown_sheet_e2e.py:274`, `test_library_section_e2e.py:87`,
`test_historical_playtime_entry_e2e.py:51`,
`test_session_reclassification_e2e.py:35`; drop the hand marks in
`test_form_dialog_e2e.py` and `test_motion_e2e.py:81`.
`test_dialog_create_e2e.py`: new navbar test with trail "Add New Session".

## Gotchas

- `make ts` after TS edits before e2e.
- `make render-pages` before (on main) and after; diff = markers only.
- Never run e2e while `make dev` is up.
- Locators inside dialogs: `page.locator("dialog[data-modal][open]").last`.
