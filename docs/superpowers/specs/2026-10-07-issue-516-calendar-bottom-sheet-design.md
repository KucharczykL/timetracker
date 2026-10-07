# A dropdown panel becomes a bottom sheet on narrow viewports (#516)

Part of #1485. #1537 reuses the switch for the picker panels.

## Decisions

Settled with the user (UI) and the modal epic organizer (shape), 2026-10-07.

1. **The switch is a `<drop-down>` opt-in, not a behavior.** A builder that
   passes a sheet title renders two extra children inside the `<drop-down>`
   host: a sheet dialog and a wide sentinel. A dropdown without one renders
   neither and behaves as today.
2. **Breakpoint: below `sm` (640 px).** The sentinel is
   `Span(data_dropdown_wide="", class_="hidden sm:block")`. JavaScript reads
   `getClientRects().length > 0` and never repeats the breakpoint. No rect
   means the sheet, a hidden ancestor included; every open today needs a
   visible toggle.
3. **One panel node, two hosts.** The `[data-menu]` panel stays one node.
   An open while the sentinel is hidden records the panel's parent and next
   sibling, moves the panel into the sheet body, calls
   `releaseFromTopLayer(panel)`, sets `data-dropdown-host="sheet"` on it, and
   opens the sheet. If the modal layer refuses the open (it answers false) or
   throws, the switch puts the panel back in a `finally`: the tap is dropped,
   never answered with an anchored popup. When the sheet closes, the switch
   puts the panel back, calls `returnToTopLayer(panel)` and removes
   `data-dropdown-host`, before `dropdown:hide` is dispatched.
   `releaseFromTopLayer` and `returnToTopLayer` (`surface-stack.ts`) remove
   and restore `popover="manual"` and `hidden`, so only top-layer helpers
   write `hidden`. The attribute returns before any later `hidePopover`,
   which throws on an element with no `popover`.
4. **The mode is chosen at open.** While the dropdown is open, a window
   `resize` that changes the sentinel moves the panel: the switch closes the
   open host and, on that host's `dropdown:hide`, reads the sentinel again
   and opens the host it names. A `close()` or a disconnect while a move is
   pending drops the move. The iOS keyboard changes only `visualViewport`,
   not the layout width, so it never moves the panel.
5. **`attachSheet` splits.** `attachSheetCore(host, dialog, options)` owns
   the modal-layer seat, the slide, `data-sheet-state` and the
   `dropdown:show`/`dropdown:hide` events. It binds no toggle and writes no
   `aria-expanded`. Its `open(opener)` passes the opener to the modal layer,
   because Safari does not focus a tapped button and the date field's
   `[data-toggle]` is a `<div>`. Options: `initialFocus`; `beforeHide`, run
   on close before `dropdown:hide`; `afterHide`, run after it. The `sheet`
   behavior's `attachSheet` keeps today's order on top: toggle click,
   `aria-expanded="false"` in `beforeHide`, same-page navigation in
   `afterHide`.
6. **The opener reaches the switch.** `MenuController.open(opener?)` and
   `DropdownElement.open(opener?)` take an optional opener;
   `bindCalendarPopupHost` passes its calendar button. Focus returns there
   from the sheet, and from the anchored popup too: `attachMenu`'s
   `restoreFocus` focuses the opener, else the toggle. Today Escape on the
   anchored calendar drops focus to the body, because the toggle is a
   `<div>`.
7. **Initial focus in the sheet** is the selected day, else today, else the
   sheet's ×. Today is in the grid only when the view shows its month. A behavior states it with `sheetFocus(menu)` in its
   `DropdownBehavior`; `date-calendar` does. #1537 states its search box the
   same way.
8. **The panel carries its own sheet look.** Its classes state the sheet
   look under `data-[dropdown-host=sheet]:` and
   `group-data-[dropdown-host=sheet]/calendar:` variants. Nothing outside
   the panel styles it.

## What the switch catches

The switch wraps the controller `DropdownElement` holds, so it decides
every open that goes through `DropdownElement.open()`. An `attachMenu`
without `inlineTrigger` also opens itself from its toggle's click and arrow
keys, and those opens bypass the wrapper. The three calendars set
`inlineTrigger`. #1537 routes those internal opens through the switch for the
behaviors that bind their toggle.

## Shape

