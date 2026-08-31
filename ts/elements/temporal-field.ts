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
  segmentsForSide,
  setSegmentBuffer,
} from "./date-field-core.js";
import { coarsestPrefix, decadeStart, temporalCodec } from "./temporal-codec.js";

const ENDPOINTS = ["start", "end"] as const;
/** How a value ends, as the one radio group states it. */
const END_SHAPES = ["end_none", "end_date", "end_open"] as const;

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
  endpoint: string,
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
function endpointBoxes(host: HTMLElement, endpoint: string): HTMLInputElement[] {
  return [
    namedInput(host, `${endpoint}_approximate`),
    namedInput(host, `${endpoint}_uncertain`),
    toggleBox(host, `whole_decade_${endpoint}`),
  ].filter((box) => box instanceof HTMLInputElement);
}

/** Empty one end, so a shape that never reads it posts nothing. */
function clearEndpoint(host: HTMLElement, endpoint: string): void {
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
function setEndpointOpen(host: HTMLElement, endpoint: string, open: boolean): void {
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
function endShape(host: HTMLElement): string {
  return END_SHAPES.find((shape) => isToggled(host, shape)) ?? "end_none";
}

function setEndShape(host: HTMLElement, shape: string): void {
  const box = toggleBox(host, shape);
  if (box) box.checked = true;
}

/** Clear a part no coarser part can carry. */
function enforceGrowth(host: HTMLElement, endpoint: string): void {
  const { values } = readSideParts(host, endpoint);
  const stale = !values.year ? ["month", "day"] : !values.month ? ["day"] : [];
  segmentsForSide(host, endpoint).forEach((segment) => {
    const part = segment.dataset.datePart ?? "";
    if (stale.includes(part) && segmentBuffer(segment)) setSegmentBuffer(segment, "");
  });
}

function endpointHasValue(host: HTMLElement, endpoint: string): boolean {
  return coarsestPrefix(readSideParts(host, endpoint).values) !== "";
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

function rememberYear(host: HTMLElement, endpoint: string, year: string): void {
  const remembered = typedYears.get(host) ?? {};
  remembered[endpoint] = year;
  typedYears.set(host, remembered);
}

function yearSegmentFor(
  host: HTMLElement,
  endpoint: string,
): HTMLInputElement | undefined {
  return segmentsForSide(host, endpoint).find(
    (segment) => segment.dataset.datePart === "year",
  );
}

function endpointPart(
  host: HTMLElement,
  endpoint: string,
  part: string,
): Element | null {
  return host.querySelector(
    `[data-temporal-endpoint="${endpoint}"] [data-temporal-part="${part}"]`,
  );
}

/** One cell, one glyph: the box reads YYYYs and states ten years. */
function paintDecade(host: HTMLElement, endpoint: string, whole: boolean): void {
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

function snapYearToDecade(host: HTMLElement, endpoint: string): void {
  const yearSegment = yearSegmentFor(host, endpoint);
  if (!yearSegment) return;
  const buffer = segmentBuffer(yearSegment);
  if (buffer.length !== 4) return;
  const snapped = decadeStart(buffer);
  if (snapped && snapped !== buffer) setSegmentBuffer(yearSegment, snapped);
}

function writeNamedParts(host: HTMLElement, endpoint: string): void {
  const { values } = readSideParts(host, endpoint);
  const whole = isToggled(host, `whole_decade_${endpoint}`);
  const year = values.year ?? "";
  setNamed(host, `${endpoint}_year`, whole ? "" : year);
  setNamed(host, `${endpoint}_month`, whole ? "" : (values.month ?? ""));
  setNamed(host, `${endpoint}_day`, whole ? "" : (values.day ?? ""));
  // A half-typed year states no decade; 19 is not the 10s.
  setNamed(host, `${endpoint}_decade`, whole && year.length === 4 ? decadeStart(year) : "");
}

function endpointSentence(host: HTMLElement, endpoint: string): string {
  if (isToggled(host, `whole_decade_${endpoint}`)) return "Decade precision";
  const { values } = readSideParts(host, endpoint);
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

export function commitEndpoint(host: HTMLElement, endpoint: string): void {
  if (isToggled(host, `whole_decade_${endpoint}`)) snapYearToDecade(host, endpoint);
  enforceGrowth(host, endpoint);
  ENDPOINTS.forEach((each) => writeNamedParts(host, each));
  setNamed(host, "kind", currentKind(host));
  announce(host);
  paintDisclosure(host);
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

function initField(host: HTMLElement): void {
  host.querySelectorAll("[data-temporal-native]").forEach((wrapper) => {
    show(wrapper, false);
  });
  ENDPOINTS.forEach((endpoint) => {
    show(host.querySelector(`[data-temporal-segments="${endpoint}"]`), true);
  });

  bindSegmentField({
    picker: host,
    field: host.querySelector<HTMLElement>("[data-temporal-field]")!,
    resolveHidden: (endpoint) => scratchInput(host, endpoint),
    onCommit: (endpoint) => commitEndpoint(host, endpoint),
    codec: temporalCodec,
  });

  // The codec ignores a part the value cannot state, so that keystroke
  // changes no scratch value and onCommit stays silent. This clears it.
  host.addEventListener("keyup", (event) => {
    const segment = (event.target as HTMLElement | null)?.closest<HTMLInputElement>(
      "input[data-date-part]",
    );
    if (segment) commitEndpoint(host, segment.dataset.dateSide ?? "start");
  });

  function paintEndShape(): void {
    // Only a date at the end needs the fields for one.
    show(host.querySelector("[data-temporal-end-group]"), endShape(host) === "end_date");
  }

  function syncEndShape(): void {
    if (endShape(host) !== "end_date") clearEndpoint(host, "end");
    paintEndShape();
    commitEndpoint(host, "end");
  }

  // The server disables them, so no script posts no answer.
  endShapeBoxes(host).forEach((box) => {
    box.disabled = false;
    box.addEventListener("change", syncEndShape);
  });

  ENDPOINTS.forEach((endpoint) => {
    const box = toggleBox(host, `whole_decade_${endpoint}`);
    box?.addEventListener("change", () => {
      const whole = isToggled(host, `whole_decade_${endpoint}`);
      const yearSegment = yearSegmentFor(host, endpoint);
      if (yearSegment) {
        if (whole) rememberYear(host, endpoint, segmentBuffer(yearSegment));
        else setSegmentBuffer(yearSegment, typedYears.get(host)?.[endpoint] ?? "");
      }
      paintDecade(host, endpoint, whole);
      commitEndpoint(host, endpoint);
    });
    paintDecade(host, endpoint, isToggled(host, `whole_decade_${endpoint}`));
  });

  const openStart = toggleBox(host, "open_start");
  openStart?.addEventListener("change", () => {
    const open = isToggled(host, "open_start");
    // An until ends on a date. It is the only end it can have.
    if (open) {
      setEndShape(host, "end_date");
      syncEndShape();
    }
    endShapeBoxes(host).forEach((box) => {
      box.disabled = open;
    });
    setEndpointOpen(host, "start", open);
    commitEndpoint(host, "start");
  });

  // The stored shape, before a keystroke derives a new one.
  const storedKind = namedInput(host, "kind")?.value ?? "";
  if (storedKind === "since") setEndShape(host, "end_open");
  else if (storedKind === "until" || endpointHasValue(host, "end"))
    setEndShape(host, "end_date");
  else setEndShape(host, "end_none");
  if (storedKind === "until" && openStart) {
    openStart.checked = true;
    endShapeBoxes(host).forEach((box) => {
      box.disabled = true;
    });
    setEndpointOpen(host, "start", true);
  }
  paintEndShape();

  const disclosure = host.querySelector("[data-temporal-disclosure]");
  disclosure?.addEventListener("click", () => setExpanded(host, !isExpanded(host)));
  // A qualifier box owns no handler, yet it decides the button.
  host.addEventListener("change", () => paintDisclosure(host));

  setExpanded(host, host.getAttribute("expanded") === "true");
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
