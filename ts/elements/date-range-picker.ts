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
 * NB: class strings below are emitted verbatim so the Tailwind scanner picks
 * them up — keep them as plain literals.
 */
import { bindPopupDismiss } from "../utils.js";

type Anchor = "" | "start" | "end";

interface CalendarState {
  open: boolean;
  viewYear: number;
  viewMonth: number;
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

const WEEKDAY_LABELS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

const WEEKDAY_CLASS =
  "w-8 h-6 flex items-center justify-center text-xs text-body select-none";
const DAY_BASE_CLASS =
  "date-range-day w-8 h-8 flex items-center justify-center text-sm " +
  "text-heading cursor-pointer hover:bg-neutral-tertiary-medium";
const DAY_ROUNDED_CLASS = "rounded-base";
const DAY_OUTSIDE_MONTH_CLASS = "opacity-40";
const DAY_SELECTED_CLASS = "bg-brand text-white hover:bg-brand-strong";
const DAY_ANCHOR_CLASS =
  "bg-brand text-white ring-2 ring-inset ring-brand-strong hover:bg-brand-strong";
// The three visual states of the date range track (the days between the
// two endpoints): outlined while picking the second date, filled once both
// are picked, muted when showing an already-committed range read-only.
const TRACK_OUTLINED_CLASS = "border-y border-brand/70 bg-brand/10";
const TRACK_FILLED_CLASS = "bg-brand/30";
const TRACK_MUTED_CLASS = "bg-brand/15";

// ── Date helpers (all local-time; values are ISO YYYY-MM-DD strings) ──

function padNumber(value: number, width: number): string {
  let text = String(value);
  while (text.length < width) text = "0" + text;
  return text;
}

function isoFromDate(dateObject: Date): string {
  return (
    padNumber(dateObject.getFullYear(), 4) +
    "-" +
    padNumber(dateObject.getMonth() + 1, 2) +
    "-" +
    padNumber(dateObject.getDate(), 2)
  );
}

function dateFromIso(isoString: string): Date {
  const pieces = isoString.split("-");
  return new Date(
    parseInt(pieces[0], 10),
    parseInt(pieces[1], 10) - 1,
    parseInt(pieces[2], 10)
  );
}

function addDays(dateObject: Date, dayCount: number): Date {
  const copy = new Date(dateObject.getTime());
  copy.setDate(copy.getDate() + dayCount);
  return copy;
}

/** Validate a (year, month, day) triple as a real calendar date. */
function isoFromParts(year: number, month: number, day: number): string {
  const candidate = new Date(year, month - 1, day);
  if (
    candidate.getFullYear() !== year ||
    candidate.getMonth() !== month - 1 ||
    candidate.getDate() !== day
  ) {
    return "";
  }
  return isoFromDate(candidate);
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

function segmentBuffer(segment: HTMLInputElement): string {
  return segment.dataset.typedDigits || "";
}

function setSegmentBuffer(segment: HTMLInputElement, buffer: string): void {
  segment.dataset.typedDigits = buffer;
  if (buffer === "") {
    segment.value = "";
    return;
  }
  const placeholder = segment.getAttribute("placeholder") ?? "";
  // Fill the placeholder from the right: typing 19 into YYYY shows YY19.
  segment.value = placeholder.slice(0, placeholder.length - buffer.length) + buffer;
}

function segmentsForSide(picker: HTMLElement, side: string): HTMLInputElement[] {
  return Array.from(
    picker.querySelectorAll<HTMLInputElement>(`input[data-date-side="${side}"]`)
  );
}

/** Recompute one hidden ISO input from its side's segment buffers. */
function syncHiddenFromSegments(picker: HTMLElement, side: string): boolean {
  const hidden = picker.querySelector<HTMLInputElement>(
    `input[data-date-range-hidden="${side}"]`
  )!;
  const partValues: Record<string, string> = {};
  let complete = true;
  segmentsForSide(picker, side).forEach((segment) => {
    const buffer = segmentBuffer(segment);
    if (buffer.length !== parseInt(segment.getAttribute("maxlength") ?? "", 10)) {
      complete = false;
    }
    partValues[segment.dataset.datePart ?? ""] = buffer;
  });
  const previousValue = hidden.value;
  if (complete) {
    hidden.value = isoFromParts(
      parseInt(partValues.year, 10),
      parseInt(partValues.month, 10),
      parseInt(partValues.day, 10)
    );
  } else {
    hidden.value = "";
  }
  return hidden.value !== previousValue;
}

/** Push an ISO value (or "") into a side's segments and hidden input. */
function setSideValue(picker: HTMLElement, side: string, isoString: string): void {
  const hidden = picker.querySelector<HTMLInputElement>(
    `input[data-date-range-hidden="${side}"]`
  )!;
  hidden.value = isoString;
  let partValues: Record<string, string> = { year: "", month: "", day: "" };
  if (isoString) {
    const pieces = isoString.split("-");
    partValues = { year: pieces[0], month: pieces[1], day: pieces[2] };
  }
  segmentsForSide(picker, side).forEach((segment) => {
    setSegmentBuffer(segment, partValues[segment.dataset.datePart ?? ""]);
  });
}

function initField(picker: HTMLElement, calendarState: CalendarState): void {
  const field = picker.querySelector<HTMLElement>("[data-date-range-field]")!;
  const segments = Array.from(
    picker.querySelectorAll<HTMLInputElement>("input[data-date-part]")
  );

  // Adopt server-rendered values (prefilled filter) as typed buffers.
  segments.forEach((segment) => {
    if (segment.value) setSegmentBuffer(segment, segment.value);
  });

  // Clicking anywhere in the container that is not a date part activates
  // the first date part.
  field.addEventListener("mousedown", (event) => {
    const target = event.target as Element;
    if (target.closest("input[data-date-part]")) return;
    if (target.closest("[data-date-range-calendar-toggle]")) return;
    event.preventDefault();
    segments[0].focus();
  });

  segments.forEach((segment, segmentIndex) => {
    segment.addEventListener("keydown", (event) => {
      if (event.key === "Tab") return; // native Tab / Shift+Tab navigation
      if (event.key === "Enter") return; // let the filter form submit
      if (event.key === "Backspace" || event.key === "Delete") {
        event.preventDefault();
        setSegmentBuffer(segment, "");
        syncHiddenFromSegments(picker, segment.dataset.dateSide ?? "");
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      event.preventDefault();
      if (!/^[0-9]$/.test(event.key)) return; // only numbers can be typed
      const maximumLength = parseInt(segment.getAttribute("maxlength") ?? "", 10);
      let buffer = segmentBuffer(segment);
      // Typing into an already-full part starts it over.
      buffer = buffer.length >= maximumLength ? event.key : buffer + event.key;
      setSegmentBuffer(segment, buffer);
      syncHiddenFromSegments(picker, segment.dataset.dateSide ?? "");
      if (buffer.length === maximumLength && segmentIndex + 1 < segments.length) {
        segments[segmentIndex + 1].focus();
      }
    });
    // Swallow any input that bypassed keydown (e.g. IME/paste).
    segment.addEventListener("input", () => {
      setSegmentBuffer(segment, segmentBuffer(segment));
    });
    segment.addEventListener("focus", () => {
      if (calendarState) calendarState.refreshFromField();
    });
  });
}

// ── DateRangeCalendar: popup month grid ────────────────────────────────

function createCalendarState(
  picker: HTMLElement
): { state: CalendarState; cleanup: () => void } {
  const popup = picker.querySelector<HTMLElement>("[data-date-range-calendar]")!;
  const grid = popup.querySelector<HTMLElement>("[data-date-range-grid]")!;
  const monthLabel = popup.querySelector<HTMLElement>("[data-date-range-month-label]")!;

  const today = new Date();

  function hiddenValue(side: string): string {
    return picker.querySelector<HTMLInputElement>(
      `input[data-date-range-hidden="${side}"]`
    )!.value;
  }

  const state: CalendarState = {
    open: false,
    viewYear: today.getFullYear(),
    viewMonth: today.getMonth(),
    startIso: "",
    endIso: "",
    anchor: "",
    hoverIso: "",
    readOnly: false,
    refreshFromField() {
      if (state.open) return;
      state.startIso = hiddenValue("min");
      state.endIso = hiddenValue("max");
    },
  };

  function syncSelectionToField(): void {
    setSideValue(picker, "min", state.startIso);
    setSideValue(picker, "max", state.endIso);
  }

  function openPopup(): void {
    state.startIso = hiddenValue("min");
    state.endIso = hiddenValue("max");
    state.anchor = state.startIso && state.endIso ? "end" : state.startIso ? "start" : "";
    state.readOnly = Boolean(state.startIso && state.endIso);
    state.hoverIso = "";
    const focusDate = state.startIso ? dateFromIso(state.startIso) : new Date();
    state.viewYear = focusDate.getFullYear();
    state.viewMonth = focusDate.getMonth();
    state.open = true;
    popup.classList.remove("hidden");
    render();
  }

  function closePopup(): void {
    state.open = false;
    state.hoverIso = "";
    popup.classList.add("hidden");
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
    state.viewYear = range[0].getFullYear();
    state.viewMonth = range[0].getMonth();
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
        state.readOnly ? TRACK_MUTED_CLASS : TRACK_FILLED_CLASS,
      ];
    }
    if (state.startIso && state.hoverIso && state.hoverIso !== state.startIso) {
      const lower = state.hoverIso < state.startIso ? state.hoverIso : state.startIso;
      const upper = state.hoverIso < state.startIso ? state.startIso : state.hoverIso;
      return [lower, upper, TRACK_OUTLINED_CLASS];
    }
    return null;
  }

  function dayCellClass(isoString: string, inViewMonth: boolean): string {
    const classes = [DAY_BASE_CLASS];
    const isStart = isoString === state.startIso;
    const isEnd = isoString === state.endIso;
    const isAnchor =
      (state.anchor === "start" && isStart) || (state.anchor === "end" && isEnd);
    const track = trackBounds();
    const inTrack = track !== null && isoString > track[0] && isoString < track[1];
    if (inTrack) {
      classes.push(track![2]);
    } else {
      classes.push(DAY_ROUNDED_CLASS);
    }
    if (isAnchor && !state.readOnly) {
      classes.push(DAY_ANCHOR_CLASS);
    } else if (isStart || isEnd) {
      classes.push(DAY_SELECTED_CLASS);
    } else if (!inViewMonth) {
      classes.push(DAY_OUTSIDE_MONTH_CLASS);
    }
    return classes.join(" ");
  }

  function render(): void {
    monthLabel.textContent = new Date(
      state.viewYear,
      state.viewMonth,
      1
    ).toLocaleDateString(undefined, { month: "long", year: "numeric" });

    grid.textContent = "";
    WEEKDAY_LABELS.forEach((weekdayLabel) => {
      const headerCell = document.createElement("span");
      headerCell.className = WEEKDAY_CLASS;
      headerCell.textContent = weekdayLabel;
      grid.appendChild(headerCell);
    });

    const firstOfMonth = new Date(state.viewYear, state.viewMonth, 1);
    // Monday-first offset of the leading overflow days.
    const leadingDays = (firstOfMonth.getDay() + 6) % 7;
    let cellDate = addDays(firstOfMonth, -leadingDays);
    for (let cellIndex = 0; cellIndex < 42; cellIndex++) {
      const isoString = isoFromDate(cellDate);
      const dayButton = document.createElement("button");
      dayButton.type = "button";
      dayButton.setAttribute("data-date", isoString);
      dayButton.className = dayCellClass(
        isoString,
        cellDate.getMonth() === state.viewMonth
      );
      dayButton.textContent = String(cellDate.getDate());
      grid.appendChild(dayButton);
      cellDate = addDays(cellDate, 1);
    }
  }

  // ── Wiring ──
  picker
    .querySelector<HTMLElement>("[data-date-range-calendar-toggle]")!
    .addEventListener("click", () => {
      if (state.open) closePopup();
      else openPopup();
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

  popup
    .querySelector<HTMLElement>("[data-date-range-prev]")!
    .addEventListener("click", () => {
      state.viewMonth -= 1;
      if (state.viewMonth < 0) {
        state.viewMonth = 11;
        state.viewYear -= 1;
      }
      render();
    });

  popup
    .querySelector<HTMLElement>("[data-date-range-next]")!
    .addEventListener("click", () => {
      state.viewMonth += 1;
      if (state.viewMonth > 11) {
        state.viewMonth = 0;
        state.viewYear += 1;
      }
      render();
    });

  popup.querySelectorAll<HTMLElement>("[data-date-range-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      applyPreset(button.getAttribute("data-date-range-preset") ?? "");
    });
  });

  // Cancel: close the popup and clear the selected dates.
  popup
    .querySelector<HTMLElement>("[data-date-range-cancel]")!
    .addEventListener("click", () => {
      clearSelection();
      closePopup();
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
    .querySelector<HTMLElement>("[data-date-range-select]")!
    .addEventListener("click", () => {
      closePopup();
    });

  const cleanup = bindPopupDismiss({
    host: picker,
    isOpen: () => state.open,
    close: closePopup,
  });

  return { state, cleanup };
}

function initPicker(picker: HTMLElement): () => void {
  const { state: calendarState, cleanup } = createCalendarState(picker);
  initField(picker, calendarState);
  return cleanup;
}

class DateRangePickerElement extends HTMLElement {
  private cleanup: (() => void) | null = null;

  connectedCallback(): void {
    this.cleanup = initPicker(this);
  }

  disconnectedCallback(): void {
    this.cleanup?.();
    this.cleanup = null;
  }
}

customElements.define("date-range-picker", DateRangePickerElement);
