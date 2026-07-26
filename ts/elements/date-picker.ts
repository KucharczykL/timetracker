/**
 * DatePicker — custom element wrapping the vanilla TS implementation.
 *
 * Drives the DatePicker component (common/components/date_picker.py): a
 * single presentation-aware segmented date (issue #485) plus a calendar
 * popup, replacing native `<input type="date">` on add/edit forms so the
 * account's DATETIME_FORMAT preference controls the visible segment order.
 *
 * Shares the segment-entry engine (date-field-core.ts) and the month-grid
 * calendar renderer (date-calendar-core.ts) with date-range-picker.ts:
 * - Segments: identical digit-typing/arrow/backspace/paste grammar, driving
 *   one side ("value") instead of two.
 * - Calendar: no presets, no anchor — clicking a day commits the value and
 *   closes the popup immediately (a native date input's one-click UX);
 *   Clear empties the value and keeps the popup open.
 *
 * Hosted in <drop-down behavior="date-calendar"> (issue #485 follow-up):
 * visibility, viewport-aware positioning, and outside-click/Escape dismiss
 * all come from the shared attachMenu engine (this element delegates to the
 * host's open()/close(), the same shape SearchSelect(host_dropdown) uses)
 * instead of a bespoke absolute-positioned Div + its own document listeners.
 *
 * The committed value lives in the hidden ISO input Django binds
 * (`[data-date-picker-hidden]`), named after the real form field.
 */
import { bindSegmentField, isoFromDate, setSideValue } from "./date-field-core.js";
import {
  bindCalendarNav,
  bindCalendarPopupHost,
  dayVariantClass,
  renderMonthCalendar,
  todayView,
  viewFromIso,
  type MonthCalendarView,
} from "./date-calendar-core.js";

export const DATE_PICKER_CHANGE_EVENT = "date-picker:change";

export interface DatePickerChangeDetail {
  value: string;
}

// The single side id this element's shared-engine hooks use — DateRangePicker
// keys its hooks by side ("min"/"max"); a single-date field has exactly one.
const SIDE = "value";

function resolveHidden(picker: HTMLElement): HTMLInputElement | null {
  return picker.querySelector<HTMLInputElement>("input[data-date-picker-hidden]");
}

function dispatchDatePickerChange(picker: HTMLElement): void {
  picker.dispatchEvent(
    new CustomEvent<DatePickerChangeDetail>(DATE_PICKER_CHANGE_EVENT, {
      bubbles: true,
      detail: { value: resolveHidden(picker)?.value ?? "" },
    }),
  );
}

interface CalendarState {
  view: MonthCalendarView;
  selectedIso: string;
  refreshFromField: () => void;
}

function initField(picker: HTMLElement, calendarState: CalendarState): void {
  const field = picker.querySelector<HTMLElement>("[data-date-picker-field]")!;
  bindSegmentField({
    picker,
    field,
    resolveHidden: () => resolveHidden(picker),
    onCommit: () => dispatchDatePickerChange(picker),
    onFocus: () => calendarState?.refreshFromField(),
  });
}

function createCalendarState(picker: HTMLElement): CalendarState {
  // The calendar shell reuses DateRangePicker's data-date-range-* hooks
  // (documented shared contract, not a range-specific naming leak).
  const popup = picker.querySelector<HTMLElement>("[data-date-range-calendar]")!;
  const grid = popup.querySelector<HTMLElement>("[data-date-range-grid]")!;
  const monthLabel = popup.querySelector<HTMLElement>("[data-date-range-month-label]")!;
  const dayTemplate = popup.querySelector<HTMLTemplateElement>(
    '[data-date-range-template="day"]',
  );
  const toggleButton = picker.querySelector<HTMLElement>(
    "[data-date-picker-calendar-toggle]",
  );

  const state: CalendarState = {
    view: todayView(),
    selectedIso: "",
    refreshFromField() {
      if (host.isOpen()) return;
      state.selectedIso = resolveHidden(picker)?.value ?? "";
    },
  };

  function commitSelection(isoString: string): void {
    setSideValue(
      picker,
      SIDE,
      () => resolveHidden(picker),
      () => dispatchDatePickerChange(picker),
      isoString,
    );
  }

  const todayIso = isoFromDate(new Date());

  function dayCellClass(isoString: string, inViewMonth: boolean): string {
    // One complete generated class list per state — never additive. Rounding,
    // fill and dimming are orthogonal, and combining them by hand is what left
    // selected and adjacent-month cells square-cornered.
    if (isoString === state.selectedIso) return dayVariantClass("selected");
    return dayVariantClass(inViewMonth ? "default" : "adjacent");
  }

  function dayCellAria(isoString: string, inViewMonth: boolean) {
    const monthQualifier = inViewMonth ? "" : " (adjacent month)";
    return {
      label: `${isoString}${monthQualifier}`,
      selected: isoString === state.selectedIso,
      current: isoString === todayIso,
    };
  }

  function render(): void {
    renderMonthCalendar(state.view, {
      grid,
      monthLabel,
      dayTemplate,
      dayCellClass,
      dayCellAria,
    });
  }

  const host = bindCalendarPopupHost({
    picker,
    popup,
    toggleButton,
    idPrefix: "date-picker-calendar",
    beforeOpen: () => {
      state.selectedIso = resolveHidden(picker)?.value ?? "";
      state.view = state.selectedIso ? viewFromIso(state.selectedIso) : todayView();
    },
    render,
  });

  grid.addEventListener("click", (event) => {
    const dayButton = (event.target as Element).closest("button[data-date]");
    if (!dayButton) return;
    const isoString = dayButton.getAttribute("data-date") ?? "";
    state.selectedIso = isoString;
    commitSelection(isoString);
    host.close();
  });

  bindCalendarNav(popup, state, render);

  // Clear: empty the value but keep the popup open (same as the range
  // picker's Clear — the footer here has no Cancel/Select, only Clear).
  popup
    .querySelector<HTMLElement>("[data-date-range-clear]")!
    .addEventListener("click", () => {
      state.selectedIso = "";
      commitSelection("");
      render();
    });

  return state;
}

// One-time wiring: field + calendar listeners persist with the subtree across
// htmx swaps and DOM moves, so there is nothing left to (re)bind on
// reconnection — unlike the old bespoke popup, which needed its own
// document-level dismiss listeners rebound.
function initPicker(picker: HTMLElement): void {
  const calendarState = createCalendarState(picker);
  initField(picker, calendarState);
}

class DatePickerElement extends HTMLElement {
  private initialized = false;

  connectedCallback(): void {
    if (this.initialized) return;
    this.initialized = true;
    initPicker(this);
  }
}

customElements.define("date-picker", DatePickerElement);
