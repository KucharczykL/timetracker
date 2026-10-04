// One stack owns every floating surface's dismissal.
//
// A surface is an open panel, hint or modal. The stack holds them
// in opening order and owns the only document listeners: Escape closes
// the topmost surface, and a press outside closes every surface above
// the one pressed in. Panels render in the top layer as manual
// popovers, so no ancestor clips them and no z-index orders them.

export type SurfaceKind = "panel" | "hint" | "modal";

export interface Surface {
  host: HTMLElement;
  kind: SurfaceKind;
  close(): void;
  restoreFocus?(): void;
}

interface PendingPress {
  pointerId: number;
  path: readonly EventTarget[];
}

const surfaces: Surface[] = [];
let pendingPress: PendingPress | null = null;
let listening = false;

function dismiss(surface: Surface): void {
  surface.close();
  removeSurface(surface);
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
  top.restoreFocus?.();
  dismiss(top);
  event.preventDefault();
}

function onPointerDown(event: PointerEvent): void {
  if (!event.isPrimary || event.button !== 0 || surfaces.length === 0) {
    pendingPress = null;
    return;
  }
  // Now: a handler may detach the target.
  pendingPress = { pointerId: event.pointerId, path: event.composedPath() };
}

function onPointerUp(event: PointerEvent): void {
  const press = pendingPress;
  if (!press || press.pointerId !== event.pointerId) return;
  pendingPress = null;
  let pressedIndex = -1;
  surfaces.forEach((surface, index) => {
    if (press.path.includes(surface.host)) pressedIndex = index;
  });
  dismissAll(surfaces.slice(pressedIndex + 1).filter((surface) => surface.kind !== "modal"));
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
  if (surface.kind !== "hint") {
    dismissAll(surfaces.filter((open) => !open.host.contains(surface.host)));
  }
  surfaces.push(surface);
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
  } catch {
    return false;
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
    if (isInvalidState(error)) return false;
    throw error;
  }
  panel.hidden = false;
  return true;
}

export function hideFromTopLayer(panel: HTMLElement): void {
  try {
    panel.hidePopover();
  } catch (error) {
    // The UA may have hidden it already.
    if (!isInvalidState(error)) throw error;
  }
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
}
