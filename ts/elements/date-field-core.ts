/**
 * Shared segmented-date-entry engine, extracted from date-range-picker.ts so
 * date-picker.ts (single date) and date-range-picker.ts (two dates) drive the
 * same grammar instead of each growing its own. A "side" is an opaque id
 * ("min"/"max" for the range picker, "value" for a single date-picker); the
 * hidden-ISO-input lookup and the commit callback are injected so each caller
 * keeps its own hidden-input naming contract unchanged.
 */

// ── Date helpers (all local-time; values are ISO YYYY-MM-DD strings) ──

export function padNumber(value: number, width: number): string {
  let text = String(value);
  while (text.length < width) text = "0" + text;
  return text;
}

export function isoFromDate(dateObject: Date): string {
  return (
    padNumber(dateObject.getFullYear(), 4) +
    "-" +
    padNumber(dateObject.getMonth() + 1, 2) +
    "-" +
    padNumber(dateObject.getDate(), 2)
  );
}

export function dateFromIso(isoString: string): Date {
  const pieces = isoString.split("-");
  return new Date(
    parseInt(pieces[0], 10),
    parseInt(pieces[1], 10) - 1,
    parseInt(pieces[2], 10),
  );
}

export function addDays(dateObject: Date, dayCount: number): Date {
  const copy = new Date(dateObject.getTime());
  copy.setDate(copy.getDate() + dayCount);
  return copy;
}

