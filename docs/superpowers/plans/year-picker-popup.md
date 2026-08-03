# Stats YearPicker Popup

## Purpose

The stats YearPicker is an in-house four-column decade selector hosted by the
shared `date-calendar` dropdown. Its popup must remain usable at every viewport
size without duplicating layout or dismissal logic outside the shared calendar
machinery.

## Geometry contract

- Year cells have fixed equal geometry: `w-14 shrink-0`.
- The four-column grid owns its width with `w-56`.
- The popup surface is intrinsic (`flex w-auto`) and contains an inner
  `data-year-picker-body` wrapper that owns `p-2`.
- The popup surface has no independently calculated width. Its width is the
  body content plus padding and borders.
- Shared anchored positioning measures that intrinsic surface, flips when
  needed, and keeps it within the viewport margin.

This keeps the grid centered in the visible surface, preserves equal columns
at every font size, and avoids tying popup width to a particular typography
scale.

## Interaction contract

- The picker reuses `<drop-down behavior="date-calendar">` and
  `bindCalendarPopupHost()` for positioning, ARIA state, dismissal, and
  single-open coordination.
- The picker owns only decade state, twelve-cell rendering, decade navigation,
  availability, and immediate navigation after a year is selected.
- Navigating to the minimum or current boundary can disable the focused arrow.
  That native focus loss is an internal update: the shared menu behavior must
  keep the popup open rather than interpret it as focus leaving the panel.
- Tab traversal stays within the panel until focus genuinely exits; Escape and
  outside clicks retain the shared dismissal behavior.

## Verification expectations

- Rendering checks keep the cell and grid geometry classes, require the body
  wrapper, and reject a fixed popup-width class.
- Browser checks cover equal grid geometry, font-size scaling, narrow-view
  containment, previous/next decade navigation, and repeated boundary
  navigation without closing the popup.
- Shared menu tests cover focus transitions caused by an in-panel control
  becoming disabled.
