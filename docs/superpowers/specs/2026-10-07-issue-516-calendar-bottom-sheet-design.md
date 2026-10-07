# A dropdown panel opens as a bottom sheet on narrow viewports

Part of #1485. Issue #516. #1537 uses the same switch for the form pickers.

## Users

Every calendar (`DatePicker`, `DateTimePicker`, `DateRangePicker`,
`YearPicker`) and every quick-bar facet opens its panel as a bottom sheet
below 640 px. Above 640 px, the panel stays an anchored popup.

## Markup

A builder opts in with a sheet title: `_assemble(sheet_title=...)`,
`Dropdown(sheet_title=...)`, `ComboboxDropdown(sheet=True)`, or
`dropdown_sheet(title)` beside the picker inside `_Dropdown`. The host then
contains two extra nodes:

- A sheet dialog, `[data-dropdown-sheet]`, with an empty body. The client
  gives its title an id on connect, because the filter builder clones
  templates.
- A sentinel, `[data-dropdown-narrow]`, with the classes
  `hidden max-sm:block`. A rect on the sentinel means "narrow". If the
  stylesheet does not have the rule, the dropdown keeps the anchored popup.

`SHEET_ATTRIBUTES` names these attributes, and `SHEET_HOST_VALUE` names
the host value. The codegen writes both to TypeScript. A test holds the
Tailwind variants to them.

## Switch

`DropdownElement` wraps the controller of the behavior with
`attachNarrowSheet` (`ts/elements/narrow-sheet.ts`).

- The switch reads the sentinel when the panel opens.
- If narrow, the switch moves the panel node into the sheet body. The
  panel is out of the top layer while it is in the sheet
  (`releaseFromTopLayer`). Then the switch opens the sheet.
- If the modal layer refuses the open or throws, the switch puts the panel
  back at once.
- When the sheet closes, the switch puts the panel back before
  `dropdown:hide`, and the panel becomes a closed manual popover again
  (`returnToTopLayer`).
- If a window resize moves the viewport across the breakpoint while the
  panel is open, the switch moves the panel to the other host. The panel
  stays open. A close cancels a pending move. A move fires `dropdown:hide`
  and `dropdown:show` again, so a facet's search box starts empty.
- One state names the switch: closed, anchored, sheet, or moving.
- A half-built sheet is reported, and the dropdown stays anchored.
- `attachMenu` keeps its own open state, because the panel is visible in the
  sheet while the anchored controller is closed.
- `attachMenu` sends its toggle click and its arrow-key opens through
  `presenter`, so the switch decides each open.

`attachSheetCore` is a sheet with no toggle. It does not write
`aria-expanded`. Its hooks run in this order: `beforeShow`, `dropdown:show`,
`beforeHide`, `dropdown:hide`, `afterHide`. The `sheet` behavior adds its
toggle and same-page navigation on top of the core. The opener goes through
`open(opener)`. Safari does not focus a tapped button, so focus returns to
the opener. `sheetFocus` on a behavior gives the first focus in the sheet:
the selected day for a calendar, the search box for a facet.

## Look and actions

A panel in a sheet has `data-dropdown-host="sheet"` and the class
`group/dropdown`. The variants on its own classes remove its surface. In a
calendar, the day grid fills the width, and the range presets wrap in a row
above the grid.

The date and date-time calendars show Close in the sheet only. The anchored
popup closes on an outside press. Every facet panel ends with Apply, which
submits the bar. A date facet puts Apply in the footer of its calendar.

A form dialog counts only its own forms. It ignores a form in a nested
dialog, for example the Undo form of a toast.
