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
//   segments' own Arrow/Backspace grammar are unaffected; the shared
//   focus-leave handler closes after focus exits the panel);
// - no `matchToggleWidth`: unlike a value-select panel, the calendar has its
//   own intrinsic width (the month grid), not the field's width.
// - a small `gap` so the popup doesn't sit flush against the field it opens
//   under (every other dropdown is flush; a calendar reads better with
//   daylight).
//
// attachMenu and the stack do the rest.
registerBehavior("date-calendar", {
  menuOptions: () => ({
    itemSelector: "[data-date-calendar-no-items]",
    inlineTrigger: true,
    keepOpenOnTab: true,
    gap: 4,
  }),
});
