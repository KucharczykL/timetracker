# Every dropdown opens as a bottom sheet on a phone

Part of #1485. Issue #1559. It extends the switch of #516 and #1537, and
moves on the tokens of [Motion](2026-10-09-issue-1559-motion-design.md).

## Rule

Every `<drop-down>` opens its panel as a bottom sheet below `sm`
(640 px). There is no opt-out. `behavior="sheet"` (`BottomSheet`) has its
own controller and stays as it is. Above `sm`, nothing changes.

## Titles

Every build site states its title in Python. `Dropdown` and `_assemble`
take a required `sheet: SheetSpec`; `_assemble` alone takes `None`, and
only for `behavior="sheet"`. A raw `_Dropdown` site puts
`dropdown_sheet(...)` beside its picker, as today.
`SheetSpec.named_on_connect()` stays for a widget that writes its own
title; no other title comes from the client.

| Site | Title |
| --- | --- |
| `RowActionMenu` | its `label` |
| `ButtonDropdown` | `aria_label`, else `label` |
| `SplitButtonDropdown` | `aria_label`, now required |
| `SelectDropdown` | a new required `sheet_title`: "Status", "Device" |
| `DropdownSubmenuItem` | its `label` |
| `AccountMenu` | the user name |
| Match mode menu | "Match" |
| Column picker | "Columns" |
| `IconPicker` | its `label` |
| `ComboboxDropdown` | its `label`; `sheet` becomes required |
| Quick-bar overflow | `OVERFLOW_LABEL` |
| Selection-line overflow | "More actions" |

`tests/html_answers.py` refuses an HTML answer with a `<drop-down>` that
has no own `[data-dropdown-sheet]` and is not `behavior="sheet"`. It
parses the answer, because a `<drop-down>` holds others (the overflow
holds facets) and a pattern cannot tell its own child from theirs.

## First focus

`sheetFocus` names the first focus in the sheet:

- `menu`: the first enabled item of its own menu; else the first
  tabbable control in the panel (an overflow panel holds triggers and
  buttons, not items). Arrow keys rove in the sheet, as in the popup.
- `select`: the selected option, else the first.
- `choice-grid`: the checked radio, else the first.
- `column-picker`: the first checkbox.

## Levels

A `<drop-down>` that opens narrow inside an open dropdown sheet
(`host.parentElement.closest("dialog[data-dropdown-sheet]")`, open in
the modal layer) opens its own sheet dialog as a **level** of that
sheet. A dropdown inside a form dialog still stacks a plain sheet,
because a form dialog is not a dropdown sheet.

A level is still its own `<dialog>`, a modal of the layer, so its lent
node stays inside its own host. Every `closest("drop-down")` lookup
(`inline-combobox` focus, search-select's create scope, the calendars,
the match menu, `focusReturnTarget`) keeps working, and a searchable
level keeps its own fixed height. Only its look differs: one sheet whose
content changes.

- **In:** the level's panel slides in from the right, from the height of
  the panel below to its own. The panel below slides left and becomes
  `visibility: hidden` (its sentinel keeps its rect). Focus moves to the
  level's `sheetFocus`.
- **Look:** the level dialog carries `data-sheet-level`. A level does
  not count as covering: the dialog below keeps its dim and gets no
  depth step, no `--modal-reserve` and no covered mark; the level's own
  backdrop is transparent. A level has no trail, and a form dialog over
  the sheet names no level in its trail.
- **Header:** a back control leads the header. It shows
  "‹ <title below>", is named "Back to <title below>", and is hidden on
  a sheet that is not a level. Each dialog keeps its own title and
  `aria-labelledby`, so no dialog is renamed.
- **Back:** the back control, Escape, the Android back gesture (all a
  native `cancel`) and the level's own `close()` close the level. It
  slides out to the right; the panel below slides back. The modal layer
  returns focus to the row that opened it. A single-select pick closes
  its host, so it goes back one level.
- **Close:** × and the backdrop close the whole sheet through a new
  layer call, `closeTogether(first)`. Every sheet from the first up
  leaves at once; only the top level runs its slide; the first sheet's
  dim fades. When the top finishes, the layer finishes them all in the
  same task, top first, so each lent node returns home before the node
  that holds it, and no frame shows a level below.
- **Focus:** a modal the layer finishes because one below it closes
  returns no focus. So a whole close returns focus once, to the first
  sheet's opener, and no picker box below takes focus and opens again.
  A menu item that acts
  (`role="menuitem"` with no `aria-haspopup`) in a level closes the
  whole sheet the same way. When a sheet below closes for another
  reason (a widen, the quick bar emptying its overflow, a disconnect),
  the layer's `closeAbove` finishes its levels first, without focus.
- **Modal layer:** `ModalOptions` gains `cancel`, the native-cancel hook,
  which defaults to `dismiss`. A level states `cancel` (back) apart from
  `dismiss` (whole sheet).
- **Switch:** a level does not move hosts on resize; the first sheet
  does, and its close closes the levels.
- **Motion:** the iOS push of [Motion](2026-10-09-issue-1559-motion-design.md).
- **Submenu:** a submenu's click and ArrowRight open through `presenter`,
  so the switch decides; today the click opens anchored. While its
  parent menu is in a sheet, `pointerenter` and `pointerleave` open and
  close nothing.

## A form dialog from a sheet

A menu item that is a form-dialog link closes the sheet first.
`<form-dialog>` waits with `whenSettled` until no modal leaves, then
opens. The dialog opens over the page, not over the leaving sheet.

## Facets

A facet with no list (number, string, bool, group) shows no divider
above Apply in a sheet. A set facet keeps it.

## Tests

Vitest covers the level stack, the switch and the behaviors. E2E at
390 px covers a row menu, a submenu level, the overflow → facet → picker
chain, a form dialog opened from a sheet menu, and the select dropdowns.

## Follow-up issues to file

- None.
