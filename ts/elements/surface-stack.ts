// One stack owns every floating surface's dismissal.
//
// A surface is an open panel, hint or modal. The stack holds them
// in opening order and owns the only dismissal listeners, on window:
// Escape closes the topmost surface, and a press outside closes every
// surface above the one pressed in. A modal is exempt from both and from
// single open: the modal layer closes it. Panels render in the top layer
// as manual popovers, so no ancestor clips them and no z-index orders them.
import { reportClientError } from "../client-errors.js";
import { holdLeave, type CancelLeave } from "../motion.js";

interface SurfaceBase {
  /** Contains the panel and its toggle. */
  readonly host: HTMLElement;
  /** Idempotent; removes itself when self-closing. */
  close(): void;
}

/** A menu, listbox or popup. */
export interface PanelSurface extends SurfaceBase {
  readonly kind: "panel";
  /** On Escape, before the close. */
  restoreFocus?(): void;
}

/** A tooltip; Escape closes it first. */
export interface HintSurface extends SurfaceBase {
  readonly kind: "hint";
}

/** A modal: Escape stays native cancel. */
export interface ModalSurface extends SurfaceBase {
  readonly kind: "modal";
}

export type Surface = PanelSurface | HintSurface | ModalSurface;
export type SurfaceKind = Surface["kind"];

interface PendingPress {
  pointerId: number;
  path: readonly EventTarget[];
}

const surfaces: Surface[] = [];
let pendingPress: PendingPress | null = null;
let listening = false;

function dismiss(surface: Surface): void {
  // A throwing close still leaves.
  try {
    surface.close();
  } finally {
    removeSurface(surface);
  }
}

function dismissAll(candidates: readonly Surface[]): void {
  for (const surface of [...candidates].reverse()) {
    if (!surfaces.includes(surface)) continue;
    // One broken close spares the rest.
    try {
      dismiss(surface);
    } catch (error) {
      reportClientError("surface-stack", `close threw: ${String(error)}`, { toast: false });
    }
  }
}

/** Closes what sits above the pressed surface. */
function dismissOutside(path: readonly EventTarget[]): void {
  const pressed = (surface: Surface): boolean => path.includes(surface.host);
  // A hint shields nothing beneath it.
  let pressedIndex = -1;
  surfaces.forEach((surface, index) => {
    if (surface.kind !== "hint" && pressed(surface)) pressedIndex = index;
  });
  dismissAll(
    surfaces
      .slice(pressedIndex + 1)
      .filter((surface) => surface.kind !== "modal" && !pressed(surface)),
  );
}

function onKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape" || event.isComposing || event.repeat) return;
  const top = surfaces.at(-1);
  // A modal keeps its native cancel.
  if (!top || top.kind === "modal") return;
  // Focus moves home before the panel hides.
  if (top.kind === "panel") top.restoreFocus?.();
  dismiss(top);
  event.preventDefault();
}

function onPointerDown(event: PointerEvent): void {
  if (!event.isPrimary || event.button !== 0 || surfaces.length === 0) {
    pendingPress = null;
    return;
  }
  // Captured now: handlers may detach the target.
  pendingPress = { pointerId: event.pointerId, path: event.composedPath() };
}

function onPointerUp(event: PointerEvent): void {
  const press = pendingPress;
  if (!press || press.pointerId !== event.pointerId) return;
  pendingPress = null;
  dismissOutside(press.path);
}

function onClick(event: MouseEvent): void {
  // Keyboard clicks bring no pointer press.
  if (event.detail !== 0 || surfaces.length === 0) return;
  dismissOutside(event.composedPath());
}

function onPointerCancel(event: PointerEvent): void {
  if (pendingPress?.pointerId === event.pointerId) pendingPress = null;
}

function listen(): void {
  if (listening) return;
  listening = true;
  window.addEventListener("keydown", onKeyDown, true);
  window.addEventListener("pointerdown", onPointerDown, true);
  window.addEventListener("pointerup", onPointerUp, true);
  window.addEventListener("pointercancel", onPointerCancel, true);
  window.addEventListener("click", onClick, true);
}

