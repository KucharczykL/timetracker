/**
 * TemporalField — the browser half of a date at any precision.
 *
 * The server renders every control (common/components/temporal_field.py):
 * a shape select, four number inputs and two checkboxes per endpoint, and
 * — hidden — a segmented date, three nameless toggles, a disabled radio
 * group for how the value ends, and a live region.
 * This element hides the first set, shows the second, and derives the
 * shape from what a person fills. With no script the first set stands and
 * stores the same value.
 *
 * The segments ride the shared engine (date-field-core.ts) through a
 * partial-date codec. Its value goes to an unnamed scratch input, never to
 * the wire: every commit reads the segment buffers and writes them out to
 * the named inputs the server already parses.
 */
import {
  bindSegmentField,
  readSideParts,
  segmentBuffer,
  segmentSpec,
  segmentsForSide,
  setSegmentBuffer,
  type PartValues,
} from "./date-field-core.js";
import { decadeStart, temporalCodec } from "./temporal-codec.js";

/**
 * What one control announces when its value moves.
 *
 * The segment engine takes every digit keydown and writes the buffers
 * itself, so nothing native fires. A peer that watches this field has no
 * other way to hear it.
 */
export const TEMPORAL_FIELD_CHANGE_EVENT = "temporal-field:change";

const ENDPOINTS = ["start", "end"] as const;
/** Which end a control names. */
type Endpoint = (typeof ENDPOINTS)[number];
/** How a value ends, as the one radio group states it. */
const END_SHAPES = ["end_none", "end_date", "end_open"] as const;
type EndShape = (typeof END_SHAPES)[number];

/** A side this element does not name is left alone. */
function isEndpoint(side: string): side is Endpoint {
  return (ENDPOINTS as readonly string[]).includes(side);
}

export function namedInput(
  host: HTMLElement,
  key: string,
): HTMLInputElement | HTMLSelectElement | null {
  return host.querySelector<HTMLInputElement | HTMLSelectElement>(
    `[data-temporal-input="${key}"]`,
  );
}

function setNamed(host: HTMLElement, key: string, value: string): void {
  const control = namedInput(host, key);
  if (control) control.value = value;
}

function scratchInput(
  host: HTMLElement,
  endpoint: Endpoint,
): HTMLInputElement | null {
  return host.querySelector<HTMLInputElement>(
    `input[data-temporal-scratch="${endpoint}"]`,
  );
}

function toggleBox(host: HTMLElement, toggle: string): HTMLInputElement | null {
  return host.querySelector<HTMLInputElement>(`[data-temporal-toggle="${toggle}"]`);
}

export function isToggled(host: HTMLElement, toggle: string): boolean {
  return toggleBox(host, toggle)?.checked ?? false;
}

/** The boxes that qualify one end, decade included. */
function endpointBoxes(host: HTMLElement, endpoint: Endpoint): HTMLInputElement[] {
  return [
    namedInput(host, `${endpoint}_approximate`),
    namedInput(host, `${endpoint}_uncertain`),
    toggleBox(host, `whole_decade_${endpoint}`),
  ].filter((box) => box instanceof HTMLInputElement);
}

/** Empty one end, so a shape that never reads it posts nothing. */
function clearEndpoint(host: HTMLElement, endpoint: Endpoint): void {
  segmentsForSide(host, endpoint).forEach((segment) => setSegmentBuffer(segment, ""));
  const scratch = scratchInput(host, endpoint);
  if (scratch) scratch.value = "";
  // A qualifier with no date beside it is refused, not stored.
  endpointBoxes(host, endpoint).forEach((box) => {
    box.checked = false;
  });
  paintDecade(host, endpoint, false);
}

/** An open end states no date, so nothing here qualifies one. */
function setEndpointOpen(host: HTMLElement, endpoint: Endpoint, open: boolean): void {
  if (open) clearEndpoint(host, endpoint);
  endpointBoxes(host, endpoint).forEach((box) => {
    box.disabled = open;
  });
  show(host.querySelector(`[data-temporal-segments="${endpoint}"]`), !open);
}

function endShapeBoxes(host: HTMLElement): HTMLInputElement[] {
  return END_SHAPES.map((shape) => toggleBox(host, shape)).filter(
    (box) => box instanceof HTMLInputElement,
  );
}