/** Validate a (year, month, day) triple as a real calendar date. */
export function isoFromParts(year: number, month: number, day: number): string {
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

// ── Segment digit entry ─────────────────────────────────────────────────

export function segmentBuffer(segment: HTMLInputElement): string {
  return segment.dataset.typedDigits || "";
}

// The numeric bounds of a date part plus the value an empty part jumps to on
// the first ArrowUp/ArrowDown (day/month start at 01, year at the current year
// rather than 0001).
export interface PartRange {
  min: number;
  max: number;
  empty: number;
}

export function partRange(datePart: string): PartRange {
  if (datePart === "month") return { min: 1, max: 12, empty: 1 };
  if (datePart === "year") {
    return { min: 1, max: 9999, empty: new Date().getFullYear() };
  }
  return { min: 1, max: 31, empty: 1 }; // day
}

export interface DigitEntry {
  buffer: string;
  complete: boolean;
}

// Fold a freshly typed digit into a part's buffer, clamping to the part's max
// and deciding whether to auto-advance. A digit that cannot validly extend the
// current value (e.g. 9 into a ≤12 month, or a second digit pushing past the
// max) commits as a zero-padded single digit and completes; an ambiguous digit
// that could still take another (month 1 → 10/11/12) stays pending.
//
// Invariant: complete === true MUST imply buffer.length === width, because
// callers re-derive completeness from buffer length — that is why a
// completing single digit is padded to full width before returning.
export function applyDigit(
  buffer: string,
  digit: string,
  width: number,
  max: number,
): DigitEntry {
  if (buffer.length >= width) buffer = ""; // restart an already-full part
  let candidate = buffer + digit;
  if (parseInt(candidate, 10) > max) candidate = digit; // overflow → fresh ones digit
  const value = parseInt(candidate, 10);
  // Strict >: value*10 <= max means another digit could still land in range.
  const complete = candidate.length === width || value * 10 > max;
  if (complete) candidate = padNumber(value, width);
  return { buffer: candidate, complete };
}

export function setSegmentBuffer(segment: HTMLInputElement, buffer: string): void {
  segment.dataset.typedDigits = buffer;
  if (buffer === "") {
    segment.value = "";
    return;
  }
  const placeholder = segment.getAttribute("placeholder") ?? "";
  if (segment.dataset.datePart === "year") {
    // Fill the placeholder from the right: typing 19 into YYYY shows YY19.
    segment.value = placeholder.slice(0, placeholder.length - buffer.length) + buffer;
  } else {
    // Day/month show a pending single digit zero-padded: typing 1 shows 01.
    segment.value = buffer.padStart(placeholder.length, "0");
  }
}

// ── Paste parsing ────────────────────────────────────────────────────────

// Any run of dash/slash/dot/space characters separates the three numeric
// groups of a pasted date, regardless of the active presentation profile.
const PASTE_SEPARATOR = /[-/.\s]+/;
const ISO_PASTE_PATTERN = /^(\d{4})[-/.\s](\d{1,2})[-/.\s](\d{1,2})$/;

/**
 * Parse pasted clipboard text into an ISO date, or "" if it cannot be
 * unambiguously read as one.
 *
 * An unambiguous big-endian `YYYY?MM?DD` (any separator) is read as ISO
 * regardless of the active profile — a pasted ISO string must not be
 * misparsed as day-first/month-first. Otherwise the three separator-split
 * groups are mapped onto `partNamesInOrder` (the segments' own DOM order,
 * i.e. the active profile's order). A 2-digit year is rejected rather than
 * century-guessed — the caller retypes with a full year.
 */
export function parsePastedDate(text: string, partNamesInOrder: string[]): string {
  const trimmed = text.trim();

  const isoMatch = ISO_PASTE_PATTERN.exec(trimmed);
  if (isoMatch) {
    const [, year, month, day] = isoMatch;
    return isoFromParts(parseInt(year, 10), parseInt(month, 10), parseInt(day, 10));
  }

  const groups = trimmed.split(PASTE_SEPARATOR);
  if (groups.length !== 3 || partNamesInOrder.length !== 3) return "";
  if (!groups.every((group) => /^\d+$/.test(group))) return "";

  const values: Partial<Record<string, string>> = {};
  partNamesInOrder.forEach((partName, index) => {
    values[partName] = groups[index];
  });
  const year = values.year;
  const month = values.month;
  const day = values.day;
  if (!year || !month || !day) return "";
  if (year.length !== 4) return ""; // reject 2-digit years, no century-guessing

  return isoFromParts(parseInt(year, 10), parseInt(month, 10), parseInt(day, 10));
}

// ── Segment group wiring ─────────────────────────────────────────────────

export function segmentsForSide(
  picker: HTMLElement,
  side: string,
): HTMLInputElement[] {
  return Array.from(
    picker.querySelectorAll<HTMLInputElement>(`input[data-date-part][data-date-side="${side}"]`),
  );
}

export type HiddenResolver = (side: string) => HTMLInputElement | null;

/** Recompute one side's hidden ISO input from its segment buffers. Returns
 * whether the hidden value changed. */
export function syncHiddenFromSegments(
  picker: HTMLElement,
  side: string,
  resolveHidden: HiddenResolver,
  onCommit: (side: string) => void,
): boolean {
  const hidden = resolveHidden(side);
  if (!hidden) return false;
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
  hidden.value = complete
    ? isoFromParts(
        parseInt(partValues.year, 10),
        parseInt(partValues.month, 10),
        parseInt(partValues.day, 10),
      )
    : "";
  const changed = hidden.value !== previousValue;
  if (changed) onCommit(side);
  return changed;
}

/** Push an ISO value (or "") into a side's segments and hidden input WITHOUT
 * invoking onCommit — the write half shared with prefill hydration, which
 * runs on a detached, not-yet-connected clone and must stay silent. Returns
 * whether the hidden value changed. Null-guarded so partial markup
 * (synthetic fixtures, malformed ISO) degrades to a no-op, not a throw. */
export function writeSideValue(
  picker: HTMLElement,
  side: string,
  resolveHidden: HiddenResolver,
  isoString: string,
): boolean {
  const hidden = resolveHidden(side);
  if (!hidden) return false;
  const previousValue = hidden.value;
  hidden.value = isoString;
  let partValues: Record<string, string> = { year: "", month: "", day: "" };
  if (isoString) {
    const pieces = isoString.split("-");
    partValues = { year: pieces[0] ?? "", month: pieces[1] ?? "", day: pieces[2] ?? "" };
  }
  segmentsForSide(picker, side).forEach((segment) => {
    setSegmentBuffer(segment, partValues[segment.dataset.datePart ?? ""] ?? "");
  });
  return hidden.value !== previousValue;
}

/** Push an ISO value (or "") into a side's segments and hidden input, and
 * invoke onCommit if it changed. */
export function setSideValue(
  picker: HTMLElement,
  side: string,
  resolveHidden: HiddenResolver,
  onCommit: (side: string) => void,
  isoString: string,
): void {
  if (writeSideValue(picker, side, resolveHidden, isoString)) onCommit(side);
}

export interface SegmentFieldOptions {
  picker: HTMLElement;
  /** The field container: holds every side's segments (a range field holds
   * both min and max). A mousedown anywhere inside that isn't a segment or
   * the calendar toggle focuses the first segment; Left/Right navigation and
   * auto-advance flow across ALL segments in DOM order, spanning sides —
   * only hidden-input sync is scoped to the completing segment's own side. */
  field: HTMLElement;
  resolveHidden: HiddenResolver;
  /** Called after a side's hidden value actually changes (digit, arrow,
   * backspace, or a successful paste). */
  onCommit: (side: string) => void;
  /** Called when a segment gains focus (e.g. to refresh a calendar's view
   * from the current field value before it opens). */
  onFocus?: () => void;
}

/** Wire every segment in a field: digit typing, Backspace/Delete, Arrow
 * navigation/stepping (flat across sides), paste parsing (scoped to the
 * pasted-into segment's own side), and click-anywhere-focuses-first. */
export function bindSegmentField(options: SegmentFieldOptions): void {
  const segments = Array.from(
    options.field.querySelectorAll<HTMLInputElement>("input[data-date-part]"),
  );

  // Adopt server-rendered values (prefilled field) as typed buffers.
  segments.forEach((segment) => {
    if (segment.value) setSegmentBuffer(segment, segment.value);
  });

  options.field.addEventListener("mousedown", (event) => {
    const target = event.target as Element;
    if (target.closest("input[data-date-part]")) return;
    if (target.closest("[data-date-range-calendar-toggle], [data-date-picker-calendar-toggle]")) {
      return;
    }
    event.preventDefault();
    segments[0]?.focus();
  });

  segments.forEach((segment, segmentIndex) => {
    const side = segment.dataset.dateSide ?? "";
    segment.addEventListener("keydown", (event) => {
      if (event.key === "Tab") return; // native Tab / Shift+Tab navigation
      if (event.key === "Enter") return; // let the form submit
      if (event.key === "Backspace" || event.key === "Delete") {
        event.preventDefault();
        setSegmentBuffer(segment, "");
        syncHiddenFromSegments(options.picker, side, options.resolveHidden, options.onCommit);
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      // Arrow keys move between parts (Left/Right) or step the focused part's
      // value (Up/Down); handled before the digit-only path below. Out-of-range
      // index clamps (no wrap); Up/Down clamp at the part's range ends.
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const step = event.key === "ArrowRight" ? 1 : -1;
        const target = segments[segmentIndex + step];
        if (target) target.focus();
        return;
      }
      if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        event.preventDefault();
        const range = partRange(segment.dataset.datePart ?? "");
        const width = parseInt(segment.getAttribute("maxlength") ?? "", 10);
        const buffer = segmentBuffer(segment);
        let next: number;
        if (buffer === "") {
          next = range.empty;
        } else {
          next = parseInt(buffer, 10) + (event.key === "ArrowUp" ? 1 : -1);
        }
        if (next < range.min) next = range.min;
        if (next > range.max) next = range.max;
        setSegmentBuffer(segment, padNumber(next, width));
        syncHiddenFromSegments(options.picker, side, options.resolveHidden, options.onCommit);
        return;
      }
      event.preventDefault();
      if (!/^[0-9]$/.test(event.key)) return; // only numbers can be typed
      const width = parseInt(segment.getAttribute("maxlength") ?? "", 10);
      const max = partRange(segment.dataset.datePart ?? "").max;
      const { buffer, complete } = applyDigit(segmentBuffer(segment), event.key, width, max);
      setSegmentBuffer(segment, buffer);
      syncHiddenFromSegments(options.picker, side, options.resolveHidden, options.onCommit);
      if (complete && segmentIndex + 1 < segments.length) {
        segments[segmentIndex + 1].focus();
      }
    });
    // Swallow any input that bypassed keydown (e.g. IME); paste is handled
    // separately below and preventDefault'd there, so it never reaches here.
    segment.addEventListener("input", () => {
      setSegmentBuffer(segment, segmentBuffer(segment));
    });
    segment.addEventListener("paste", (event) => {
      event.preventDefault();
      const text = (event as ClipboardEvent).clipboardData?.getData("text") ?? "";
      const partNamesInOrder = segmentsForSide(options.picker, side).map(
        (candidate) => candidate.dataset.datePart ?? "",
      );
      const iso = parsePastedDate(text, partNamesInOrder);
      if (iso) setSideValue(options.picker, side, options.resolveHidden, options.onCommit, iso);
    });
    segment.addEventListener("focus", () => {
      options.onFocus?.();
    });
  });
}
