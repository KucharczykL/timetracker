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
import { coarsestPrefix, temporalCodec } from "./temporal-codec.js";

const ENDPOINTS = ["start", "end"] as const;

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
  return start ? "date" : "unknown";
}

function writeNamedParts(host: HTMLElement, endpoint: string): void {
  const { values } = readSideParts(host, endpoint);
  setNamed(host, `${endpoint}_year`, values.year ?? "");
  setNamed(host, `${endpoint}_month`, values.month ?? "");
  setNamed(host, `${endpoint}_day`, values.day ?? "");
}

export function commitEndpoint(host: HTMLElement, endpoint: string): void {
  enforceGrowth(host, endpoint);
  ENDPOINTS.forEach((each) => writeNamedParts(host, each));
  setNamed(host, "kind", currentKind(host));
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

  const disclosure = host.querySelector("[data-temporal-disclosure]");
  disclosure?.addEventListener("click", () => setExpanded(host, true));

  setExpanded(host, host.getAttribute("expanded") === "true");
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
