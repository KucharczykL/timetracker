/**
 * Shared segmented date/time entry engine, driven by an explicit per-segment
 * config rather than by a hard-coded idea of what a date is.
 *
 * date-picker.ts (single date) and date-range-picker.ts (two dates) bind the
 * same grammar. A "side" is an opaque id ("min"/"max" for the range picker,
 * "value" for a single date-picker); the hidden-ISO-input lookup and the
 * commit callback are injected so each caller keeps its own hidden-input
 * naming contract unchanged.
 *
 * Every segment's bounds, width, and stepping behaviour come from
 * `segmentSpec()`, which reads the active presentation contract first and
 * falls back to an exhaustive per-name table. There is deliberately no
 * fall-through: a name the contract does not define is left unbound instead of
 * being silently treated as a day.
 */

import {
  dayPeriodLabels,
  segmentRules,
  todayInPresentationZone,
} from "../date-time-presentation.js";
import type { SegmentName } from "../generated/date-time-presentation.js";

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

/**
 * Today at midnight, in the display zone (#949).
 *
 * Returns a `Date` and never `null`: with no readable contract the browser's
 * day stands, because a "Today" a day out beats presets that do nothing.
 */
export function todayInDisplayZone(): Date {
  const isoString = todayInPresentationZone();
  if (isoString) return dateFromIso(isoString);
  const browserToday = new Date();
  browserToday.setHours(0, 0, 0, 0);
  return browserToday;
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

// ── Segment config ───────────────────────────────────────────────────────

/** Everything the engine needs to know about one segment. */
export interface SegmentSpec {
  name: SegmentName;
  kind: "numeric" | "day_period";
  /** Typed width — how many digits fill this segment. */
  width: number;
  placeholder: string;
  minimum: number;
  maximum: number;
  /** Where an empty segment jumps on the first ArrowUp/ArrowDown. */
  emptyValue: number;
  /**
   * Fill the placeholder from the right while typing (`19` into `YYYY` shows
   * `YY19`) instead of zero-padding from the left (`1` into `MM` shows `01`).
   */
  fillFromRight: boolean;
}

interface SegmentBehaviour {
  emptyValue: (minimum: number) => number;
  fillFromRight: boolean;
  /** Bounds used only when the presentation contract is unreadable. */
  fallback: { minimum: number; maximum: number };
}

/**
 * Per-name behaviour, exhaustive over `SegmentName` so the compiler rejects a
 * new segment kind that nobody taught the engine about. This is what replaced
 * the old `partRange` if/else, whose final `return` treated *any* unrecognised
 * part as a day (1–31).
 *
 * The fallback bounds only apply when the contract cannot be read; the hour's
 * real range depends on `hour_cycle`, which is exactly why bounds are carried
 * in the contract rather than derived here.
 */
const SEGMENT_BEHAVIOUR: Record<SegmentName, SegmentBehaviour> = {
  // An empty year starts from this year.
  //
  // "This" is the display zone's year, not the browser's (#949).
  year: {
    emptyValue: () => todayInDisplayZone().getFullYear(),
    fillFromRight: true,
    fallback: { minimum: 1, maximum: 9999 },
  },
  month: {
    emptyValue: (minimum) => minimum,
    fillFromRight: false,
    fallback: { minimum: 1, maximum: 12 },
  },
  day: {
    emptyValue: (minimum) => minimum,
    fillFromRight: false,
    fallback: { minimum: 1, maximum: 31 },
  },
  hour: {
    emptyValue: (minimum) => minimum,
    fillFromRight: false,
    fallback: { minimum: 0, maximum: 23 },
  },
  minute: {
    emptyValue: (minimum) => minimum,
    fillFromRight: false,
    fallback: { minimum: 0, maximum: 59 },
  },
  day_period: {
    emptyValue: (minimum) => minimum,
    fillFromRight: false,
    fallback: { minimum: 0, maximum: 1 },
  },
};

function isSegmentName(value: string): value is SegmentName {
  return value in SEGMENT_BEHAVIOUR;
}

const specCache = new WeakMap<HTMLInputElement, SegmentSpec>();

/**
 * The config for one rendered segment, or `null` if its `data-date-part` is
 * not a name the engine knows — in which case the caller leaves it alone
 * rather than guessing at its bounds.
 */
export function segmentSpec(segment: HTMLInputElement): SegmentSpec | null {
  const cached = specCache.get(segment);
  if (cached) return cached;

  const name = segment.dataset.datePart ?? "";
  if (!isSegmentName(name)) return null;
  const behaviour = SEGMENT_BEHAVIOUR[name];
  const rules = segmentRules(name);
  const minimum = rules?.minimumValue ?? behaviour.fallback.minimum;
  const maximum = rules?.maximumValue ?? behaviour.fallback.maximum;
  const placeholder = segment.getAttribute("placeholder") ?? "";
  const spec: SegmentSpec = {
    name,
    kind: rules?.kind ?? (name === "day_period" ? "day_period" : "numeric"),
    width: parseInt(segment.getAttribute("maxlength") ?? "", 10) || placeholder.length,
    placeholder,
    minimum,
    maximum,
    emptyValue: behaviour.emptyValue(minimum),
    fillFromRight: behaviour.fillFromRight,
  };
  specCache.set(segment, spec);
  return spec;
}

// ── Segment digit entry ─────────────────────────────────────────────────

/**
 * The typed buffer stays on the element (`data-typed-digits`) rather than in
 * engine-side state, because the filter builder clones widget markup while it
 * is still detached and prefills it through `writeSideValue` — with no bound
 * engine in existence yet. Keeping it on the node is what lets that clone
 * carry its value into the DOM and be adopted when it is finally bound.
 */
export function segmentBuffer(segment: HTMLInputElement): string {
  return segment.dataset.typedDigits || "";
}

export interface DigitEntry {
  buffer: string;
  complete: boolean;
}

// Merge a freshly typed digit into a part's buffer, clamping to the part's max
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

/**
 * Announce a segment's current value to assistive technology.
 *
 * Stamped here, at runtime, rather than server-side: `aria-valuenow` changes
 * on every keystroke, so it is widget state, not document structure — and a
 * JS write to a focused text input's `.value` is not reliably announced, which
 * is why arrow-stepping was silent to a screen reader before this. The
 * enclosing `role="group"` and its label are server-rendered and stay so.
 */
function applySegmentAria(
  segment: HTMLInputElement,
  spec: SegmentSpec,
  buffer: string,
): void {
  segment.setAttribute("role", "spinbutton");
  segment.setAttribute("aria-valuemin", String(spec.minimum));
  segment.setAttribute("aria-valuemax", String(spec.maximum));
  if (buffer === "" || buffer.length !== spec.width) {
    // The value is genuinely indeterminate, so aria-valuenow stays absent —
    // but absent alone is not silence: a screen reader falls back to zero, so
    // an untouched field announced every segment as "spinbutton, zero" while
    // showing YYYY. Say the indeterminate state in words instead, and let a
    // half-typed buffer read back the digits entered so far.
    segment.removeAttribute("aria-valuenow");
    segment.setAttribute("aria-valuetext", buffer === "" ? "blank" : buffer);
    return;
  }
  const value = parseInt(buffer, 10);
  segment.setAttribute("aria-valuenow", String(value));
  // Every segment states its value as text, not only the day period. A
  // spinbutton with a bare valuenow invites the reader to announce its
  // position within valuemin..valuemax as a percentage — VoiceOver read the
  // year 2026 as "2026, 20.3 percent" (2025/9998) and the month 7 as
  // "7, 54.5 percent" (6/11). A date segment has no meaningful position in its
  // range, and valuetext is what suppresses that reading.
  if (spec.kind === "day_period") {
    // A two-state toggle: the number alone ("0") announces nothing useful.
    const labels = dayPeriodLabels();
    segment.setAttribute(
      "aria-valuetext",
      labels ? (value === 0 ? labels.am : labels.pm) : buffer,
    );
  } else {
    segment.setAttribute("aria-valuetext", String(value));
  }
}

/** The visible text for a day-period buffer ("00"/"01" → the contract's own
 * AM/PM labels). Django's `cs` locale renders "dop."/"odp.", so the labels
 * cannot be hard-coded and neither can the keys that select them. */
export function dayPeriodText(buffer: string): string {
  const labels = dayPeriodLabels();
  if (!labels || buffer === "") return "";
  return parseInt(buffer, 10) === 0 ? labels.am : labels.pm;
}

export function setSegmentBuffer(segment: HTMLInputElement, buffer: string): void {
  segment.dataset.typedDigits = buffer;
  const spec = segmentSpec(segment);
  if (spec) applySegmentAria(segment, spec, buffer);
  if (buffer === "") {
    segment.value = "";
    return;
  }
  if (spec?.kind === "day_period") {
    // The buffer stays numeric so stepping and the wire codec need no special
    // case; only what the user sees is the label.
    segment.value = dayPeriodText(buffer);
    return;
  }
  const placeholder = spec?.placeholder ?? segment.getAttribute("placeholder") ?? "";
  if (spec?.fillFromRight) {
    segment.value = placeholder.slice(0, placeholder.length - buffer.length) + buffer;
  } else {
    segment.value = buffer.padStart(placeholder.length, "0");
  }
}

/** The buffer a typed key selects in a day-period segment, or "" if the key
 * matches neither label. Matched against the contract's labels rather than a
 * literal a/p, which "dop."/"odp." would both fail. */
export function dayPeriodBufferForKey(key: string, width: number): string {
  const labels = dayPeriodLabels();
  if (!labels) return "";
  const typed = key.toLowerCase();
  if (labels.am.toLowerCase().startsWith(typed)) return padNumber(0, width);
  if (labels.pm.toLowerCase().startsWith(typed)) return padNumber(1, width);
  return "";
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

/** Per-segment buffers keyed by `data-date-part`. */
export type PartValues = Record<string, string>;

/**
 * Translates between the segment buffers and the value the server binds.
 *
 * The engine deliberately knows nothing about the wire format: a date field's
 * is `YYYY-MM-DD`, a datetime field's is an offset-qualified wall clock. This
 * is the last of the "it's a date" assumptions that used to be baked into the
 * sync helpers below.
 */
export interface FieldCodec {
  /** Segment buffers → wire value. `""` when the field is incomplete. */
  encode(values: PartValues, complete: boolean): string;
  /** Wire value → segment buffers. Missing parts come back as `""`. */
  decode(value: string): PartValues;
}

/** The `YYYY-MM-DD` codec every date field uses. */
export const dateCodec: FieldCodec = {
  encode(values, complete) {
    if (!complete) return "";
    return isoFromParts(
      parseInt(values.year, 10),
      parseInt(values.month, 10),
      parseInt(values.day, 10),
    );
  },
  decode(value) {
    if (!value) return { year: "", month: "", day: "" };
    const pieces = value.split("-");
    return { year: pieces[0] ?? "", month: pieces[1] ?? "", day: pieces[2] ?? "" };
  },
};

/** The default paste hook: the three-numeric-group date grammar, expressed as
 * the segment buffers it fills. A datetime field supplies its own, which keeps
 * whatever segments the pasted text says nothing about. */
export function pastedDateParts(
  text: string,
  partNamesInOrder: string[],
): PartValues | null {
  const isoString = parsePastedDate(text, partNamesInOrder);
  return isoString ? dateCodec.decode(isoString) : null;
}

/** Read one side's segment buffers, and whether every one of them is filled. */
export function readSideParts(
  picker: HTMLElement,
  side: string,
): { values: PartValues; complete: boolean } {
  const values: PartValues = {};
  let complete = true;
  segmentsForSide(picker, side).forEach((segment) => {
    const buffer = segmentBuffer(segment);
    const spec = segmentSpec(segment);
    if (!spec || buffer.length !== spec.width) complete = false;
    values[segment.dataset.datePart ?? ""] = buffer;
  });
  return { values, complete };
}

/** Recompute one side's hidden input from its segment buffers. Returns
 * whether the hidden value changed. */
export function syncHiddenFromSegments(
  picker: HTMLElement,
  side: string,
  resolveHidden: HiddenResolver,
  onCommit: (side: string) => void,
  codec: FieldCodec = dateCodec,
): boolean {
  const hidden = resolveHidden(side);
  if (!hidden) return false;
  const { values, complete } = readSideParts(picker, side);
  const previousValue = hidden.value;
  hidden.value = codec.encode(values, complete);
  const changed = hidden.value !== previousValue;
  if (changed) onCommit(side);
  return changed;
}

/** Push a wire value (or "") into a side's segments and hidden input WITHOUT
 * invoking onCommit — the write half shared with prefill hydration, which
 * runs on a detached, not-yet-connected clone and must stay silent. Returns
 * whether the hidden value changed. Null-guarded so partial markup
 * (synthetic fixtures, malformed values) degrades to a no-op, not a throw. */
export function writeSideValue(
  picker: HTMLElement,
  side: string,
  resolveHidden: HiddenResolver,
  isoString: string,
  codec: FieldCodec = dateCodec,
): boolean {
  const hidden = resolveHidden(side);
  if (!hidden) return false;
  const previousValue = hidden.value;
  hidden.value = isoString;
  const partValues = codec.decode(isoString);
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
  codec: FieldCodec = dateCodec,
): void {
  if (writeSideValue(picker, side, resolveHidden, isoString, codec)) onCommit(side);
}

export interface SegmentFieldOptions {
  picker: HTMLElement;
  /** The field container: holds every side's segments (a range field holds
   * both min and max). A mousedown anywhere inside that isn't a segment or
   * the calendar toggle focuses the nearest segment; Left/Right navigation and
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
  /** How segment buffers become the value the server binds. Defaults to the
   * `YYYY-MM-DD` date codec. */
  codec?: FieldCodec;
  /** Parse pasted text into the side's new segment buffers, or `null` to
   * ignore the paste. Takes the side's current buffers so a partial paste (a
   * bare time into a datetime field) can keep the rest, which a wire value —
   * all-or-nothing by construction — could not express. Defaults to the
   * three-numeric-group date grammar. */
  parsePaste?: (
    text: string,
    partNamesInOrder: string[],
    current: PartValues,
  ) => PartValues | null;
}

/**
 * The bound state of one field: its segments, their specs, and the listeners
 * wiring the grammar onto them.
 */
class SegmentedField {
  private readonly options: SegmentFieldOptions;
  private readonly segments: HTMLInputElement[];

  constructor(options: SegmentFieldOptions) {
    this.options = options;
    this.segments = Array.from(
      options.field.querySelectorAll<HTMLInputElement>("input[data-date-part]"),
    );
  }

  bind(): void {
    // The server renders the field `inert`, so before this runs it is visible
    // but unreachable: it shows the stored date and cannot be focused or
    // typed into. That matters because the segments carry no `name` — they
    // are not submitted — so anything typed before the engine binds would be
    // silently discarded. If the script never arrives, an inert field showing
    // the date read-only is the honest degraded state.
    this.options.field.removeAttribute("inert");

    // Adopt server-rendered values (prefilled field) as typed buffers, which
    // also stamps each segment's initial ARIA state.
    this.segments.forEach((segment) => {
      // A day period renders its label ("PM"), not its buffer ("01"), so the
      // server states the buffer explicitly; everywhere else the two agree
      // and the rendered value is the buffer.
      const rendered = segment.dataset.typedDigits || segment.value;
      setSegmentBuffer(segment, rendered);
    });

    this.options.field.addEventListener("mousedown", (event) => {
      const target = event.target as Element;
      if (target.closest("input[data-date-part]")) return;
      // Any control in the field owns its own click and its own focus — the
      // calendar toggle, a datetime field's copy arrow, a checkbox beside the
      // segments. Only genuinely blank space redirects focus into the nearest
      // segment. A label counts: clicking one focuses the control it names.
      if (target.closest("a, button, input, label, select, textarea, [tabindex]"))
        return;
      event.preventDefault();
      this.nearestSegment(event as MouseEvent)?.focus();
    });

    this.segments.forEach((segment, index) => this.bindSegment(segment, index));
  }

  /**
   * The segment closest to a click in the field's blank space. Focusing the
   * first one instead teleports focus to the month when the user taps beside
   * the minutes — wrong on any field wide enough to have blank space, and
   * wrong on every wrapped one.
   */
  private nearestSegment(event: MouseEvent): HTMLInputElement | undefined {
    let best: HTMLInputElement | undefined;
    let bestDistance = Infinity;
    for (const segment of this.segments) {
      const box = segment.getBoundingClientRect();
      const horizontal = Math.max(box.left - event.clientX, event.clientX - box.right, 0);
      const vertical = Math.max(box.top - event.clientY, event.clientY - box.bottom, 0);
      const distance = Math.hypot(horizontal, vertical);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = segment;
      }
    }
    return best ?? this.segments[0];
  }

  private get codec(): FieldCodec {
    return this.options.codec ?? dateCodec;
  }

  private commitSide(side: string): void {
    syncHiddenFromSegments(
      this.options.picker,
      side,
      this.options.resolveHidden,
      this.options.onCommit,
      this.codec,
    );
  }

  private bindSegment(segment: HTMLInputElement, index: number): void {
    const side = segment.dataset.dateSide ?? "";
    segment.addEventListener("keydown", (event) => {
      if (event.key === "Tab") return; // native Tab / Shift+Tab navigation
      if (event.key === "Enter") return; // let the form submit
      if (event.key === "Backspace" || event.key === "Delete") {
        event.preventDefault();
        setSegmentBuffer(segment, "");
        this.commitSide(side);
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      // Arrow keys move between parts (Left/Right) or step the focused part's
      // value (Up/Down); handled before the digit-only path below. Out-of-range
      // index clamps (no wrap); Up/Down clamp at the part's range ends.
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const step = event.key === "ArrowRight" ? 1 : -1;
        this.segments[index + step]?.focus();
        return;
      }
      const spec = segmentSpec(segment);
      if (!spec) return; // unknown segment: never guess at its bounds
      if (event.key === "ArrowUp" || event.key === "ArrowDown") {
        event.preventDefault();
        const buffer = segmentBuffer(segment);
        let next =
          buffer === ""
            ? spec.emptyValue
            : parseInt(buffer, 10) + (event.key === "ArrowUp" ? 1 : -1);
        if (next < spec.minimum) next = spec.minimum;
        if (next > spec.maximum) next = spec.maximum;
        setSegmentBuffer(segment, padNumber(next, spec.width));
        this.commitSide(side);
        return;
      }
      event.preventDefault();
      if (spec.kind === "day_period") {
        const buffer = dayPeriodBufferForKey(event.key, spec.width);
        if (!buffer) return;
        setSegmentBuffer(segment, buffer);
        this.commitSide(side);
        if (index + 1 < this.segments.length) this.segments[index + 1].focus();
        return;
      }
      if (!/^[0-9]$/.test(event.key)) return; // only numbers can be typed
      const { buffer, complete } = applyDigit(
        segmentBuffer(segment),
        event.key,
        spec.width,
        spec.maximum,
      );
      setSegmentBuffer(segment, buffer);
      this.commitSide(side);
      if (complete && index + 1 < this.segments.length) {
        this.segments[index + 1].focus();
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
      const sideSegments = segmentsForSide(this.options.picker, side);
      const partNamesInOrder = sideSegments.map(
        (candidate) => candidate.dataset.datePart ?? "",
      );
      const parse = this.options.parsePaste ?? pastedDateParts;
      const { values } = readSideParts(this.options.picker, side);
      const parsed = parse(text, partNamesInOrder, values);
      if (!parsed) return;
      sideSegments.forEach((sideSegment) => {
        setSegmentBuffer(sideSegment, parsed[sideSegment.dataset.datePart ?? ""] ?? "");
      });
      this.commitSide(side);
    });
    segment.addEventListener("focus", () => {
      this.options.onFocus?.();
    });
  }
}

/** Wire every segment in a field: digit typing, Backspace/Delete, Arrow
 * navigation/stepping (flat across sides), paste parsing (scoped to the
 * pasted-into segment's own side), and click-anywhere-focuses-nearest. */
export function bindSegmentField(options: SegmentFieldOptions): void {
  new SegmentedField(options).bind();
}
