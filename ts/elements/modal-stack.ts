// Covered modals step back; the top names them.
import { MODAL_ATTRIBUTES } from "../generated/modal-attributes.js";
import type { ModalState } from "./modal-layer.js";

export interface StackedModal {
  readonly dialog: HTMLDialogElement;
  readonly state: ModalState;
}

type StackProperty = "--modal-depth" | "--modal-shift" | "--modal-reserve";
type Pixels = number;

const STACK_PROPERTIES: readonly StackProperty[] = [
  "--modal-depth",
  "--modal-shift",
  "--modal-reserve",
];
const SCALE_STEP = 0.05;
const SEPARATOR = " › ";
const SPOKEN_SEPARATOR = ", ";

let resizeObserver: ResizeObserver | null = null;
let resizeListener: (() => void) | null = null;
const observed = new Set<Element>();
let mintedTrails = 0;

interface Parts {
  readonly panel: HTMLElement | null;
  readonly header: HTMLElement | null;
  readonly trail: HTMLElement | null;
}

function ownPart(dialog: HTMLDialogElement, attribute: string): HTMLElement | null {
  return (
    Array.from(dialog.querySelectorAll<HTMLElement>(`[${attribute}]`)).find(
      (element) => element.closest("dialog") === dialog,
    ) ?? null
  );
}

function partsOf(dialog: HTMLDialogElement): Parts {
  return {
    panel: ownPart(dialog, MODAL_ATTRIBUTES.panel),
    header: ownPart(dialog, MODAL_ATTRIBUTES.header),
    trail: ownPart(dialog, MODAL_ATTRIBUTES.trail),
  };
}

function setProperty(element: HTMLElement, name: StackProperty, value: string): void {
  if (element.style.getPropertyValue(name) !== value) element.style.setProperty(name, value);
}

function setAttribute(element: Element, name: string, value: string | null): void {
  if (value === null) {
    if (element.hasAttribute(name)) element.removeAttribute(name);
  } else if (element.getAttribute(name) !== value) {
    element.setAttribute(name, value);
  }
}

function pixels(value: Pixels): string {
  // Unitless voids the whole transform.
  return `${Math.round(value * 100) / 100 || 0}px`;
}

function scale(depth: number): number {
  return 1 - SCALE_STEP * depth;
}

/** Labelledby text, else aria-label. */
function nameOf(dialog: HTMLDialogElement): string {
  const labelled = (dialog.getAttribute("aria-labelledby") ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((id) => dialog.ownerDocument.getElementById(id)?.textContent?.trim() ?? "")
    .filter(Boolean)
    .join(" ");
  return labelled || (dialog.getAttribute("aria-label") ?? "").trim();
}

function describedBy(dialog: HTMLDialogElement, trailId: string, shown: boolean): void {
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

function showTrail(dialog: HTMLDialogElement, trail: HTMLElement, names: string[]): void {
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

function observe(element: HTMLElement | null): void {
  if (!element || !resizeObserver || observed.has(element)) return;
  observed.add(element);
  resizeObserver.observe(element);
}

function watch(refresh: () => void): void {
  if (resizeListener) return;
  resizeListener = refresh;
  window.addEventListener("resize", refresh);
  if (typeof ResizeObserver !== "undefined") resizeObserver = new ResizeObserver(refresh);
}

/** Steps, measures and names every shown modal. */
export function markStack(shown: readonly StackedModal[], refresh: () => void): void {
  if (shown.length === 0) return;
  watch(refresh);
  const open = shown.filter((entry) => entry.state === "open");
  const top = open.at(-1);
  for (const entry of shown) {
    // A leaving modal keeps what it shows.
    if (entry.state !== "open") continue;
    const { trail } = partsOf(entry.dialog);
    const names = open.slice(0, -1).map((below) => nameOf(below.dialog)).filter(Boolean);
    if (entry === top && trail && names.length > 0) showTrail(entry.dialog, trail, names);
    else hideTrail(entry.dialog, trail);
  }

  const layers = open.map((entry, index) => {
    const parts = partsOf(entry.dialog);
    observe(parts.panel);
    observe(parts.header);
    const depth = open.length - 1 - index;
    return { ...parts, depth, strip: scale(depth) * (parts.header?.offsetHeight ?? 0) };
  });
  let reserve: Pixels = 0;
  for (const layer of layers) {
    if (layer.panel) {
      setProperty(layer.panel, "--modal-reserve", pixels(reserve));
      setProperty(layer.panel, "--modal-depth", String(layer.depth));
      setAttribute(layer.panel, MODAL_ATTRIBUTES.depth, layer.depth ? String(layer.depth) : null);
    }
    reserve += layer.strip;
  }
  // Read after every reserve is written.
  const tops = layers.map((layer) => layer.panel?.offsetTop ?? 0);
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
  if (resizeListener) window.removeEventListener("resize", resizeListener);
  resizeListener = null;
  resizeObserver?.disconnect();
  resizeObserver = null;
  observed.clear();
}