/** Which of the three the group is on. */
function endShape(host: HTMLElement): EndShape {
  return END_SHAPES.find((shape) => isToggled(host, shape)) ?? "end_none";
}

function setEndShape(host: HTMLElement, shape: EndShape): void {
  const box = toggleBox(host, shape);
  if (box) box.checked = true;
}

/**
 * Whether the endpoint holds anything its shape counts.
 *
 * Under the decade box only the year counts: a hidden month or day would
 * announce a decade nobody typed a year for.
 */
function endpointHasValue(host: HTMLElement, endpoint: Endpoint): boolean {
  const { values } = readSideParts(host, endpoint);
  if (isToggled(host, `whole_decade_${endpoint}`)) return Boolean(values.year);
  return Boolean(values.year || values.month || values.day);
}

export function currentKind(host: HTMLElement): string {
  const start = endpointHasValue(host, "start");
  const end = endpointHasValue(host, "end");
  if (!start && !end) return "unknown";
  if (isToggled(host, "open_start")) return "until";
  const shape = endShape(host);
  if (shape === "end_open") return "since";
  if (shape === "end_date") return "range";
  return start ? "date" : "unknown";
}

/** What a person typed before the decade box swallowed it. */
const typedYears = new WeakMap<HTMLElement, Record<string, string>>();

function rememberYear(host: HTMLElement, endpoint: Endpoint, year: string): void {
  const remembered = typedYears.get(host) ?? {};
  remembered[endpoint] = year;
  typedYears.set(host, remembered);
}

function yearSegmentFor(
  host: HTMLElement,
  endpoint: Endpoint,
): HTMLInputElement | undefined {
  return segmentsForSide(host, endpoint).find(
    (segment) => segment.dataset.datePart === "year",
  );
}

function endpointPart(
  host: HTMLElement,
  endpoint: Endpoint,
  part: string,
): Element | null {
  return host.querySelector(
    `[data-temporal-endpoint="${endpoint}"] [data-temporal-part="${part}"]`,
  );
}

/** One cell, one glyph: the box reads YYYYs and states ten years. */
function paintDecade(host: HTMLElement, endpoint: Endpoint, whole: boolean): void {
  ["month", "day"].forEach((part) => show(endpointPart(host, endpoint, part), !whole));
  const cells = Array.from(
    host.querySelectorAll(`[data-temporal-endpoint="${endpoint}"] [data-temporal-part]`),
  ).filter((cell) => !cell.hasAttribute("hidden"));
  cells.forEach((cell, index) => {
    show(cell.querySelector("[data-temporal-prefix]"), index > 0);
  });
  show(
    host.querySelector(
      `[data-temporal-endpoint="${endpoint}"] [data-temporal-decade-suffix]`,
    ),
    whole,
  );
}

function snapYearToDecade(host: HTMLElement, endpoint: Endpoint): void {
  const yearSegment = yearSegmentFor(host, endpoint);
  if (!yearSegment) return;
  const buffer = segmentBuffer(yearSegment);
  if (buffer.length !== 4) return;
  const snapped = decadeStart(buffer);
  if (snapped && snapped !== buffer) setSegmentBuffer(yearSegment, snapped);
}

function writeNamedParts(host: HTMLElement, endpoint: Endpoint): void {
  const { values } = readSideParts(host, endpoint);
  const whole = isToggled(host, `whole_decade_${endpoint}`);
  const year = values.year ?? "";
  setNamed(host, `${endpoint}_year`, whole ? "" : year);
  setNamed(host, `${endpoint}_month`, whole ? "" : (values.month ?? ""));
  setNamed(host, `${endpoint}_day`, whole ? "" : (values.day ?? ""));
  // A half-typed year posts as typed, for the server to refuse.
  const decade = year.length === 4 ? decadeStart(year) : year;
  setNamed(host, `${endpoint}_decade`, whole ? decade : "");
}

/**
 * A part filled with a coarser part missing beside it.
 *
 * The holes the server refuses, split the way its sentences are, so neither
 * half asks for a part that is filled.
 */
type Hole =
  | "day_needs_year_and_month"
  | "day_needs_year"
  | "day_needs_month"
  | "month_needs_year"
  | "decade_needs_four_digits";

const HOLE_SENTENCES: Record<Hole, string> = {
  day_needs_year_and_month: "Day needs a year and a month",
  day_needs_year: "Day needs a year",
  day_needs_month: "Day needs a month",
  month_needs_year: "Month needs a year",
  decade_needs_four_digits: "Decade needs four digits",
};

