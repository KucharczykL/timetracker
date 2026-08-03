import { registerBehavior } from "../dropdown-behaviors.js";

// Date-calendar dropdown (issue #485 follow-up): a DateRangePicker/DatePicker
// popup hosted in <drop-down behavior="date-calendar">, mirroring the
// inline-combobox shape — the field is a typing surface (segments), and the
// picker element itself decides WHEN to open (its calendar-icon click, or a
// segment focus refreshing the calendar's view) rather than a toggle click
// owning everything. Its only jobs, via attachMenu's `inlineTrigger` option:
//
// - suppress the toggle click/keydown handlers (typing into a segment or
//   clicking the icon must not double-fire attachMenu's own open/close) and
//   the toggle aria-expanded writes — the picker element owns aria-expanded
//   on its own calendar-icon button, same as SearchSelect owns it on its
//   search input;
// - a match-nothing `itemSelector`, so attachMenu's roving/typeahead stays
//   off entirely (the calendar's own day-grid click handling and the
//   segments' own Arrow/Backspace grammar are unaffected; Escape still closes
//   via attachMenu while its shared focus-leave handler closes after focus
//   exits the panel);
// - no `matchToggleWidth`: unlike a value-select panel, the calendar has its
//   own intrinsic width (the month grid), not the field's width.
// - a small `gap` so the popup doesn't sit flush against the field it opens
//   under (every other dropdown is flush; a calendar reads better with
//   daylight).
//
// Positioning (viewport-aware fixed + flip + horizontal clamp), outside-click/
// Escape/Tab dismiss, and single-open coordination all come from the shared
// attachMenu engine — this is the actual #485 mobile-overlap fix: the popup
// no longer uses a static `top-full` CSS offset with no viewport awareness.
registerBehavior("date-calendar", {
  menuOptions: () => ({
    itemSelector: "[data-date-calendar-no-items]",
    inlineTrigger: true,
    keepOpenOnTab: true,
    gap: 4,
  }),
});
