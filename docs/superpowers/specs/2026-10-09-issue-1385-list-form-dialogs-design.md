# Form pages from lists open in a modal

Slice 1 of #1385. A form page that a list's row menu, a list or landing
Add action, or the navbar's Log game opens, opens in a form dialog
(`form_dialog_link()`, #1384). The page stays reachable at its own URL.
No view changes: `render_page()` answers the dialog and
`FormDialogResultMiddleware` answers its redirect.

## Scope

Marked links, by build site:

| Build site | Links | Renders on |
|---|---|---|
| `session_row_menu` | Edit, Record as historical playtime… | Sessions list |
| `playthrough_rows._row_menu` | Edit | Playthroughs list, Game detail |
| `record_row_menu` | Edit | Historical list, Game detail |
| `device_row_menu` | Edit | Devices list |
| `platform_row_menu` | Edit | Platforms list |
| `game_row_menu` | Edit | Games list, Game detail add-ons |
| `entry_row_menu` | Edit…, Add purchase…, end With details…, Edit how it left…, resume With details… | Library list, Game detail |
| `purchase_items` | Edit purchase… | Purchases list, copy menus |
| Library page `SummaryRow`s | Add (game, platform, device), Add to library | Library page |
| `list_library` | Add to library | Library list |
| `NavbarLogButton` | Log game | every signed-in page |

A shared row menu is marked wherever it renders, Game detail included.
Game detail's own acts (section Adds, header, its Add to library) are
slice 3, after #1383. Every `ConfirmPage` (`remove_*`, `reset_session`)
is slice 2. `reclassify_session` is a form page, not a confirmation, so
it is here. A one-click POST stays a POST.

## Decisions

- **Mark at the build site.** Each link passes `attributes=form_dialog_link()`
  (`DropdownLinkItem`) or takes it in the positional attribute slot
  (`ControlButton`). No registry of dialog routes: the link, not the
  route, chooses, because the same route stays a page in a new tab.
- **`SummaryAction` takes `attributes`.** It renders twice, as an
  overflow menu item and as a wide link; both carry the same attributes.
  A field of type `Attributes`, default `()`, keeps every other caller
  unchanged.
- **A redirect between copy pages continues.** `end_library_entry` on an
  ended copy redirects to `edit_library_entry_end`, the reverse, and
  `resume_library_entry` on a held copy to `end_library_entry`. None is
  `READ_ONLY`, so the dialog fetches the target in place.
- **A redirect to the origin on open is a toast.** `edit_playthrough` on
  a run whose dates the form cannot hold redirects to the origin with an
  error. The open answers `done`; the error shows as a toast and no
  dialog opens.
- **The navbar's Log game opens on every page.** On a host that is not
  `READ_ONLY` (a form page at its own URL), `done` shows its messages in
  place and nothing reloads, as #1384 states. A `READ_ONLY` host such as
  the filter builder reloads and drops unsaved builder edits, as the
  navigation did before.
- **Focus finds a link that shows.** A Library page `SummaryRow` renders
  each action twice, the overflow item first; at wide widths that menu
  is `display: none`. `focusOpener` takes the first link with the href
  whose return target is visible, and `isReachable` refuses an element
  that is not rendered. Before, focus stayed on `body`.
- **`isRendered` is shared.** `isShown` moves out of
  `selectable-table.ts` unchanged, renamed `isRendered` (`menu.ts` has
  another `isShown`): `checkVisibility()` where the engine has it,
  `[hidden]` in jsdom, which has none. `isReachable` becomes
  `isRendered(element)`, not inside `[hidden], [inert]`, and its dialog
  open; `inert` and a closed dialog are not visibility. Its third
  caller, `sheet-controller.ts`, then refuses to open a sheet whose
  trigger a class hides at wide widths, which its comment already
  means. An element with no box (`display: contents`) is not rendered;
  no opener is one.

## Verification

Each converted page gets an e2e that presses the real link (no
`_mark`), and checks: the dialog opens titled; an invalid submit stays
in the dialog with an invalid control; a refused act renders its
sentence in the dialog where the form has one; a save closes the
dialog, reloads the host and returns focus to the opener or its row
menu's toggle. Where the act removes the opener (an end, a resume, a
move off Game detail), focus goes to `#main-container`. A refusal is a
toast inside the dialog on `form_page` pages, the session and record
pages; a field error on the device and platform pages. The price form
types into its `x-mask` input inside the dialog, which proves Alpine
starts the mask on insertion; `test_a_masked_field_works_inside`
already covers the session form. The settings form's mask is not on a
converted page.

A phone-width e2e opens a copy's "I no longer have it" level, presses
"With details…", and checks that the sheet chain closes and the form
dialog opens (#1559's settle).

`test_session_reclassification_e2e.py` presses the real item; it moves
into the dialog and keeps its Undo, which the `done` handoff carries
across the reload.

Existing e2e that press these links and wait for a navigation move into
the dialog: the device and platform bulk-removal edits, the Library
tab's end, the dropdown sheet's Edit, the Library section's end and the
historical playtime edit. Their locators scope to the dialog. The hand
marks on the device Edit link (`_mark` in `test_form_dialog_e2e.py`,
`test_motion_e2e.py`) go.

A new test in `test_dialog_create_e2e.py` opens Add session from the
navbar, opens Add game from its picker, and asserts the top dialog's
trail reads "Add New Session" (#1514). The existing page-URL test
stays.

`make render-pages` runs before and after; the diff holds only the
marker attributes and the busy class.

## Follow-up issues to file

None. Slices 2 and 3 are already recorded in #1385.