function holeIn(values: PartValues, wholeDecade: boolean): Hole | null {
  const year = values.year ?? "";
  if (wholeDecade) return year.length === 4 ? null : "decade_needs_four_digits";
  if (values.day && !year && !values.month) return "day_needs_year_and_month";
  if (values.day && !year) return "day_needs_year";
  if (values.day && !values.month) return "day_needs_month";
  if (values.month && !year) return "month_needs_year";
  return null;
}

function endpointSentence(host: HTMLElement, endpoint: Endpoint): string {
  const { values } = readSideParts(host, endpoint);
  const wholeDecade = isToggled(host, `whole_decade_${endpoint}`);
  // A hole is named before a precision.
  const hole = holeIn(values, wholeDecade);
  if (hole) return HOLE_SENTENCES[hole];
  if (wholeDecade) return "Decade precision";
  if (values.day) return "Day precision";
  if (values.month) return "Month precision";
  if (values.year) return "Year precision";
  return "No date";
}

/** What a screen reader hears when the precision moves. */
export function precisionSentence(host: HTMLElement): string {
  const kind = currentKind(host);
  if (kind === "unknown") return "Unknown date";
  if (kind === "until") return `Until ${endpointSentence(host, "end").toLowerCase()}`;
  if (kind === "since") return `Since ${endpointSentence(host, "start").toLowerCase()}`;
  if (kind === "range") {
    const from = endpointSentence(host, "start").toLowerCase();
    const to = endpointSentence(host, "end").toLowerCase();
    return `Range, ${from} to ${to}`;
  }
  return endpointSentence(host, "start");
}

function announce(host: HTMLElement): void {
  const region = host.querySelector("[data-temporal-announcement]");
  if (!region) return;
  const sentence = precisionSentence(host);
  // Repeating it on every keystroke would drown the field out.
  if (region.textContent !== sentence) region.textContent = sentence;
}

/**
 * Mirror the buffers into the scratch value the engine compares against.
 *
 * The engine commits only when that value changes, and it writes it before
 * this endpoint's own handlers run. A buffer written outside the engine — a
 * decade snap, a restore, a server-rendered value — would otherwise leave a
 * stale value that swallows the next keystroke that lands back on it.
 */
function syncScratch(host: HTMLElement, endpoint: Endpoint): void {
  const scratch = scratchInput(host, endpoint);
  if (!scratch) return;
  scratch.value = temporalCodec.encode(readSideParts(host, endpoint).values, false);
}

export function commitEndpoint(host: HTMLElement, endpoint: Endpoint): void {
  if (isToggled(host, `whole_decade_${endpoint}`)) snapYearToDecade(host, endpoint);
  ENDPOINTS.forEach((each) => {
    syncScratch(host, each);
    writeNamedParts(host, each);
  });
  setNamed(host, "kind", currentKind(host));
  announce(host);
  paintDisclosure(host);
  host.dispatchEvent(new CustomEvent(TEMPORAL_FIELD_CHANGE_EVENT, { bubbles: true }));
}

function show(element: Element | null, visible: boolean): void {
  element?.toggleAttribute("hidden", !visible);
}

function isExpanded(host: HTMLElement): boolean {
  const disclosure = host.querySelector("[data-temporal-disclosure]");
  return disclosure?.getAttribute("aria-expanded") === "true";
}

/** Whether the collapsed field could still state this value. */
function canCollapse(host: HTMLElement): boolean {
  if (endShape(host) !== "end_none") return false;
  if (isToggled(host, "open_start")) return false;
  if (endpointHasValue(host, "end")) return false;
  return !ENDPOINTS.some((endpoint) =>
    endpointBoxes(host, endpoint).some((box) => box.checked),
  );
}

/** Which label the button shows, and whether it shows at all. */
function paintDisclosure(host: HTMLElement): void {
  const expanded = isExpanded(host);
  show(host.querySelector("[data-temporal-disclosure-row]"), !expanded || canCollapse(host));
  show(host.querySelector('[data-temporal-disclosure-label="collapsed"]'), !expanded);
  show(host.querySelector('[data-temporal-disclosure-label="expanded"]'), expanded);
}

