/**
 * DateRangePicker — custom element wrapping the vanilla TS implementation.
 *
 * Drives the DateRangePicker component (common/components/date_range_picker.py):
 *
 * - DateRangeField: segmented manual entry. Each date part (DD/MM/YYYY) is its
 *   own input; digits fill the placeholder from the right (YYYY → YYY1 → YY19
 *   → Y198 → 1987), full parts auto-advance to the next one, and
 *   Backspace/Delete reverts the active part to its placeholder.
 * - DateRangeCalendar: popup month grid with a preset column and a
 *   Cancel / Clear / Select footer. Picking works anchor-style: the first
 *   pick becomes the StartDate anchor, the second pick sets the EndDate and
 *   moves the anchor there so further picks adjust the StartDate. Picking on
 *   the wrong side of the anchor clears the range and restarts from the
 *   clicked date.
 *
 * The committed value lives in the two hidden ISO inputs ({prefix}-min /
 * {prefix}-max) that filter_bar.ts serializes into a DateCriterion.
 *
 * The segment-entry grammar (digit typing, arrows, paste) and the month-grid
 * renderer are shared with date-picker.ts via date-field-core.ts /
 * date-calendar-core.ts; anchor/track/preset logic below is range-specific.
 *
 * The popup (non-panel) variant is hosted in <drop-down behavior="date-calendar">
 * (issue #485 follow-up): visibility, viewport-aware positioning, and outside-
 * click/Escape dismiss all come from the shared attachMenu engine (this element
 * delegates to the host's open()/close(), the same shape SearchSelect(host_dropdown)
 * uses) instead of a bespoke absolute-positioned Div + its own document listeners.
 * The static (panel) variant is unaffected — it already lives inside the quick
 * bar's OWN separate <drop-down>, and never toggles.
 *
 * NB: class strings below are emitted verbatim so the Tailwind scanner picks
 * them up — keep them as plain literals.
 */
import {
  addDays,
  bindSegmentField,
  dateFromIso,
  isoFromDate,
  setSideValue,
  writeSideValue as writeSideValueCore,
} from "./date-field-core.js";
import {
  bindCalendarNav,
  bindCalendarPopupHost,
  dayVariantClass,
  renderMonthCalendar,
  trackVariantClass,
  todayView,
  viewFromIso,
  type MonthCalendarView,
} from "./date-calendar-core.js";

// Fired whenever a committed bound actually changes — segment typing or a
// calendar/preset pick (issue #192). The flat filter bar reads the hidden inputs
// at serialize time (pull), but the nested filter builder's date leaf needs a push
// signal to fold the new value into its tree node. detail carries both ISO bounds
// ("" when a side is empty) so a consumer needn't re-query the DOM.
export const DATE_RANGE_CHANGE_EVENT = "date-range:change";

export interface DateRangeChangeDetail {
  min: string;
  max: string;
}

function resolveHidden(picker: HTMLElement, side: string): HTMLInputElement | null {
  return picker.querySelector<HTMLInputElement>(`input[data-date-range-hidden="${side}"]`);
}

function dispatchDateRangeChange(picker: HTMLElement): void {
  const read = (side: string): string => resolveHidden(picker, side)?.value ?? "";
  picker.dispatchEvent(
    new CustomEvent<DateRangeChangeDetail>(DATE_RANGE_CHANGE_EVENT, {
      bubbles: true,
      detail: { min: read("min"), max: read("max") },
    }),
  );
}

/** Push an ISO value (or "") into a side's segments and hidden input, without
 * dispatching date-range:change — the write half shared with prefill
 * hydration (#263), which runs on a detached, not-yet-connected clone and
 * must stay silent. Returns whether the hidden value changed. Kept as the
 * public contract filter-widgets.ts writes prefilled bounds through. */
export function writeSideValue(picker: HTMLElement, side: string, isoString: string): boolean {
  return writeSideValueCore(picker, side, (candidateSide) => resolveHidden(picker, candidateSide), isoString);
}

type Anchor = "" | "start" | "end";

