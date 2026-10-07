# A field picker opens as a bottom sheet on a phone

Part of #1485. Issue #1537. It uses the narrow-viewport switch of #516
(`2026-10-07-issue-516-calendar-bottom-sheet-design.md`).

## Problem

A field picker shows its list below its search box. On iOS Safari the
keyboard makes the visual viewport smaller, and the list covers the box.

## Scope

Every `SearchSelect` and `FilterSelect` that `_inline_combobox_host` holds:
form pickers, fixed-choice pickers, the builder's pickers and the
`ChoicePicker` controls. A picker in a quick-bar facet sheet opens a second
sheet on top. The Presets panel and `TimeZoneRow` also open as sheets.

## The face

Below `sm`, the host shows a face, and the widget is hidden. The face is the
widget's own field box: its text area is a button, and it holds the box's ×
and +. The server writes the held label, or `none_label`, or the
placeholder. The widget keeps the face current: the held value, a typed
draft in the uncommitted look, or the placeholder. It copies `disabled`,
`aria-invalid` and `aria-describedby` from the search box. A hidden span
gives the field name, so the button name is "Field, value". A click on the
field label opens the sheet. A + on the face gives its created row to the
widget.

## The lent widget

A tap on the face moves the whole `<search-select>` into the sheet. A modal
makes the page inert, so a list alone would lose the focus of its box. The
switch stamps `data-dropdown-host="sheet"` before the move in and removes
the stamp after the move back.

While the widget has the stamp:

- `hidePanel` does not close the host, so a code commit keeps the sheet open.
- A person's single-select pick closes the sheet. A multi-select or filter
  pick does not.
- `focusout` does nothing. The leave work (revert, pending search) runs once
  on the host's `dropdown:hide`.
- The sheet controls the list height, and the search box stays at the top.
- The + of the box is hidden.

## The switch

`attachNarrowSheet` takes the node to move (`sheetLent`) and a focus target
for an open with no opener (`sheetOpener`). If the modal layer refuses an
open because a modal is closing, the switch tries again one time when the
layer is stable (`whenSettled`). While a sheet is open, it writes
`--sheet-keyboard-inset` and `--sheet-visible-height` from `visualViewport`.
The sheet panel uses them as its bottom margin and its height limit.

## Label panels

The `combobox` behavior closes its dropdown when its own single-select
picker reports a pick or none. `ComboboxDropdown` takes a `sheet_title`, so
a title does not include a value.

## Tests

Vitest covers the switch, the face and the lent widget. Pytest covers the
markup. E2E tests at 375 px cover a pick, a clear, Escape and the Presets
sheet. The e2e helpers wait for a closing sheet to finish. A manual iOS
Safari test covers the keyboard.
