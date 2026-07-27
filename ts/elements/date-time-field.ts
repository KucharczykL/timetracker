/**
 * DateTimeField — the segmented datetime input (issue #511).
 *
 * Drives the DateTimePicker component (common/components/date_time_picker.py),
 * which replaces native `<input type="datetime-local">` on the Session and
 * GameStatusChange forms so the account's DATETIME_FORMAT preference controls
 * the visible segment order *and* the hour cycle.
 *
 * Almost everything here is the date field's: the same segment-entry engine
 * (date-field-core.ts), the same month-grid calendar (date-calendar-core.ts),
 * the same `<drop-down behavior="date-calendar">` popup host. Three things are
 * this element's own:
 *
 * - The wire codec is `createDateTimeCodec` (date-time-codec.ts), so the
 *   committed value is an offset-qualified wall clock rather than an ISO date.
 * - Picking a calendar day changes only the date segments. A datetime field's
 *   calendar has no opinion about the time, and overwriting a typed one would
 *   be the widget silently discarding input.
 * - It absorbs the old `<session-timestamp-buttons>`: "Now" is a calendar
 *   footer button, and copy-to-the-other-timestamp is an arrow in the field
 *   that calls `setValue()` on its peer. Those buttons wrote formatted strings
 *   into `#id_timestamp_start`, which is a *segment* now — they could not
 *   survive this widget, and `setValue()` is the API that replaces them.
 */
import {
  bindSegmentField,
  dateCodec,
  isoFromDate,
  readSideParts,
  segmentsForSide,
  setSegmentBuffer,
  syncHiddenFromSegments,
  type PartValues,
} from "./date-field-core.js";
import {
  createDateTimeCodec,
  parsePastedWallClock,
  type DateTimeCodec,
} from "./date-time-codec.js";
import { nowInPresentationZone, segmentRules } from "../date-time-presentation.js";
import {
  bindCalendarNav,
  bindCalendarPopupHost,
  dayVariantClass,
  renderMonthCalendar,
  todayView,
  viewFromIso,
  type MonthCalendarView,
} from "./date-calendar-core.js";

export const DATE_TIME_FIELD_CHANGE_EVENT = "date-time-field:change";

export interface DateTimeFieldChangeDetail {
  value: string;
}

// The single side id this element's shared-engine hooks use — DateRangePicker
// keys its hooks by side ("min"/"max"); a single datetime field has exactly one.
const SIDE = "value";

function resolveHidden(host: HTMLElement): HTMLInputElement | null {
  return host.querySelector<HTMLInputElement>("input[data-date-time-hidden]");
}

/** The date half of the committed value, for the calendar's selected day. */
function selectedIsoFrom(host: HTMLElement): string {
  const value = resolveHidden(host)?.value ?? "";
  return /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : "";
}

/** Whether this profile renders a day period, i.e. whether it is 12-hour. */
function hasDayPeriod(host: HTMLElement): boolean {
  return segmentsForSide(host, SIDE).some(
    (segment) => segment.dataset.datePart === "day_period",
  );
}

/** The date segments' names in profile order, which is what the paste grammar
 * maps its numeric groups onto. */
function datePartNames(host: HTMLElement): string[] {
  return segmentsForSide(host, SIDE)
    .map((segment) => segment.dataset.datePart ?? "")
    .filter((name) => segmentRules(name)?.run === "date");
}

/** Midnight for whichever hour cycle is rendered, as segment buffers. */
function midnightParts(twelveHour: boolean): PartValues {
  return twelveHour
    ? { hour: "12", minute: "00", day_period: "00" }
    : { hour: "00", minute: "00" };
}

class DateTimeFieldElement extends HTMLElement {
  private initialized = false;
  private codec!: DateTimeCodec;

  connectedCallback(): void {
    if (this.initialized) return;
    this.initialized = true;
    // The residual (seconds, microseconds) is read from the value the field was
    // rendered with, so the codec has to be built before anything writes.
    this.codec = createDateTimeCodec(resolveHidden(this)?.value ?? "");
    this.initCalendar();
    this.initField();
    this.initCopyControl();
  }

  /**
   * Replace the whole value from a wire string (or "" to clear), re-deriving
   * every segment. The public API the copy arrow uses, and the reason the
   * element carries `field-name`: a control on one datetime field addresses
   * the *widget* it writes into, not that widget's hidden input, because only
   * the widget knows how to turn a value back into segments.
   */
  setValue(wireValue: string): void {
    this.codec.adopt(wireValue);
    this.writeParts(this.codec.decode(wireValue));
  }

  private announceChange(): void {
    this.dispatchEvent(
      new CustomEvent<DateTimeFieldChangeDetail>(DATE_TIME_FIELD_CHANGE_EVENT, {
        bubbles: true,
        detail: { value: resolveHidden(this)?.value ?? "" },
      }),
    );
  }

  /**
   * Push segment buffers into the field and re-derive the hidden value from
   * them. Every programmatic write goes through here rather than through
   * `setSideValue`, so the committed value is always the codec's own encoding
   * — a caller cannot commit a wall clock that never got its offset resolved.
   */
  private writeParts(parts: PartValues): void {
    segmentsForSide(this, SIDE).forEach((segment) => {
      setSegmentBuffer(segment, parts[segment.dataset.datePart ?? ""] ?? "");
    });
    syncHiddenFromSegments(
      this,
      SIDE,
      () => resolveHidden(this),
      () => this.announceChange(),
      this.codec,
    );
  }