interface CalendarState {
  view: MonthCalendarView;
  startIso: string;
  endIso: string;
  // The anchor is the fixed endpoint: "start" while picking the EndDate,
  // "end" once the range is complete (further picks move the StartDate).
  anchor: Anchor;
  hoverIso: string;
  // True while showing a committed range the user has not edited yet —
  // the track renders muted until the first pick.
  readOnly: boolean;
  refreshFromField: () => void;
}

function presetRange(presetName: string): [Date, Date] | null {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = addDays(today, -1);
  const year = today.getFullYear();
  const month = today.getMonth();
  switch (presetName) {
    case "today":
      return [today, today];
    case "yesterday":
      return [yesterday, yesterday];
    case "last_7_days":
      return [addDays(today, -6), today];
    case "last_30_days":
      return [addDays(today, -29), today];
    case "this_month":
      return [new Date(year, month, 1), new Date(year, month + 1, 0)];
    case "last_month":
      return [new Date(year, month - 1, 1), new Date(year, month, 0)];
    case "this_year":
      return [new Date(year, 0, 1), new Date(year, 11, 31)];
    default:
      return null;
  }
}

// ── DateRangeField: segmented manual entry ──────────────────────────────

function initField(picker: HTMLElement, calendarState: CalendarState): void {
  const field = picker.querySelector<HTMLElement>("[data-date-range-field]")!;
  bindSegmentField({
    picker,
    field,
    resolveHidden: (candidateSide) => resolveHidden(picker, candidateSide),
    onCommit: () => dispatchDateRangeChange(picker),
    onFocus: () => calendarState?.refreshFromField(),
  });
}

// ── DateRangeCalendar: popup month grid ────────────────────────────────