function setExpanded(host: HTMLElement, expanded: boolean): void {
  host
    .querySelectorAll("[data-temporal-extra]")
    .forEach((extra) => show(extra, expanded));
  const disclosure = host.querySelector("[data-temporal-disclosure]");
  disclosure?.setAttribute("aria-expanded", String(expanded));
  paintDisclosure(host);
}

/** The thirteen posted inputs, which together are the whole value. */
const DRAFT_KEYS = [
  "kind",
  "start_year",
  "start_month",
  "start_day",
  "start_decade",
  "start_approximate",
  "start_uncertain",
  "end_year",
  "end_month",
  "end_day",
  "end_decade",
  "end_approximate",
  "end_uncertain",
] as const;

type DraftKey = (typeof DRAFT_KEYS)[number];

export type TemporalDraft = Record<DraftKey, string>;

/** A box states itself; every other control states its value. */
function draftValue(control: HTMLInputElement | HTMLSelectElement | null): string {
  if (!control) return "";
  if (control instanceof HTMLInputElement && control.type === "checkbox") {
    return control.checked ? "on" : "";
  }
  return control.value;
}

export function readDraft(host: HTMLElement): TemporalDraft {
  const draft = {} as TemporalDraft;
  DRAFT_KEYS.forEach((key) => {
    draft[key] = draftValue(namedInput(host, key));
  });
  return draft;
}

function draftPart(draft: TemporalDraft, endpoint: Endpoint, part: string): string {
  return draft[`${endpoint}_${part}` as DraftKey] ?? "";
}

/** Digits right-aligned in one segment's width, as the server pads them. */
function paddedDigits(text: string, width: number): string {
  const stripped = text.trim();
  return /^\d+$/.test(stripped) ? stripped.padStart(width, "0") : "";
}

/** One end takes the parts, the qualifiers and the decade a draft states. */
function adoptEndpoint(
  host: HTMLElement,
  draft: TemporalDraft,
  endpoint: Endpoint,
): void {
  const whole = draftPart(draft, endpoint, "decade") !== "";
  const parts: Record<string, string> = {
    year: whole
      ? draftPart(draft, endpoint, "decade")
      : draftPart(draft, endpoint, "year"),
    month: whole ? "" : draftPart(draft, endpoint, "month"),
    day: whole ? "" : draftPart(draft, endpoint, "day"),
  };
  segmentsForSide(host, endpoint).forEach((segment) => {
    const width = segmentSpec(segment)?.width ?? 0;
    setSegmentBuffer(segment, paddedDigits(parts[segment.dataset.datePart ?? ""] ?? "", width));
  });
  ["approximate", "uncertain"].forEach((qualifier) => {
    const box = namedInput(host, `${endpoint}_${qualifier}`);
    if (box instanceof HTMLInputElement) {
      box.checked = draftPart(draft, endpoint, qualifier) !== "";
    }
  });
  const decadeBox = toggleBox(host, `whole_decade_${endpoint}`);
  if (decadeBox) decadeBox.checked = whole;
  paintDecade(host, endpoint, whole);
}

/**
 * The state one draft implies, over whatever the field holds now.
 *
 * Both the page load and a copy from another field come through here, so
 * the order below is exercised by every render rather than by the rarer
 * path alone.
 */
export function adoptDraft(host: HTMLElement, draft: TemporalDraft): void {
  const open = draft.kind === "until";
  const openStart = toggleBox(host, "open_start");
  if (openStart) openStart.checked = open;
  setEndpointOpen(host, "start", open);

  ENDPOINTS.forEach((endpoint) => adoptEndpoint(host, draft, endpoint));

  if (draft.kind === "since") setEndShape(host, "end_open");
  else if (open || draft.kind === "range" || endpointHasValue(host, "end"))
    setEndShape(host, "end_date");
  else setEndShape(host, "end_none");
  paintEndShape(host);
  // The server disables the group, so no script posts no answer. Only an
  // open start takes the choice away again.
  endShapeBoxes(host).forEach((box) => {
    box.disabled = open;
  });

  commitEndpoint(host, "start");
  setExpanded(host, !canCollapse(host));
}

/** One field takes the whole value another states. */
export function copyTemporalDraft(source: HTMLElement, target: HTMLElement): void {
  adoptDraft(target, readDraft(source));
}

