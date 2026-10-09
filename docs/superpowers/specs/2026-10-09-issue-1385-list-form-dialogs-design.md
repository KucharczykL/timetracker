# Form pages from lists open in a modal

A form page that a list opens, opens in a form dialog
(`form_dialog_link()`). The page stays reachable at its own URL. No route
or response changes. `render_page()` answers the dialog.
`FormDialogResultMiddleware` answers its redirect.

## Scope

These build sites mark their links:

| Build site | Links |
|---|---|
| `session_row_menu` | Edit, Record as historical playtime… (Duration-only rows) |
| `playthrough_rows._row_menu` | Edit |
| `record_row_menu` | Edit |
| `device_row_menu`, `platform_row_menu`, `game_row_menu` | Edit |
| `entry_row_menu` | Edit…, Add purchase…, both With details…, Edit how it left… |
| `purchase_items` | Edit purchase… |
| Library page `SummaryRow`s | Add, Add to library |
| `list_library` | Add to library |
| `NavbarLogButton` | Log game |

A shared row menu is marked on every page that renders it, Game detail
included. Game detail's own acts are not marked. A `ConfirmPage` is not
marked. A one-click POST stays a POST.

## Rules

- **The link chooses.** Each link passes `attributes=form_dialog_link()`,
  or takes it in the positional attribute slot of `ControlButton` or
  `Link`. No registry of routes exists, because the same route stays a
  page in a new tab.
- **`SummaryAction` has `attributes`.** It renders twice, as an overflow
  menu item and as a wide link. Both carry the same attributes.
- **A redirect between copy pages continues.** An end of an ended copy
  redirects to the end's edit page. A resume of a held copy redirects to
  the end page. Neither target is `READ_ONLY`, so the dialog fetches it.
- **A redirect to the origin on open is a toast.** The open answers
  `done`. No dialog opens.
- **Log game opens on every page.** On a host that is not `READ_ONLY`,
  `done` shows its messages in place. A `READ_ONLY` host reloads.
- **Focus returns to a reachable link.** `focusOpener` takes the opener
  by id first. Then it takes the first link with the href whose return
  target is reachable. Else it takes `#main-container`. A focus that does
  not land is reported. A `SummaryRow` renders its overflow item first.
  At wide widths that menu is not rendered.
- **`isRendered` is shared** (`ts/rendered.ts`). It reads
  `checkVisibility()`. A browser without `checkVisibility()` reads
  `[hidden]` only. The app supports no such browser.
  `isReachable` is `isRendered`, not inside `[hidden], [inert]`, and not
  in a closed dialog.

## Verification

`tests/test_form_dialog_links.py` renders each build site and checks
which links carry the marker. `e2e/test_list_form_dialogs_e2e.py`
presses each real link. It checks that the dialog opens. An invalid
submit stays in the dialog. A save closes the dialog, reloads the host
and returns focus. Where the act removes the opener, focus goes to
`#main-container`. The price form's `x-mask` works inside
the dialog. At phone width, "With details…" in a sheet level closes the
sheet chain and opens the dialog.