- **Python.** `BottomSheet` keeps its markup. Its dialog and panel move into
  `sheet_dialog(...)`, which also builds the dropdown sheet with an empty
  `[data-sheet-body]`, `data-dropdown-sheet` and no `data-bottom-sheet`
  (section-nav and two e2e files select that attribute alone). Its height
  cap is `max-h-[90dvh]`, so the range calendar's footer stays in view; the
  section sheet keeps `max-h-[min(80dvh,32rem)]`. `dropdown_sheet(title)`
  answers the dialog and the sentinel as one `Fragment`.
  `ModalPanelHeader` and `titled_header` take `title_id=None`, which omits
  the id and `aria-labelledby` (an attribute value is never `None`). The
  dropdown sheet uses it: the switch stamps a counter id on the title and
  the dialog's `aria-labelledby` at connect, so the filter builder's cloned
  templates never share one. `DatePicker`, `DateTimePicker` and
  `DateRangePicker` call `_Dropdown(...)[picker, dropdown_sheet(label)]`,
  the sheet after the picker. `DateRangePanel` and `YearPicker` pass
  nothing: one lives inside the quick bar's own dropdown, the other is
  224 px wide. `sheet_dialog` stays in `custom_elements.py`, the module
  `tests/test_modal_dialog.py` admits for `ModalDialog(`.
- **Attribute names are generated.** `DROPDOWN_SHEET_ATTRIBUTES` in
  `custom_elements.py` names `data-dropdown-sheet`, `data-dropdown-wide`,
  `data-dropdown-host` and `data-sheet-body`; `make gen-element-types`
  writes `ts/generated/dropdown-sheet-attributes.ts`, as it writes the modal
  attributes.
- **TypeScript.** `DropdownElement.connectedCallback` builds the behavior's
  controller as today. When it finds an own `[data-dropdown-sheet]` and an
  own `[data-dropdown-wide]`, it wraps the controller with
  `attachNarrowSheet` (`ts/elements/narrow-sheet.ts`), which answers the
  same `MenuController`. A behavior with `createController` and a sheet is
  a defect, reported with `reportClientError`. `DropdownElement` gains
  `isOpen()`.
- **In the sheet the panel is outside the picker element.** Every panel
  reference is captured at init; a later `picker.querySelector` for a part
  of the panel finds nothing.
- **`attachMenu` keeps its own open state.** `isOpen()` and `reposition`
  read a flag `open()` and `close()` set, not `menu.hidden`. Reason: the
  panel in the sheet is unhidden while the anchored controller is closed;
  its `focusout` and Tab handlers must not hide it there.
- **`bindCalendarPopupHost`** reads `dropdownHost.isOpen()`, not the panel's
  `hidden`, and syncs `aria-expanded` on `dropdown:show` as well as on
  `dropdown:hide`, because a move fires both.
- **Form dialog baseline.** `formsOf` in `form-dialog/unsaved.ts` counts only
  forms whose nearest dialog is the form dialog. A toast moves into the top
  modal, and a sheet inside the page form would otherwise add its Undo form.
- **Calendar look in the sheet.** The shell drops its border, corners,
  surface and blur, and stacks its children in a column. The grid takes
  `w-full`, a definite width, so Firefox does not shrink its tracks. The
  weekday header and day cells take `w-auto` and fill seven equal tracks.
  The client overwrites every cell's classes from the generated
  `CALENDAR_DAY_CLASSES` and `CALENDAR_WEEKDAY_CLASS`, so the variant goes
  into `_DAY_CELL_GEOMETRY_CLASS` and the weekday string, and
  `make gen-element-types` runs.
  Range presets wrap as one row above the grid (`w-auto` each), with a
  bottom divider instead of the end divider.

## Out of scope

- A picker panel in a sheet (search box at the sheet top, closing on an
  item pick, internal opens, `visualViewport` sizing): #1537.
- Touch-friendly time entry.

## Tests

- Python: the three pickers each render one `[data-dropdown-sheet]` titled
  by the label and one sentinel; `Dropdown` and `YearPicker` render neither;
  `BottomSheet` markup is unchanged.
- Vitest: `attachNarrowSheet` opens anchored or in the sheet by the
  sentinel; the panel moves and returns with its attributes; a refused open
  puts it back; a resize while open moves it and a close drops the pending
  move; ids are stamped per instance. `attachMenu.isOpen()` stays false
  while the panel sits unhidden in the sheet. The sheet core keeps
  `attachSheet`'s order.
- e2e at 375 px and desktop width: a date field opens a sheet or the popup;
  a day pick commits and closes; focus returns to the calendar button; the
  range sheet shows its footer; a date field in a form dialog stacks a
  sheet over the dialog; a resize keeps an open calendar open. Locators
  scope by `drop-down`, not by the picker. The 390 px touch-target test now
  measures the sheet.

## Follow-up issues to file

None.
