/**
 * Shared month-grid calendar renderer, extracted from date-range-picker.ts so
 * date-picker.ts (single-date select) and date-range-picker.ts (anchor-style
 * range select) render the same grid instead of each growing its own. Picking
 * semantics (anchor/track for a range, immediate commit for a single date)
 * stay with each caller — this module only owns the 42-cell month grid, the
 * weekday header, and month navigation.
 *
 * Also owns the popup-host delegation boilerplate (issue #485 follow-up):
 * both calendars hosted in <drop-down behavior="date-calendar"> need the
 * exact same aria-controls/aria-expanded stamping, isOpen/open/close
 * delegation to the host, and prev/next month nav — only the state each
 * calendar keeps (view + whatever else it tracks) and its own render/pick
 * logic differ.
 */
import {
  CALENDAR_DAY_CLASSES,
  CALENDAR_TRACK_CLASSES,
  CALENDAR_WEEKDAY_CLASS,
} from "../generated/calendar-classes.js";
import { calendarWeekdayLabels, formatCalendarMonthYear } from "../date-time-presentation.js";
import { addDays, isoFromDate } from "./date-field-core.js";

// Day-cell looks are GENERATED from Python (common/components/date_range_picker.py
// composes them out of ControlButton). Nothing here hand-writes a class string:
// that is what let the calendar drift from every other button in the app —
// square corners on selected/adjacent cells, and a 16px-wide nav hit area.
//
// Each entry is a COMPLETE class list for that state, so states cannot be
// combined by accident: rounding and fill are orthogonal, and the old additive
// if/else chain is what dropped rounding from the filled variants.
export type DayVariant = "default" | "selected" | "adjacent" | "anchor";
export type TrackVariant = "outlined" | "filled" | "muted";

export function dayVariantClass(variant: DayVariant): string {
  return CALENDAR_DAY_CLASSES[variant] ?? CALENDAR_DAY_CLASSES.default;
}

export function trackVariantClass(variant: TrackVariant): string {
  return CALENDAR_TRACK_CLASSES[variant] ?? "";
}

export interface MonthCalendarView {
  year: number;
  month: number; // 0-based, JS Date convention
}

export interface DayCellAria {
  label: string;
  selected: boolean;
  current: boolean;
}

export interface MonthCalendarOptions {
  grid: HTMLElement;
  monthLabel: HTMLElement;
  /** The server-rendered day-cell prototype (`[data-date-range-template=day]`),
   * cloned per cell so the markup comes from ControlButton rather than from a
   * `createElement` call here. Absent in a partial fixture → plain button. */
  dayTemplate: HTMLTemplateElement | null;
  dayCellClass: (iso: string, inViewMonth: boolean) => string;
  dayCellAria: (iso: string, inViewMonth: boolean) => DayCellAria;
}

export function todayView(): MonthCalendarView {
  const today = new Date();
  return { year: today.getFullYear(), month: today.getMonth() };
}

export function viewFromIso(isoString: string): MonthCalendarView {
  const date = new Date(
    parseInt(isoString.slice(0, 4), 10),
    parseInt(isoString.slice(5, 7), 10) - 1,
    parseInt(isoString.slice(8, 10), 10),
  );
  return { year: date.getFullYear(), month: date.getMonth() };
}

export function stepMonth(view: MonthCalendarView, direction: 1 | -1): MonthCalendarView {
  let { year, month } = view;
  month += direction;
  if (month < 0) {
    month = 11;
    year -= 1;
  } else if (month > 11) {
    month = 0;
    year += 1;
  }
  return { year, month };
}

/** Render the weekday header and the 42-cell month grid (Monday-first,
 * leading/trailing overflow days from adjacent months). */
export function renderMonthCalendar(view: MonthCalendarView, options: MonthCalendarOptions): void {
  options.monthLabel.textContent = formatCalendarMonthYear(view.year, view.month) ?? "";

  options.grid.textContent = "";
  calendarWeekdayLabels()?.forEach((weekdayLabel) => {
    const headerCell = document.createElement("span");
    headerCell.className = CALENDAR_WEEKDAY_CLASS;
    headerCell.textContent = weekdayLabel;
    options.grid.appendChild(headerCell);
  });

  // One prototype element, cloned per cell — the server-rendered ControlButton
  // when present (the real pages), a bare <button> only for partial fixtures.
  const prototype =
    options.dayTemplate?.content.firstElementChild ??
    Object.assign(document.createElement("button"), { type: "button" });

  const firstOfMonth = new Date(view.year, view.month, 1);
  const leadingDays = (firstOfMonth.getDay() + 6) % 7;
  let cellDate = addDays(firstOfMonth, -leadingDays);
  for (let cellIndex = 0; cellIndex < 42; cellIndex++) {
    const isoString = isoFromDate(cellDate);
    const inViewMonth = cellDate.getMonth() === view.month;
    const dayButton = prototype.cloneNode(false) as HTMLButtonElement;
    dayButton.setAttribute("data-date", isoString);
    dayButton.className = options.dayCellClass(isoString, inViewMonth);
    const aria = options.dayCellAria(isoString, inViewMonth);
    dayButton.setAttribute("aria-label", aria.label);
    dayButton.setAttribute("aria-selected", aria.selected ? "true" : "false");
    if (aria.current) dayButton.setAttribute("aria-current", "date");
    dayButton.textContent = String(cellDate.getDate());
    options.grid.appendChild(dayButton);
    cellDate = addDays(cellDate, 1);
  }
}

