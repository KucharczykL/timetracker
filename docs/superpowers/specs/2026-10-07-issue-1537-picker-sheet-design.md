# A field picker opens as a bottom sheet on a phone

Part of #1485. Issue #1537. It uses the narrow-viewport switch of #516.

## Problem

A field picker shows its list below its search box. On iOS Safari the
keyboard makes the visual viewport smaller, and the list covers the box.

## Scope

Every `SearchSelect` and `FilterSelect` that `_inline_combobox_host` holds:
form pickers, fixed-choice pickers, the builder's pickers and the
`ChoicePicker` controls. A picker in a facet sheet opens a second sheet on
top. The Presets panel and `TimeZoneRow` also open as sheets.

## The face

Below `sm`, the host shows a face and hides the widget. The face has the
look of the widget's field box, and its text area is a button. Its own ×
presses the box's ×, and its own + gives its created row to the widget. A
`FilterSelect` face has no × and no +. The face shows the held value (or
`none_label`), a typed draft in the uncommitted look, or the placeholder.
The widget copies `disabled`, `aria-invalid` and `aria-describedby` to it.
A hidden span gives the button the name "Field, value", and the widget
writes the field name into the empty sheet title. A click on the field
label opens the sheet. If the sheet cannot attach, the host is stamped
`sheetless` and the widget shows instead of the face.

## The lent widget

A tap on the face moves the whole `<search-select>` into the sheet. A modal
makes the page inert, so a list alone would lose the focus of its box. The
switch stamps `data-dropdown-host="sheet"` before the move in and removes
the stamp after the move back.

While the widget has the stamp:

- `hidePanel` does not close the host: a code commit keeps the sheet open.
- A person's single-select pick, or a pick of none, closes the sheet. A
  multi-select or filter pick does not.
- `focusout` does nothing. The leave work (revert, pending search) runs once
  on `dropdown:hide`, but not when the sheet only changes hosts.
- The sheet has a fixed height, so a filter does not move the box.
- The + of the box is hidden.

## The switch

`attachNarrowSheet` takes the node to move (`sheetLent`) and a focus target
for an open with no opener (`sheetOpener`). If the modal layer refuses an
open because a modal is closing, the switch tries again one time when the
layer is stable (`whenSettled`). While a sheet is open, it writes
`--sheet-keyboard-inset` and `--sheet-visible-height` from `visualViewport`.
The sheet panel uses them as its bottom margin and its height limit. A
sheet whose content holds a search box is steady (`data-sheet-steady`,
stamped by `attachNarrowSheet`) and fills the screen. See
[Every dropdown opens as a bottom sheet](2026-10-09-issue-1559-sheet-by-default-design.md).

## Label panels

The `combobox` behavior closes its dropdown on a person's pick, changed or
not (`search-select:pick`). The Presets panel, `TimeZoneRow` and set facets
have steady sheets. In a sheet, a panel's list stops above its
footer, so a facet's Apply stays in view.

## Tests

Automated tests cover all of this except the iOS keyboard, which is checked
by hand on iOS Safari.
