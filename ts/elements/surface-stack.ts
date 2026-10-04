// One stack owns every floating surface's dismissal.
//
// A surface is an open panel, hint or modal. The stack holds them
// in opening order and owns the only document listeners: Escape closes
// the topmost surface, and a press outside closes every surface above
// the one pressed in. Panels render in the top layer as manual
// popovers, so no ancestor clips them and no z-index orders them.
import { reportClientError } from "../client-errors.js";

interface SurfaceBase {
  /** Holds the panel and its toggle; a press inside is inside. */
  readonly host: HTMLElement;
  /** Safe twice; removes itself when it closes on its own. */
  close(): void;
}

/** An anchored panel: a menu, listbox or popup. */
export interface PanelSurface extends SurfaceBase {
  readonly kind: "panel";
  /** On Escape, before the close. */
  restoreFocus?(): void;
}

/** A tooltip: it never closes another surface. */
export interface HintSurface extends SurfaceBase {
  readonly kind: "hint";
}

/** A modal dialog: Escape stays its native cancel. */
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
  // A throwing close must not jam the stack.
  try {
    surface.close();
  } finally {
    removeSurface(surface);
  }
}

function dismissAll(candidates: readonly Surface[]): void {
  for (const surface of [...candidates].reverse()) {
    if (surfaces.includes(surface)) dismiss(surface);
  }
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
  const pressed = (surface: Surface): boolean => press.path.includes(surface.host);
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
}

export function pushSurface(surface: Surface): void {
  if (surfaces.includes(surface)) return;
  listen();
  try {
    if (surface.kind !== "hint") {
      dismissAll(surfaces.filter((open) => !open.host.contains(surface.host)));
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
  try {
    return panel.matches(":popover-open");
  } catch (error) {
    // jsdom does not parse the selector.
    if (error instanceof DOMException && error.name === "SyntaxError") return false;
    throw error;
  }
}

function isInvalidState(error: unknown): boolean {
  return error instanceof DOMException && error.name === "InvalidStateError";
}

/** False if not shown. */
export function showInTopLayer(panel: HTMLElement): boolean {
  if (!panel.isConnected) return false;
  try {
    if (!isShowing(panel)) panel.showPopover();
  } catch (error) {
    if (!isInvalidState(error)) throw error;
    reportClientError("surface-stack", `showPopover refused: ${String(error)}`, {
      toast: false,
    });
    return false;
  }
  panel.hidden = false;
  return true;
}

export function hideFromTopLayer(panel: HTMLElement): void {
  try {
    panel.hidePopover();
  } catch (error) {
    // Detached: the UA hid it already.
    if (!isInvalidState(error)) throw error;
  }
  panel.hidden = true;
}

export function openSurfacesForTests(): readonly Surface[] {
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
}