function createCalendarState(picker: HTMLElement): CalendarState {
  const popup = picker.querySelector<HTMLElement>("[data-date-range-calendar]")!;
  const grid = popup.querySelector<HTMLElement>("[data-date-range-grid]")!;
  const monthLabel = popup.querySelector<HTMLElement>("[data-date-range-month-label]")!;
  const dayTemplate = popup.querySelector<HTMLTemplateElement>(
    '[data-date-range-template="day"]',
  );
  const toggleButton = picker.querySelector<HTMLElement>(
    "[data-date-range-calendar-toggle]",
  );
  // The static (panel) variant lives inside the quick bar's OWN <drop-down> — it
  // must never call open()/close() on that unrelated ancestor. It has no toggle
  // either, so bindCalendarPopupHost's click/aria wiring no-ops naturally; only
  // `staticAlways` is needed to make isOpen() report true forever.
  const staticCalendar = picker.hasAttribute("data-static-calendar");

  function hiddenValue(side: string): string {
    return resolveHidden(picker, side)?.value ?? "";
  }

  const state: CalendarState = {
    view: todayView(),
    startIso: "",
    endIso: "",
    anchor: "",
    hoverIso: "",
    readOnly: false,
    refreshFromField() {
      if (host.isOpen()) return;
      state.startIso = hiddenValue("min");
      state.endIso = hiddenValue("max");
    },
  };

  function syncSelectionToField(): void {
    const commit = () => dispatchDateRangeChange(picker);
    const resolve = (side: string) => resolveHidden(picker, side);
    setSideValue(picker, "min", resolve, commit, state.startIso);
    setSideValue(picker, "max", resolve, commit, state.endIso);
  }

  function syncViewFromHidden(): void {
    state.startIso = hiddenValue("min");
    state.endIso = hiddenValue("max");
    state.anchor = state.startIso && state.endIso ? "end" : state.startIso ? "start" : "";
    state.readOnly = Boolean(state.startIso && state.endIso);
    state.hoverIso = "";
    state.view = state.startIso ? viewFromIso(state.startIso) : todayView();
  }

  function clearSelection(): void {
    state.startIso = "";
    state.endIso = "";
    state.anchor = "";
    state.hoverIso = "";
    state.readOnly = false;
    syncSelectionToField();
  }

  /**
   * Anchor-style picking:
   * - no selection: the pick becomes the StartDate anchor
   * - anchor=start (picking EndDate): a pick on/after the StartDate
   *   completes the range and moves the anchor to the EndDate; a pick
   *   before it clears the range and restarts
   * - anchor=end (adjusting StartDate): a pick on/before the EndDate
   *   moves the StartDate (extend/shorten); a pick after it clears the
   *   range and restarts from the clicked date
   */
  function pickDate(isoString: string): void {
    state.readOnly = false;
    if (!state.startIso) {
      state.startIso = isoString;
      state.anchor = "start";
    } else if (state.anchor === "start" && !state.endIso) {
      if (isoString >= state.startIso) {
        state.endIso = isoString;
        state.anchor = "end";
      } else {
        state.startIso = isoString;
        state.endIso = "";
        state.anchor = "start";
      }
    } else {
      if (isoString <= state.endIso) {
        state.startIso = isoString;
      } else {
        state.startIso = isoString;
        state.endIso = "";
        state.anchor = "start";
      }
    }
    syncSelectionToField();
    render();
  }

  function applyPreset(presetName: string): void {
    const range = presetRange(presetName);
    if (!range) return;
    state.startIso = isoFromDate(range[0]);
    state.endIso = isoFromDate(range[1]);
    state.anchor = "end";
    state.readOnly = false;
    state.view = { year: range[0].getFullYear(), month: range[0].getMonth() };
    syncSelectionToField();
    render();
  }

  /** The (inclusive-exclusive of endpoints) track between the two range
   * ends; while picking the second date the hovered day acts as the
   * provisional other end. */
  function trackBounds(): [string, string, string] | null {
    if (state.startIso && state.endIso) {
      return [
        state.startIso,
        state.endIso,
        trackVariantClass(state.readOnly ? "muted" : "filled"),
      ];
    }
    if (state.startIso && state.hoverIso && state.hoverIso !== state.startIso) {
      const lower = state.hoverIso < state.startIso ? state.hoverIso : state.startIso;
      const upper = state.hoverIso < state.startIso ? state.startIso : state.hoverIso;
      return [lower, upper, trackVariantClass("outlined")];
    }
    return null;
  }

  function dayCellClass(isoString: string, inViewMonth: boolean): string {
    const isStart = isoString === state.startIso;
    const isEnd = isoString === state.endIso;
    const isAnchor =
      (state.anchor === "start" && isStart) || (state.anchor === "end" && isEnd);
    // The day's own look: one COMPLETE generated variant, never assembled from
    // parts. (Hand-combining rounding/fill/dimming is what left the filled
    // variants square-cornered.)
    let variant: "default" | "selected" | "adjacent" | "anchor";
    if (isAnchor && !state.readOnly) variant = "anchor";
    else if (isStart || isEnd) variant = "selected";
    else variant = inViewMonth ? "default" : "adjacent";
    const classes = [dayVariantClass(variant)];
    // The track is the one genuinely ADDITIVE layer — it paints the days
    // between the endpoints, and deliberately squares their corners so the
    // run reads as one continuous bar rather than separate pills.
    //
    // This is the same VISUAL idea as ButtonGroup (a joined run rounded only
    // at its outer ends) but necessarily the opposite MECHANISM, so don't try
    // to share them:
    //
    // - ButtonGroup rounds from the parent, keyed on DOM position
    //   ([&>*:first-child]:rounded-s-base). It has to: a member cannot know
    //   its own position — the one styling-at-a-distance exception the
    //   primitives module documents.
    // - A range is data-defined, not DOM-positional. It is a subrange of a
    //   7-column grid that WRAPS ACROSS WEEK ROWS, so :first-child/:last-child
    //   would match the first and last day of the month, not of the range.
    //   The cell does know its own position here, from the range state.
    //
    // Hence subtractive (un-round the joined edges) rather than additive:
    // going additive would mean day variants that ship unrounded, which means
    // a `rounded` knob on ControlButton for one caller's benefit. Removing one
    // override is not worth a parameter on a shared primitive.
    const track = trackBounds();
    if (track !== null && isoString > track[0] && isoString < track[1]) {
      classes.push("rounded-none", track[2]);
    } else if (track !== null && track[0] !== track[1]) {
      // An endpoint that FACES the track squares only the edge it meets, so
      // the band joins the pill flush. Leaving both corners rounded leaves a
      // notch of background above and below the join — the range then reads
      // as three separate chips instead of one continuous selection.
      // (`rounded-base` + `rounded-e-none` is the documented Tailwind
      // shorthand-then-longhand pattern, as in `rounded-lg rounded-t-none`.)
      if (isoString === track[0]) classes.push("rounded-e-none");
      else if (isoString === track[1]) classes.push("rounded-s-none");
    }
    return classes.join(" ");
  }

  const todayIso = isoFromDate(new Date());

  function dayCellAria(isoString: string, inViewMonth: boolean) {
    const isStart = isoString === state.startIso;
    const isEnd = isoString === state.endIso;
    const monthQualifier = inViewMonth ? "" : " (adjacent month)";
    return {
      label: `${isoString}${monthQualifier}`,
      selected: isStart || isEnd,
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

  // ── Wiring ──
  // The panel variant (data-static-calendar, DateRangePanel) has no toggle:
  // its calendar flows statically inside a dropdown dialog and never closes;
  // bindCalendarPopupHost's click/aria wiring no-ops since toggleButton is null.
  const host = bindCalendarPopupHost({
    picker,
    popup,
    toggleButton,
    idPrefix: "date-range-calendar",
    staticAlways: staticCalendar,
    beforeOpen: syncViewFromHidden,
    render,
  });

  grid.addEventListener("click", (event) => {
    const dayButton = (event.target as Element).closest("button[data-date]");
    if (dayButton) pickDate(dayButton.getAttribute("data-date") ?? "");
  });

  grid.addEventListener("mouseover", (event) => {
    if (!state.startIso || state.endIso) return;
    const dayButton = (event.target as Element).closest("button[data-date]");
    if (!dayButton) return;
    const hoveredIso = dayButton.getAttribute("data-date") ?? "";
    if (hoveredIso === state.hoverIso) return;
    state.hoverIso = hoveredIso;
    render();
  });

  bindCalendarNav(popup, state, render);

  popup.querySelectorAll<HTMLElement>("[data-date-range-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      applyPreset(button.getAttribute("data-date-range-preset") ?? "");
    });
  });

  // Cancel: close the popup and clear the selected dates. Absent in the
  // static variant (nothing to close), like Select below.
  popup
    .querySelector<HTMLElement>("[data-date-range-cancel]")
    ?.addEventListener("click", () => {
      clearSelection();
      host.close();
    });

  // Clear: clear the selected dates but keep the popup open.
  popup
    .querySelector<HTMLElement>("[data-date-range-clear]")!
    .addEventListener("click", () => {
      clearSelection();
      render();
    });

  // Select: close the popup, keeping the selected dates.
  popup
    .querySelector<HTMLElement>("[data-date-range-select]")
    ?.addEventListener("click", () => {
      host.close();
    });

  // The static variant renders its grid immediately and stays visible for the
  // element's whole life — the hosting (unrelated) <drop-down> owns its own
  // visibility, so this variant never delegates open()/close() to anything
  // (staticAlways above keeps `host`'s own delegation a no-op); this just
  // reuses the same beforeOpen+render sequence as a real open() would run.
  if (staticCalendar) host.open();

  return state;
}

// One-time wiring: field + calendar listeners persist with the subtree across
// htmx swaps and DOM moves (the nested filter builder reorders rows), so
// there is nothing left to (re)bind on reconnection — unlike the old bespoke
// popup, which needed its own document-level dismiss listeners rebound.
function initPicker(picker: HTMLElement): void {
  const calendarState = createCalendarState(picker);
  initField(picker, calendarState);
}

class DateRangePickerElement extends HTMLElement {
  private initialized = false;

  connectedCallback(): void {
    if (this.initialized) return;
    this.initialized = true;
    initPicker(this);
  }
}

customElements.define("date-range-picker", DateRangePickerElement);
