// Covered modals step back; the top names them.
import { reportClientError } from "../client-errors.js";
import { MODAL_ATTRIBUTES, type ModalAttributeRole } from "../generated/modal-attributes.js";
import type { ModalState } from "./modal-layer.js";

/** Shown modals, bottom first; open or leaving. */
export interface StackedModal {
  readonly dialog: HTMLDialogElement;
  readonly state: ModalState;
}

export const STACK_PROPERTIES = [
  "--modal-depth",
  "--modal-scale",
  "--modal-scrim",
  "--modal-shift",
  "--modal-reserve",
] as const;
export type StackProperty = (typeof STACK_PROPERTIES)[number];

type Pixels = number;
/** Open modals above this one. */
type Depth = number;
type ScaleFactor = number;
type CssValue = string; // e.g. "12.5px"
type ModalName = string;
type ElementId = string;
type Refresh = () => void;

const SCALE_STEP = 0.05;
// Covered panels darken to this opacity at most.
const SCRIM_STEP = 0.15;
const SCRIM_MAX = 0.5;
const SEPARATOR = " › ";
const SPOKEN_SEPARATOR = ", ";

let refresh: Refresh | null = null;
let watching = false;
let resizeObserver: ResizeObserver | null = null;
let scheduledFrame: number | null = null;
const observed = new Set<Element>();
const unnamedReported = new WeakSet<HTMLDialogElement>();
let mintedTrails = 0;

interface Parts {
  readonly panel: HTMLElement | null;
  readonly header: HTMLElement | null;
  readonly trail: HTMLElement | null;
}

interface Layer extends Parts {
  readonly depth: Depth;
  /** Header height once stepped back. */
  readonly strip: Pixels;
}

function report(detail: string): void {
  reportClientError("modal-layer", detail, { toast: false });
}

function ownPart(dialog: HTMLDialogElement, role: ModalAttributeRole): HTMLElement | null {
  return (
    Array.from(dialog.querySelectorAll<HTMLElement>(`[${MODAL_ATTRIBUTES[role]}]`)).find(
      (element) => element.closest("dialog") === dialog,
    ) ?? null
  );
}

function partsOf(dialog: HTMLDialogElement): Parts {
  return {
    panel: ownPart(dialog, "panel"),
    header: ownPart(dialog, "header"),
    trail: ownPart(dialog, "trail"),
  };
}

function setProperty(element: HTMLElement, name: StackProperty, value: CssValue): void {
  if (element.style.getPropertyValue(name) !== value) element.style.setProperty(name, value);
}

function setAttribute(element: Element, name: string, value: string | null): void {
  if (value === null) {
    if (element.hasAttribute(name)) element.removeAttribute(name);
  } else if (element.getAttribute(name) !== value) {
    element.setAttribute(name, value);
  }
}

function pixels(value: Pixels): CssValue {
  // Unitless or NaN voids the transform.
  return `${Math.round(value * 100) / 100 || 0}px`;
}

function scale(depth: Depth): ScaleFactor {
  return 1 - SCALE_STEP * depth;
}

/** The scrim's opacity: the page stays hidden, never translucent. */
function scrim(depth: Depth): CssValue {
  return String(Math.round(Math.min(SCRIM_MAX, SCRIM_STEP * depth) * 100) / 100);
}

/** Labelledby text, else aria-label. */
function nameOf(dialog: HTMLDialogElement): ModalName {
  const labelled = (dialog.getAttribute("aria-labelledby") ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => dialog.ownerDocument.getElementById(id)?.textContent?.trim() ?? "")
    .filter(Boolean)
    .join(" ");
  const name = labelled || (dialog.getAttribute("aria-label") ?? "").trim();
  if (!name && !unnamedReported.has(dialog)) {
    unnamedReported.add(dialog);
    report(`a covered modal has no name: ${dialog.id || dialog.className}`);
  }
  return name;
}

function describedBy(dialog: HTMLDialogElement, trailId: ElementId, shown: boolean): void {
  const tokens = (dialog.getAttribute("aria-describedby") ?? "")
    .split(/\s+/)
    .filter((token) => token && token !== trailId);
  if (shown) {
    // An alertdialog must lead with its message.
    if (dialog.getAttribute("role") === "alertdialog") tokens.push(trailId);
    else tokens.unshift(trailId);
  }
  setAttribute(dialog, "aria-describedby", tokens.length ? tokens.join(" ") : null);
}

function hideTrail(dialog: HTMLDialogElement, trail: HTMLElement | null): void {
  if (!trail) return;
  if (trail.textContent !== "") trail.replaceChildren();
  if (!trail.hidden) trail.hidden = true;
  if (trail.id) describedBy(dialog, trail.id, false);
}