function revealSegments(host: HTMLElement): void {
  host.querySelectorAll("[data-temporal-native]").forEach((wrapper) => {
    show(wrapper, false);
  });
  ENDPOINTS.forEach((endpoint) => {
    show(host.querySelector(`[data-temporal-segments="${endpoint}"]`), true);
  });
}

function bindEngine(host: HTMLElement): void {
  bindSegmentField({
    picker: host,
    field: host.querySelector<HTMLElement>("[data-temporal-field]")!,
    resolveHidden: (side) => (isEndpoint(side) ? scratchInput(host, side) : null),
    onCommit: (side) => {
      if (isEndpoint(side)) commitEndpoint(host, side);
    },
    codec: temporalCodec,
  });
}

function paintEndShape(host: HTMLElement): void {
  // Only a date at the end needs the fields for one.
  show(host.querySelector("[data-temporal-end-group]"), endShape(host) === "end_date");
}

function syncEndShape(host: HTMLElement): void {
  if (endShape(host) !== "end_date") clearEndpoint(host, "end");
  paintEndShape(host);
  commitEndpoint(host, "end");
}

function bindDecadeBox(host: HTMLElement, endpoint: Endpoint): void {
  const box = toggleBox(host, `whole_decade_${endpoint}`);
  box?.addEventListener("change", () => {
    const whole = isToggled(host, `whole_decade_${endpoint}`);
    const yearSegment = yearSegmentFor(host, endpoint);
    if (yearSegment) {
      if (whole) rememberYear(host, endpoint, segmentBuffer(yearSegment));
      else {
        // Give back the year the snap took, never a year typed since.
        const remembered = typedYears.get(host)?.[endpoint] ?? "";
        if (segmentBuffer(yearSegment) === decadeStart(remembered)) {
          setSegmentBuffer(yearSegment, remembered);
        }
      }
    }
    paintDecade(host, endpoint, whole);
    commitEndpoint(host, endpoint);
  });
}

function bindControls(host: HTMLElement): void {
  endShapeBoxes(host).forEach((box) => {
    box.addEventListener("change", () => syncEndShape(host));
  });

  ENDPOINTS.forEach((endpoint) => bindDecadeBox(host, endpoint));

  toggleBox(host, "open_start")?.addEventListener("change", () => {
    const open = isToggled(host, "open_start");
    // An until ends on a date. It is the only end it can have.
    if (open) {
      setEndShape(host, "end_date");
      syncEndShape(host);
    }
    endShapeBoxes(host).forEach((box) => {
      box.disabled = open;
    });
    setEndpointOpen(host, "start", open);
    commitEndpoint(host, "start");
  });

  const disclosure = host.querySelector("[data-temporal-disclosure]");
  disclosure?.addEventListener("click", () => setExpanded(host, !isExpanded(host)));
  // A qualifier box owns no handler, yet it decides the button.
  host.addEventListener("change", () => paintDisclosure(host));
}

/**
 * The button that takes another field's whole value.
 *
 * The source may be on no page at all: a value a segment cannot hold
 * renders the native controls alone, with no element around them. That
 * reads as a source stating nothing, so the button stays inert and says
 * which field to correct.
 */
function initCopyControl(host: HTMLElement): void {
  const button = host.querySelector<HTMLButtonElement>("[data-temporal-copy]");
  if (!button) return;
  const sourceName = button.getAttribute("data-temporal-copy") ?? "";
  const source = document.querySelector<HTMLElement>(
    `temporal-field[field-name="${sourceName}"]`,
  );
  const paint = () => {
    button.disabled = !source || currentKind(source) === "unknown";
  };
  button.hidden = false;
  paint();
  source?.addEventListener(TEMPORAL_FIELD_CHANGE_EVENT, paint);
  button.addEventListener("click", () => {
    if (source) copyTemporalDraft(source, host);
  });
}

function initField(host: HTMLElement): void {
  revealSegments(host);
  bindEngine(host);
  bindControls(host);
  adoptDraft(host, readDraft(host));
  initCopyControl(host);
  // A field nobody has touched announces nothing.
  const region = host.querySelector("[data-temporal-announcement]");
  if (region) region.textContent = "";
}

class TemporalFieldElement extends HTMLElement {
  private initialized = false;

  connectedCallback(): void {
    if (this.initialized) return;
    this.initialized = true;
    initField(this);
  }
}

customElements.define("temporal-field", TemporalFieldElement);
