# Stats YearPicker

The stats YearPicker is an in-house four-column decade selector. It preserves
the public Python API:

```python
YearPicker(year, available_years, url_template)
```

## Architecture

- The component is hosted by `<drop-down behavior="date-calendar">`.
- Shared dropdown/calendar machinery owns popup positioning, ARIA expanded
  state, viewport clamping, outside-click dismissal, Escape, focus-leave, and
  single-open coordination.
- `year-picker.ts` owns only decade state, twelve-cell rendering, availability,
  decade navigation, and immediate navigation after selecting an enabled year.
- The legacy Flowbite datepicker bundle and hidden input are not part of the
  implementation.

## User-visible behavior

- The grid has four columns and twelve cells: one adjacent year on either side
  of the active decade.
- Selectable years are bounded by 1999 and the browser's current year, then
  filtered by `available_years`.
- Enabled year selection navigates immediately through `url_template`; an
  empty template never navigates.
- Previous/next decade controls stay within those bounds. Reaching a boundary
  can disable the focused arrow without closing the popup.
- Tab remains in the popup while focus moves between its controls and closes
  only after focus genuinely exits.

## Layout contract

- Cells use `w-14 shrink-0`; the four-column grid uses `w-56`.
- The popup surface is intrinsic (`flex w-auto`) and its inner body owns
  `p-2`; the surface has no independently calculated width.
- The shared anchored positioner measures, flips, and clamps the popup.

## Verification

- Rendering and unit tests protect the component API, year bounds, grid
  geometry, and shared-menu focus behavior.
- Browser coverage protects navigation, repeated boundary navigation,
  font-size scaling, and narrow-viewport containment.