function showTrail(
  dialog: HTMLDialogElement,
  trail: HTMLElement,
  names: readonly ModalName[],
): void {
  if (trail.textContent !== names.join(`${SEPARATOR}${SPOKEN_SEPARATOR}`)) {
    const children: Node[] = [];
    names.forEach((name, index) => {
      if (index > 0) {
        const glyph = document.createElement("span");
        glyph.setAttribute("aria-hidden", "true");
        glyph.textContent = SEPARATOR;
        const spoken = document.createElement("span");
        spoken.className = "sr-only";
        spoken.textContent = SPOKEN_SEPARATOR;
        children.push(glyph, spoken);
      }
      children.push(document.createTextNode(name));
    });
    trail.replaceChildren(...children);
  }
  if (trail.hidden) trail.hidden = false;
  if (!trail.id) {
    mintedTrails += 1;
    trail.id = `modal-trail-${mintedTrails}`;
  }
  describedBy(dialog, trail.id, true);
}

/** One refresh per frame; never inside the observer. */
function scheduleRefresh(): void {
  if (scheduledFrame !== null || !refresh) return;
  const run = refresh;
  scheduledFrame = window.requestAnimationFrame(() => {
    scheduledFrame = null;
    run();
  });
}

function observe(element: HTMLElement | null): void {
  if (!element || !resizeObserver || observed.has(element)) return;
  observed.add(element);
  resizeObserver.observe(element);
}

function watch(): void {
  if (watching) return;
  window.addEventListener("resize", scheduleRefresh);
  if (typeof ResizeObserver !== "undefined") resizeObserver = new ResizeObserver(scheduleRefresh);
  watching = true;
}

/** The layer's re-measure, run on resize. */
export function onStackResize(callback: Refresh): void {
  refresh = callback;
}

function layersOf(open: readonly StackedModal[]): Layer[] {
  return open.map((entry, index) => {
    const parts = partsOf(entry.dialog);
    observe(parts.panel);
    observe(parts.header);
    const depth = open.length - 1 - index;
    return { ...parts, depth, strip: scale(depth) * (parts.header?.offsetHeight ?? 0) };
  });
}

/** A leaving modal keeps what it shows. */
function markTrails(open: readonly StackedModal[]): void {
  const top = open.at(-1);
  for (const entry of open) {
    const { trail } = partsOf(entry.dialog);
    if (entry !== top || !trail) {
      hideTrail(entry.dialog, trail);
      continue;
    }
    const names = open.slice(0, -1).map((below) => nameOf(below.dialog)).filter(Boolean);
    if (names.length > 0) showTrail(entry.dialog, trail, names);
    else hideTrail(entry.dialog, trail);
  }
}

/** Steps, measures and names every shown modal. */
export function markStack(shown: readonly StackedModal[]): void {
  if (shown.length === 0) return;
  watch();
  const open = shown.filter((entry) => entry.state === "open");
  markTrails(open);
  const layers = layersOf(open);
  let reserve: Pixels = 0;
  for (const layer of layers) {
    if (layer.panel) {
      setProperty(layer.panel, "--modal-reserve", pixels(reserve));
      setProperty(layer.panel, "--modal-depth", String(layer.depth));
      setProperty(layer.panel, "--modal-scale", String(scale(layer.depth)));
      setProperty(layer.panel, "--modal-scrim", scrim(layer.depth));
      setAttribute(layer.panel, MODAL_ATTRIBUTES.depth, layer.depth ? String(layer.depth) : null);
    }
    reserve += layer.strip;
  }
  // Read after every reserve is written.
  const tops: Pixels[] = layers.map((layer) => layer.panel?.offsetTop ?? 0);
  let above: Pixels | null = null;
  for (let index = layers.length - 1; index >= 0; index -= 1) {
    const { panel, strip } = layers[index];
    if (!panel) continue;
    const shift: Pixels = above === null ? 0 : Math.min(0, above - strip - tops[index]);
    setProperty(panel, "--modal-shift", pixels(shift));
    above = tops[index] + shift;
  }
}

/** Takes every mark off one modal. */
export function clearStack(dialog: HTMLDialogElement): void {
  const { panel, header, trail } = partsOf(dialog);
  hideTrail(dialog, trail);
  for (const element of [panel, header]) {
    if (element && observed.delete(element)) resizeObserver?.unobserve(element);
  }
  if (!panel) return;
  panel.removeAttribute(MODAL_ATTRIBUTES.depth);
  for (const name of STACK_PROPERTIES) panel.style.removeProperty(name);
}

export function stopWatchingStack(): void {
  window.removeEventListener("resize", scheduleRefresh);
  if (scheduledFrame !== null) window.cancelAnimationFrame(scheduledFrame);
  scheduledFrame = null;
  resizeObserver?.disconnect();
  resizeObserver = null;
  observed.clear();
  watching = false;
}
