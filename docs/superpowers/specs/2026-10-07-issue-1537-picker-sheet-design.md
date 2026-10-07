# A picker opens as a bottom sheet on a phone

Part of #1485. Issue #1537. Builds on #516's narrow-viewport switch
(`docs/superpowers/specs/2026-10-07-issue-516-calendar-bottom-sheet-design.md`).

## Problem

A field-hosted picker (`<drop-down behavior="inline-combobox">`) anchors its
list under its own search box. On iOS Safari the keyboard shrinks the visual
viewport, and the anchored list covers the box the person types in.

## Scope

- Every `SearchSelect` and `FilterSelect` that `_inline_combobox_host` wraps:
  form pickers, `ChoiceSearchSelectWidget`, the builder's field-layout
  `FilterSelect`, and `ChoicePicker` (the filter modifier and operator
  pickers). A `ChoicePicker` inside a quick-bar facet sheet opens a second
  sheet over it; the modal layer stacks them (#1514).
- `ComboboxDropdown` hosts that have no sheet yet: the Presets segment
  (`sheet_title=PRESETS_LABEL`) and `TimeZoneRow` (`sheet=True`). Their
  `combobox` behavior already names `sheetFocus`.
- Quick-bar facets are sheets since #516.
- `TimeZoneRow`'s sheet title is its trigger label, value included. That is
  `ComboboxDropdown`'s rule for every facet, and it stays.

## The face and the lent picker

Below `sm` the form shows a **face**, and the whole `<search-select>` element
moves into the sheet when it opens.

Moving only the list does not work. A modal sheet makes the page inert, so the
box in the form loses focus and the widget's `focusout` closes the list. The
widget also asks `container.contains(document.activeElement)`. When the whole
element moves, those checks and every listener stay intact, and the list moves
with it as a child.

The face (`[data-search-select-face]`) is a sibling of `<search-select>` inside
the `<drop-down>`, `hidden max-sm:flex`. The element is
`max-sm:not-data-[dropdown-host=sheet]:hidden`. The face renders server-side
with the held label (or `none_label`, or the placeholder in muted text), so no
blank face shows before upgrade. Its controls, all `type="button"` or links:

All three are `ControlButton`s (the button guard): the open button takes the
`outline` variant on a field-box shape.

- **Open button**, `aria-haspopup="dialog"`: the value and a chevron. A tap
  opens the `<drop-down>` with this button as the opener. The button takes no
  keyboard, so the keyboard first rises in the sheet.
- **×**, rendered only where the widget has its own ×, and shown exactly when
  the widget's × is shown (`syncClearButton` writes both). A tap clicks the
  widget's ×, then focuses the open button.
- **+**, a second `form_dialog_link` with the same href, rendered only with
  `dialog_create`. `rewriteDialogCreate` queries the host, so it rewrites
  both links. `form-dialog`'s `handOver` resolves the picker of a face link
  through its `<drop-down>` (`ownChild(..., "search-select")`), so a face +
  that nobody answers is reported as declined, not read as a plain link.
  The widget listens for `form-dialog:created` on the face as on itself. In the sheet the
  widget's own + is hidden (`in-data-[dropdown-host=sheet]:hidden`), so no
  form dialog opens over a picker sheet.

The widget keeps the face current. `syncFace` runs wherever
`syncClearButton` runs: the committed label or `none_label` for a
single-select, the pill labels joined with ", " for multi-select and filter
mode, else the placeholder. A `MutationObserver` on the search box copies
`disabled`, `aria-invalid`, `aria-required` and `aria-describedby` to the open
button, because `ChoiceControl.setDisabled` and the settings controls write
`search.disabled` directly. `syncExpanded` writes the open button's
`aria-expanded`.

The open button's name is the field's label and the value
(`aria-labelledby`; `FormFields` already ids the label through
`field_label_id`, and the widget ids one that has none). The
sheet title is the label's text, else the box's `aria-label`, else its
placeholder. Below `sm` the label's `for` names a hidden box, so a click on
the label opens the face by hand. Face and sheet are optional to the widget:
hand-built hosts in vitest have neither.

## Switch changes

- `attachNarrowSheet` takes `lent`, the node it moves into the sheet body
  (default: the menu). `PanelPlace` and `returnPanel` track `lent`. The menu
  is still released from the top layer; both nodes get
  `data-dropdown-host="sheet"`.
- `DropdownBehavior` gains `sheetLent(host, toggle, menu)` and
  `sheetOpener(host)`. `inline-combobox` names the toggle (the
  `<search-select>`) and the face's open button; `sheetFocus` finds the box
  through `menu.closest("drop-down")`. `sheetOpener` is used when an open
  states no opener: a wide-to-narrow move while open, and a code open.
- `_inline_combobox_host` adds `dropdown_sheet("")`; the widget writes the
  title on connect, before any modal can cover the sheet and read its name.
- An open that the layer refuses because another modal is leaving is retried
  once when the layer settles, so a tap on the next face during the previous
  sheet's slide is not lost.

## In the sheet

The sheet owns dismissal: the header ×, the backdrop, Escape. The widget
reads "lent" from the `data-dropdown-host="sheet"` stamp on itself, which
the switch writes before the move into the sheet and removes after the move
back. A flag set on `dropdown:show` is too late: `modal.open` focuses the box,
and `runFocus` runs, before `dropdown:show`. While lent:

- `hidePanel` does not close the host. Code commits (`commitTheSoleOption`,
  `holdValue`, `setSelected`, `form-dialog:created`), Tab onto the widget's ×,
  and `focusout` to the sheet's padding therefore leave the sheet open.
- A person's single-select pick (click or Enter on an option, the none row,
  the create row) closes the sheet. A multi-select or filter-mode pick keeps
  it open.