export function pushSurface(surface: Surface): void {
  if (surfaces.includes(surface)) return;
  listen();
  try {
    // Single open spares modals; they nest.
    if (surface.kind !== "hint") {
      dismissAll(
        surfaces.filter(
          (open) => open.kind !== "modal" && !open.host.contains(surface.host),
        ),
      );
    }
  } finally {
    surfaces.push(surface);
  }
}

/** Idempotent; closes surfaces nested inside first. */
export function removeSurface(surface: Surface): void {
  const index = surfaces.indexOf(surface);
  if (index === -1) return;
  dismissAll(
    surfaces
      .slice(index + 1)
      .filter((open) => open.host !== surface.host && surface.host.contains(open.host)),
  );
  const current = surfaces.indexOf(surface);
  if (current !== -1) surfaces.splice(current, 1);
}

function isShowing(panel: HTMLElement): boolean {
  return panel.matches(":popover-open");
}

const pendingLeaves = new WeakMap<Element, CancelLeave>();

function cancelPendingLeave(panel: Element): void {
  pendingLeaves.get(panel)?.();
  pendingLeaves.delete(panel);
}

export function isInvalidState(error: unknown): boolean {
  return error instanceof DOMException && error.name === "InvalidStateError";
}

/** False if detached (quietly) or refused (reported). */
export function showInTopLayer(panel: HTMLElement): boolean {
  if (!panel.isConnected) return false;
  if (typeof panel.showPopover !== "function") {
    reportClientError("surface-stack", "this browser has no Popover API");
    return false;
  }
  try {
    if (!isShowing(panel)) panel.showPopover();
  } catch (error) {
    if (!isInvalidState(error)) throw error;
    reportClientError("surface-stack", `showPopover refused: ${String(error)}`, {
      toast: false,
    });
    return false;
  }
  // A re-entrant show returns without showing.
  if (!isShowing(panel)) {
    reportClientError("surface-stack", "showPopover left the panel hidden", {
      toast: false,
    });
    return false;
  }
  cancelPendingLeave(panel);
  panel.hidden = false;
  panel.setAttribute("data-motion", "entering");
  return true;
}

/** The hide waits out the exit animation, then runs onHidden once. */
export function hideFromTopLayer(panel: HTMLElement, onHidden?: () => void): void {
  cancelPendingLeave(panel);
  const finish = (): void => {
    pendingLeaves.delete(panel);
    try {
      panel.hidePopover();
    } catch (error) {
      // Nothing to hide, or the UA refused.
      if (!isInvalidState(error)) throw error;
    }
    panel.hidden = true;
    onHidden?.();
  };
  // Already hidden: nothing to animate out.
  if (panel.hidden && !isShowing(panel)) {
    finish();
    return;
  }
  let finished = false;
  const cancel = holdLeave(panel, "fast-exit", () => {
    finished = true;
    finish();
  });
  if (!finished) pendingLeaves.set(panel, cancel);
}

/** Out of the top layer, shown in flow. */
export function releaseFromTopLayer(panel: HTMLElement): void {
  cancelPendingLeave(panel);
  if (panel.hasAttribute("popover") && isShowing(panel)) {
    try {
      panel.hidePopover();
    } catch (error) {
      if (!isInvalidState(error)) throw error;
      reportClientError("surface-stack", `hidePopover refused: ${String(error)}`, {
        toast: false,
      });
    }
  }
  panel.removeAttribute("popover");
  panel.hidden = false;
}

/** Back to a closed manual popover. */
export function returnToTopLayer(panel: HTMLElement): void {
  panel.setAttribute("popover", "manual");
  panel.hidden = true;
}

export function openSurfaces(): readonly Surface[] {
  return [...surfaces];
}

export function resetSurfacesForTests(): void {
  surfaces.length = 0;
  pendingPress = null;
  if (!listening) return;
  listening = false;
  window.removeEventListener("keydown", onKeyDown, true);
  window.removeEventListener("pointerdown", onPointerDown, true);
  window.removeEventListener("pointerup", onPointerUp, true);
  window.removeEventListener("pointercancel", onPointerCancel, true);
  window.removeEventListener("click", onClick, true);
}
