# In-house Stats YearPicker Design

## Context

Issue #99 replaces the stats page's last Flowbite-datepicker consumer. The
current `YearPicker` renders a toggle button and hidden input, then
`ts/elements/year-picker.ts` instantiates the vendored `Datepicker` UMD bundle
at `pickLevel: 2`. The bundle is loaded as component media and is currently
104,214 bytes.

The rest of the application's date controls have since moved to in-house
TypeScript elements. Single-date and range calendars use the shared
`<drop-down behavior="date-calendar">` host and the calendar lifecycle helpers
in `ts/elements/date-calendar-core.ts`.

## Goals

- Remove the stats page's dependency on `datepicker.umd.js`.
- Preserve the current YearPicker's public Python API and immediate-navigation
  behavior.
- Preserve the current twelve-cell year view, decade navigation, bounds, and
  `available_years` filtering.
- Adopt the existing dropdown positioning, dismissal, ARIA, and control styling
  machinery.
- Add unit, rendering, and browser coverage for the replacement.

## Non-goals

- Do not change the existing `DatePicker`, `DateRangePicker`, or
  `DateTimeField` implementations.
- Do not add a confirmation step, Clear button, Cancel button, or pending
  selection state.
- Do not generalize `date-calendar-core.ts` into a generic grid framework.
- Do not remove the separate global Flowbite bundle; that is issue #98.

## Design

### Server-rendered structure

Keep the existing public call unchanged:

```python
YearPicker(
    year=year_int,
    available_years=tuple(year_range or []),
    url_template=url_template,
)
```

Change the component to render a `<drop-down behavior="date-calendar">`
around the `<year-picker>` element. The YearPicker contains:

- a toggle button carrying both `data-toggle` for the dropdown and
  `data-year-picker-toggle` for the element;
- a hidden `[data-menu]` popup with the shared overlay surface styling;
- previous/next decade buttons;
- a decade-period label;
- a four-column year grid;
- a server-rendered `ControlButton` template cloned by TypeScript for each
  year cell.

The hidden input exists only to give Flowbite-datepicker an input anchor. It is
removed. The existing `selected-year`, `available-years`, and `url-template`
custom-element props remain the server/client contract.

The popup uses the same dropdown shape as the existing date pickers. Its
`placement` is `bottom-end`, its `submenu` prop is `false`, and its behavior is
`date-calendar` so viewport-aware positioning, outside-click dismissal,
Escape, Tab, and single-open coordination remain centralized.

### Client lifecycle

`year-picker.ts` reads the existing props, finds the toggle, popup, navigation
buttons, period label, and year-grid template, then calls
`bindCalendarPopupHost()` from `date-calendar-core.ts`.

The popup host's `beforeOpen` callback synchronizes the view from the selected
year (or the current year when there is no selection). Its `render` callback
fills the year grid before the dropdown opens, ensuring the positioning engine
measures the final popup dimensions.

Because `date-calendar` sets `inlineTrigger` and intentionally disables
dropdown item roving, the YearPicker supplies only the small trigger behavior
that the generic host cannot provide: ArrowDown opens the popup from the
trigger, and Escape closes it when focus remains on the trigger. The year cells
remain ordinary buttons, matching the existing date-calendar implementation;
native Enter/Space behavior is sufficient for selection. A small shared
`keepOpenOnTab` option for `date-calendar` lets Tab and Shift+Tab move through
all popup controls; a shared focus-leave handler closes the popup when focus
actually exits it. The shared host owns popup geometry, outside-click
dismissal, Escape/focus-leave handling, and single-open coordination. The
trigger renders `aria-expanded="false"` server-side and the helper updates it
when the popup opens or closes.

The element owns only year-specific behavior:

- decade view state;
- rendering the twelve year cells;
- previous/next decade navigation;
- enabled/disabled and selected cell state;
- immediate URL navigation after a valid selection;
- the small trigger keyboard gap described above.

The old body-mounted Flowbite popup and its bespoke `bindPopupDismiss()` path
are removed.

### Year view and selection rules

The year view keeps the useful existing twelve-cell layout without making the
new component a Flowbite keyboard clone:

- the grid has four columns and three rows;
- the exact cell sequence is `decadeStart - 1` through `decadeStart + 10`;
- the first cell is the year before the active decade;
- the next ten cells are the active decade;
- the last cell is the year after the active decade;
- the header displays the active decade with the existing ASCII-hyphen format,
  such as `2020-2029`;
- previous and next move by ten years.

The minimum selectable year remains `1999`. The maximum remains the browser's
current year, matching the existing Datepicker configuration. A cell is
enabled only if it is within those bounds and its year occurs in
`available_years`. An empty `available_years` list therefore keeps every year
disabled, preserving the current behavior.