// ── Popup-host delegation (shared by date-picker.ts / date-range-picker.ts) ──

export interface CalendarPopupHost {
  isOpen: () => boolean;
  /** Runs `beforeOpen` (sync state from the hidden input(s) + resolve the
   * view), renders, then delegates to the drop-down host and syncs
   * aria-expanded. For the static (panel) variant this is also the one-time
   * init call — `beforeOpen`/`render` run, `dropdownHost`/`toggleButton` are
   * both null so the delegation/aria steps no-op. */
  open: () => void;
  /** Delegates to the drop-down host and syncs aria-expanded. A no-op for
   * the static variant (no host, no toggle). */
  close: () => void;
}

let calendarIdCounter = 0;

/**
 * Wires one calendar popup's host delegation: aria-controls/aria-expanded
 * stamping (the widget owns these under `inlineTrigger`, not attachMenu —
 * see date-calendar.ts), open()/close() delegated to the closest
 * `<drop-down>`, the toggle's click handler, and resyncing aria-expanded
 * when attachMenu closes the popup for a reason this element didn't
 * initiate (outside click, Escape, Tab, another dropdown opening).
 *
 * `staticAlways` (the DateRangePanel variant) skips the host entirely — it
 * lives inside a DIFFERENT, unrelated `<drop-down>` (the quick-facet's own
 * "Label ▾" host) and must never call open()/close() on it; `isOpen()`
 * simply stays `true` and `toggleButton` is null (no toggle exists), so the
 * click/aria wiring below no-ops naturally.
 */
export function bindCalendarPopupHost(options: {
  picker: HTMLElement;
  popup: HTMLElement;
  toggleButton: HTMLElement | null;
  idPrefix: string;
  staticAlways?: boolean;
  beforeOpen: () => void;
  render: () => void;
}): CalendarPopupHost {
  const dropdownHost = options.staticAlways
    ? null
    : options.picker.closest<HTMLElement & { open(): void; close(): void }>("drop-down");

  if (options.toggleButton) {
    calendarIdCounter += 1;
    options.popup.id = `${options.idPrefix}-${calendarIdCounter}`;
    options.toggleButton.setAttribute("aria-controls", options.popup.id);
  }

  const isOpen = (): boolean =>
    Boolean(options.staticAlways) ||
    (dropdownHost ? !options.popup.hasAttribute("hidden") : false);

  const syncExpanded = (): void => {
    options.toggleButton?.setAttribute("aria-expanded", isOpen() ? "true" : "false");
  };

  const open = (): void => {
    options.beforeOpen();
    // Render before opening: attachMenu unhides then measures scrollHeight
    // for its flip decision, so stale (or empty) grid content must never be it.
    options.render();
    dropdownHost?.open();
    syncExpanded();
  };

  const close = (): void => {
    dropdownHost?.close();
    syncExpanded();
  };

  options.toggleButton?.addEventListener("click", () => {
    if (isOpen()) close();
    else open();
  });

  dropdownHost?.addEventListener("dropdown:hide", syncExpanded);

  return { isOpen, open, close };
}

/** Wires the shared prev/next month-nav buttons: step `state.view` and
 * re-render. `state` is whichever calendar-state object the caller keeps —
 * it only needs a mutable `view` field. */
export function bindCalendarNav(
  popup: HTMLElement,
  state: { view: MonthCalendarView },
  render: () => void,
): void {
  popup.querySelector<HTMLElement>("[data-date-range-prev]")!.addEventListener("click", () => {
    state.view = stepMonth(state.view, -1);
    render();
  });
  popup.querySelector<HTMLElement>("[data-date-range-next]")!.addEventListener("click", () => {
    state.view = stepMonth(state.view, 1);
    render();
  });
}
