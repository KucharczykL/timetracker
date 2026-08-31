/**
 * TemporalField — the browser half of a date at any precision.
 *
 * The server renders every control (common/components/temporal_field.py):
 * a shape select, four number inputs and two checkboxes per endpoint, and
 * — hidden — a segmented date, five nameless toggles and a live region.
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
/** The toggle that opens an end, and the end it empties. */
const OPEN_TOGGLES: Record<string, string> = {
  open_start: "start",
  open_end: "end",
};

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

/** Close whichever end is open, leaving its controls usable again. */
function closeOpenEnds(host: HTMLElement): void {
  Object.entries(OPEN_TOGGLES).forEach(([openToggle, endpoint]) => {
    const box = toggleBox(host, openToggle);
    if (!box?.checked) return;
    box.checked = false;
    setEndpointOpen(host, endpoint, false);
  });
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
  if (isToggled(host, "open_end")) return "since";
  if (isToggled(host, "add_end")) return "range";
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
}

function show(element: Element | null, visible: boolean): void {
  element?.toggleAttribute("hidden", !visible);
}

function setExpanded(host: HTMLElement, expanded: boolean): void {
  host
    .querySelectorAll("[data-temporal-extra]")
    .forEach((extra) => show(extra, expanded));
  const disclosure = host.querySelector("[data-temporal-disclosure]");
  disclosure?.setAttribute("aria-expanded", String(expanded));
  show(host.querySelector("[data-temporal-disclosure-row]"), !expanded);
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

  function syncEndGroup(): void {
    const wanted = isToggled(host, "add_end");
    show(host.querySelector("[data-temporal-end-group]"), wanted);
    // Since and until both need an end. No end closes them.
    if (!wanted) {
      closeOpenEnds(host);
      clearEndpoint(host, "end");
    }
    commitEndpoint(host, "end");
  }

  const addEnd = toggleBox(host, "add_end");
  addEnd?.addEventListener("change", syncEndGroup);
  // A stored end is the only thing that asks for one at load.
  if (addEnd) addEnd.checked = endpointHasValue(host, "end");
  show(host.querySelector("[data-temporal-end-group]"), isToggled(host, "add_end"));

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

  Object.entries(OPEN_TOGGLES).forEach(([openToggle, endpoint]) => {
    toggleBox(host, openToggle)?.addEventListener("change", () => {
      const open = isToggled(host, openToggle);
      if (open) {
        // An open end needs the other end to say something.
        const other = openToggle === "open_start" ? "open_end" : "open_start";
        const otherBox = toggleBox(host, other);
        if (otherBox?.checked) {
          otherBox.checked = false;
          setEndpointOpen(host, OPEN_TOGGLES[other], false);
        }
        const wantsEnd = toggleBox(host, "add_end");
        if (wantsEnd && !wantsEnd.checked) {
          wantsEnd.checked = true;
          wantsEnd.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
      setEndpointOpen(host, endpoint, open);
      commitEndpoint(host, endpoint);
    });
  });

  const disclosure = host.querySelector("[data-temporal-disclosure]");
  disclosure?.addEventListener("click", () => setExpanded(host, true));

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