The selected year receives selected styling and `aria-current="page"`. Years
outside the active decade are visually muted. Disabled cells use native button
`disabled` semantics. Previous is disabled when the active decade's start is
less than or equal to `1999`; next is disabled when the active decade's last
year is greater than or equal to the current maximum. This keeps navigation
bounded while retaining the current visible range.

Cell state is selected from complete Python-generated class variants, not by
appending competing Tailwind classes in TypeScript. The variants cover
default, selected, adjacent, disabled, and adjacent-disabled states. State
selection gives disabled styling precedence over selected styling, while the
selected state wins over adjacent styling for the theoretically overlapping
case.

Selecting an enabled year immediately replaces `__year__` in `url_template`
and assigns the resulting URL to `window.location.href`, but only when
`url_template` is non-empty, preserving the current public API behavior. The
all-time view remains the separate All-time stats button.

### Keyboard and accessibility

The trigger's `aria-controls` and `aria-expanded` are managed by
`bindCalendarPopupHost()`, as with the existing date calendars. The initial
state is rendered as `aria-expanded="false"`. The grid follows the existing
date-calendar convention: a labelled `role="group"` container whose
`aria-labelledby` points at the decade label, real year buttons, and
`aria-current="page"` on the selected button. Unavailable buttons use native
`disabled` semantics, and previous/next buttons have explicit accessible
names. No custom `role="grid"`/roving-tabindex framework is introduced.

The dropdown continues to own Escape, outside-click, and focus-leave dismissal
while focus is in the popup. Its shared `keepOpenOnTab` option allows Tab and
Shift+Tab to traverse the popup before closing when focus leaves. Native
button activation handles Enter/Space on the trigger and year cells. The
YearPicker adds ArrowDown on the trigger to open the popup and Escape on the
trigger to close it; these are the only keyboard gaps not already supplied by
the shared machinery. ArrowDown leaves focus on the trigger, so the next Tab
enters the first popup control. Reopening resets the view to the selected year,
or the current year for the all-time view.

## Testing and verification

### TypeScript unit tests

Add `ts/elements/year-picker.test.ts` using the same jsdom/fake-dropdown
pattern as the existing date-picker tests. Cover:

- twelve-cell rendering around a decade;
- exact four-column ordering and the lower/upper decade boundaries;
- selected-year initialization;
- minimum and current-year bounds;
- `available_years` disabling;
- previous/next decade navigation;
- selected and muted cell state;
- complete state-class precedence;
- trigger ArrowDown/Escape behavior and native button activation;
- initial and updated `aria-expanded`, `aria-controls`, group labelling, and
  date-calendar-style button semantics;
- immediate URL navigation for an enabled year;
- no navigation for a disabled year;
- no navigation when `url_template` is empty.

### Python rendering tests

Update `tests/test_rendered_pages.py` to assert that stats pages render the
new dropdown/year-grid hooks and no longer include `datepicker.umd.js` or the
obsolete `year-picker-input`. Verify the initial `aria-expanded="false"` and
the new grid/template hooks in the rendered markup.

Add or update component assertions for the server-rendered template and
control attributes where the existing component test structure makes that
more precise than a full-page assertion.

### Browser tests

Add a stats-page Playwright test that logs in, opens the YearPicker, verifies
the visible four-column decade grid, navigates a decade, tabs through more
than one popup control, uses keyboard activation, verifies that focus leaving
the panel closes it, and selects an enabled year while asserting the resulting
stats URL. Keep sparse `available_years` behavior in deterministic
TypeScript/unit coverage because production stats data normally supplies a
contiguous year range.

Add shared menu-behavior coverage for `keepOpenOnTab`: Tab and Shift+Tab stay
open while focus moves between controls inside a date-calendar panel and close
when focus leaves the panel.

### Cleanup and checks

Remove the UMD file and all source, runtime, test, comment, and product
documentation references to it. The historical design record may retain the
asset name when explaining the migration. Regenerate TypeScript contracts,
rebuild static assets, and run the relevant Python tests, TypeScript
checks/tests, and YearPicker E2E test. The final search over source, tests,
runtime assets, and product documentation must find no `datepicker.umd.js`
reference.

## Acceptance criteria

1. The stats YearPicker opens and dismisses through the shared dropdown host,
   including the small ArrowDown/Escape trigger behavior, native button
   activation, and shared focus-leave handling.
2. It presents the same twelve-cell decade layout and immediate-navigation
   behavior as the current picker.
3. The grid has the exact four-column ordering and bounded decade
   navigation.
4. Bounds and `available_years` disable exactly the same years as before.
5. The existing date-calendar button semantics and the small added keyboard
   gaps are covered by tests.
6. Tab and Shift+Tab can traverse the YearPicker popup controls and close the
   popup when focus leaves it.
7. `games/static/js/datepicker.umd.js` is deleted.
8. The YearPicker no longer declares or loads datepicker media.
9. Stats rendering tests pass without expecting the removed asset.
10. No source, test, runtime-asset, or product-documentation reference to
   `datepicker.umd.js` remains.