  private initField(): void {
    const field = this.querySelector<HTMLElement>("[data-date-picker-field]")!;
    bindSegmentField({
      picker: this,
      field,
      resolveHidden: () => resolveHidden(this),
      onCommit: () => this.announceChange(),
      onFocus: () => this.calendarState?.refreshFromField(),
      codec: this.codec,
      parsePaste: (text, _partNames, current) => {
        const pasted = parsePastedWallClock(text, datePartNames(this));
        if (!pasted) return null;
        const parts = { ...current };
        if (pasted.date) Object.assign(parts, dateCodec.decode(pasted.date));
        if (pasted.hour) {
          // Decoding a synthetic wire value is what folds a 24-hour clock into
          // whichever segments this profile renders, day period included.
          const time = this.codec.decode(`2000-01-01T${pasted.hour}:${pasted.minute}`);
          Object.assign(parts, {
            hour: time.hour,
            minute: time.minute,
            day_period: time.day_period,
          });
        }
        return parts;
      },
    });
  }

  private calendarState?: {
    view: MonthCalendarView;
    selectedIso: string;
    refreshFromField: () => void;
  };

  private initCalendar(): void {
    // The calendar shell reuses DateRangePicker's data-date-range-* hooks
    // (documented shared contract, not a range-specific naming leak).
    const popup = this.querySelector<HTMLElement>("[data-date-range-calendar]")!;
    const grid = popup.querySelector<HTMLElement>("[data-date-range-grid]")!;
    const monthLabel = popup.querySelector<HTMLElement>("[data-date-range-month-label]")!;
    const dayTemplate = popup.querySelector<HTMLTemplateElement>(
      '[data-date-range-template="day"]',
    );
    const toggleButton = this.querySelector<HTMLElement>(
      "[data-date-picker-calendar-toggle]",
    );

    const state = {
      view: todayView(),
      selectedIso: "",
      refreshFromField: () => {
        if (host.isOpen()) return;
        state.selectedIso = selectedIsoFrom(this);
      },
    };
    this.calendarState = state;

    const todayIso = isoFromDate(new Date());

    const dayCellClass = (isoString: string, inViewMonth: boolean): string => {
      if (isoString === state.selectedIso) return dayVariantClass("selected");
      return dayVariantClass(inViewMonth ? "default" : "adjacent");
    };

    const dayCellAria = (isoString: string, inViewMonth: boolean) => ({
      label: `${isoString}${inViewMonth ? "" : " (adjacent month)"}`,
      selected: isoString === state.selectedIso,
      current: isoString === todayIso,
    });

    const render = (): void => {
      renderMonthCalendar(state.view, {
        grid,
        monthLabel,
        dayTemplate,
        dayCellClass,
        dayCellAria,
      });
    };

    const host = bindCalendarPopupHost({
      picker: this,
      popup,
      toggleButton,
      idPrefix: "date-time-calendar",
      beforeOpen: () => {
        state.selectedIso = selectedIsoFrom(this);
        state.view = state.selectedIso ? viewFromIso(state.selectedIso) : todayView();
      },
      render,
    });

    grid.addEventListener("click", (event) => {
      const dayButton = (event.target as Element).closest("button[data-date]");
      if (!dayButton) return;
      const isoString = dayButton.getAttribute("data-date") ?? "";
      state.selectedIso = isoString;
      // Only the date segments move: the time is the user's, typed or not.
      const parts = { ...readSideParts(this, SIDE).values };
      Object.assign(parts, dateCodec.decode(isoString));
      if (!parts.hour) Object.assign(parts, midnightParts(hasDayPeriod(this)));
      if (!parts.minute) parts.minute = "00";
      this.writeParts(parts);
      host.close();
    });

    bindCalendarNav(popup, state, render);

    popup
      .querySelector<HTMLElement>("[data-date-range-now]")
      ?.addEventListener("click", () => {
        // The account's wall clock, never the browser's: the server reads this
        // field in the account's zone, so the two differing would store an
        // instant the user never picked.
        const now = nowInPresentationZone();
        if (!now) return;
        this.setValue(now);
        state.selectedIso = selectedIsoFrom(this);
        state.view = viewFromIso(state.selectedIso);
        render();
      });

    popup
      .querySelector<HTMLElement>("[data-date-range-clear]")!
      .addEventListener("click", () => {
        state.selectedIso = "";
        this.setValue("");
        render();
      });
  }

  private initCopyControl(): void {
    const copyButton = this.querySelector<HTMLElement>("[data-date-time-copy]");
    copyButton?.addEventListener("click", () => {
      const targetName = copyButton.getAttribute("data-date-time-copy") ?? "";
      const target = document.querySelector<DateTimeFieldElement>(
        `date-time-field[field-name="${targetName}"]`,
      );
      target?.setValue(resolveHidden(this)?.value ?? "");
    });
  }
}

customElements.define("date-time-field", DateTimeFieldElement);
