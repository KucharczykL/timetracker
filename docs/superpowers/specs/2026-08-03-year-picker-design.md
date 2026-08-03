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
- a year grid;
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

The element owns only year-specific behavior:

- decade view state;
- rendering the twelve year cells;
- previous/next decade navigation;
- enabled/disabled and selected cell state;
- immediate URL navigation after a valid selection;
- year-grid keyboard movement.

The old body-mounted Flowbite popup and its bespoke `bindPopupDismiss()` path
are removed.

### Year view and selection rules

The year view mirrors Flowbite's existing `YearsView` layout:

- the first cell is the year before the active decade;
- the next ten cells are the active decade;
- the last cell is the year after the active decade;
- the header displays the active decade, such as `2020–2029`;
- previous and next move by ten years.

The minimum selectable year remains `1999`. The maximum remains the browser's
current year, matching the existing Datepicker configuration. A cell is
enabled only if it is within those bounds and its year occurs in
`available_years`. An empty `available_years` list therefore keeps every year
disabled, preserving the current behavior.

The selected year receives selected styling and `aria-selected="true"`.
Years outside the active decade are visually muted. Disabled cells use native
button `disabled` semantics. Selecting an enabled year immediately replaces
`__year__` in `url_template` and assigns the resulting URL to
`window.location.href`. The all-time view remains the separate All-time stats
button.

### Keyboard and accessibility

The trigger's `aria-controls` and `aria-expanded` are managed by
`bindCalendarPopupHost()`, as with the existing date calendars. Year cells are
real buttons, so disabled years cannot receive focus or activation.

The year grid adds the keyboard behavior supplied by the current Flowbite
picker:

- Left/Right moves one cell;
- Up/Down moves one row;
- Home/End moves to the first/last enabled year on the visible page;
- Enter/Space activates the focused enabled year.

The dropdown continues to own Escape, Tab, outside-click, and focus-boundary
dismissal. No custom generic grid abstraction is introduced.

## Testing and verification

### TypeScript unit tests

Add `ts/elements/year-picker.test.ts` using the same jsdom/fake-dropdown
pattern as the existing date-picker tests. Cover:

- twelve-cell rendering around a decade;
- selected-year initialization;
- minimum and current-year bounds;
- `available_years` disabling;
- previous/next decade navigation;
- selected and muted cell state;
- keyboard movement and activation;
- immediate URL navigation for an enabled year;
- no navigation for a disabled year.

### Python rendering tests

Update `tests/test_rendered_pages.py` to assert that stats pages render the
new dropdown/year-grid hooks and no longer include `datepicker.umd.js` or the
obsolete `year-picker-input`.

Add or update component assertions for the server-rendered template and
control attributes where the existing component test structure makes that
more precise than a full-page assertion.

### Browser tests

Add a stats-page Playwright test that logs in, opens the YearPicker, verifies
the visible decade grid and disabled unavailable years, navigates a decade,
and selects an enabled year while asserting the resulting stats URL.

### Cleanup and checks

Remove the UMD file and all source, runtime, test, comment, and product
documentation references to it. The historical design record may retain the
asset name when explaining the migration. Regenerate TypeScript contracts,
rebuild static assets, and run the relevant Python tests, TypeScript
checks/tests, and YearPicker E2E test. The final search over source, tests,
runtime assets, and product documentation must find no `datepicker.umd.js`
reference.

## Acceptance criteria

1. The stats YearPicker opens and dismisses through the shared dropdown host.
2. It presents the same twelve-cell decade layout and immediate-navigation
   behavior as the current picker.
3. Bounds and `available_years` disable exactly the same years as before.
4. Keyboard and accessible button behavior are covered by tests.
5. `games/static/js/datepicker.umd.js` is deleted.
6. The YearPicker no longer declares or loads datepicker media.
7. Stats rendering tests pass without expecting the removed asset.
8. No source, test, runtime-asset, or product-documentation reference to
   `datepicker.umd.js` remains.