- `focusout` does no leave work. Both moves blur a focused box with no
  `relatedTarget`, and both happen while the stamp is on.
- The leave work (`revert_on_leave`, the pending search) runs once on the
  host's `dropdown:hide` after a lent period: the widget notes `wasLent`
  whenever a handler sees the stamp. An anchored hide stays as today: only
  `focusout` reverts.
- The listbox's inline `max-height` yields to the sheet
  (`group-data-[dropdown-host=sheet]/dropdown:max-h-none!`), so the list fills
  the sheet.
- The empty-list gate does not apply: the face opens the host directly.
- A picker inside a form dialog stacks its sheet over the dialog, which steps
  back as #1514 states, as a calendar sheet does since #516.

## Keyboard

iOS Safari does not shrink the layout viewport. While a dropdown sheet is
open, `attachNarrowSheet` reads `visualViewport` on `resize` and `scroll`
and writes `--sheet-keyboard-inset` (layout viewport bottom minus visual
viewport bottom) and `--sheet-visible-height` on the dialog. The sheet
panel's bottom margin takes the inset, and its height cap takes 90 % of the
visible height. Without `visualViewport` both have no effect. Focus moves
into the sheet synchronously inside the tap (`modal.open` calls
`focusInitial`), which iOS needs to raise the keyboard.

## Tests to change

- `e2e/test_game_form_catalog_e2e.py` runs at 390 px and types in the platform
  box: it opens the face first.
- `tests/test_search_select.py::test_serializer_contract_is_layout_invariant`
  drops the face and sheet hooks with the other host hooks.
- `tests/test_dropdown_sheet.py::test_every_quick_facet_carries_a_sheet`
  counts facet sheets only (own children of each facet's `<drop-down>`).

## New tests

- vitest: `attachNarrowSheet` with `lent` and `sheetOpener`; the viewport
  properties; the face (sync, ×, +, mirrored state, label click); a lent
  `hidePanel`; a person's pick against a code commit.
- pytest: the host renders face and sheet; presets and time zone rows have a
  sheet.
- e2e at 375 px: a form picker opens a sheet with its box focused; a pick
  closes it and the face shows the value; the face × clears; a sole-option
  picker stays open; a builder `FilterSelect` and the presets panel open as
  sheets; at desktop width the anchored list is unchanged.
- Manual: iOS Safari on an iPhone.

## Follow-up issues to file

None known.
