// One layer owns every modal dialog.
import { reportClientError } from "../client-errors.js";
import { MODAL_ATTRIBUTES } from "../generated/modal-attributes.js";
import { ownChild } from "./own-child.js";
import {
  isInvalidState,
  pushSurface,
  removeSurface,
  type ModalSurface,
} from "./surface-stack.js";

export const MODAL_CHANGE = "modal-layer:change" as const;

declare global {
  interface WindowEventMap {
    [MODAL_CHANGE]: Event;
  }
}

/** Idempotent; the leave must call it. */
export type FinishLeave = () => void;

export interface ModalOptions {
  /** The surface host; defaults to the dialog. */
  host?: HTMLElement;
  initialFocus?: () => HTMLElement | null;
  /** Must call finish, now or later. */
  leave?: (finish: FinishLeave) => void;
  /** Escape, backdrop, dismiss control; default close.
   *
   * Best effort: the browser may close anyway.
   * onClosed is the one hook that always runs.
   */
  dismiss?: () => void;
  /** Runs last, after focus return. */
  onClosed?: () => void;
}

export type ModalState = "closed" | "open" | "leaving";

export interface Modal {
  /** False when refused; true when open. */
  open(opener?: HTMLElement): boolean;
  close(): void;
  /** False while leaving. */
  isOpen(): boolean;
  state(): ModalState;
  focusInitial(): void;
}

/** Bumped on every open and finish. */
type Generation = number;
type PointerId = number;
type TimerHandle = number;

interface Entry {
  readonly dialog: HTMLDialogElement;
  readonly options: ModalOptions;
  readonly surface: ModalSurface;
  state: ModalState;
  opener: HTMLElement | null;
  generation: Generation;
  /** The layer's cap on a leave. */
  leaveLimit: TimerHandle | null;
  focusInitial(): void;
}

// A leave past this is a defect.
const LEAVE_LIMIT_MS = 1_000;

const LOCKED_HTML_STYLES = ["overflow", "overscrollBehavior", "scrollBehavior"] as const;
const LOCKED_BODY_STYLES = [
  "position",
  "top",
  "right",
  "bottom",
  "left",
  "width",
  "overflow",
  "paddingRight",
] as const;
type LockedStyle =
  | (typeof LOCKED_HTML_STYLES)[number]
  | (typeof LOCKED_BODY_STYLES)[number];
type StyleValues<Names extends readonly LockedStyle[]> = Readonly<
  Record<Names[number], string>
>;

interface ScrollLockSnapshot {
  readonly scrollLeft: number;
  readonly scrollTop: number;
  readonly html: StyleValues<typeof LOCKED_HTML_STYLES>;
  readonly body: StyleValues<typeof LOCKED_BODY_STYLES>;
}

const attached = new WeakSet<HTMLDialogElement>();
/** Open and leaving modals, in opening order. */
const shown: Entry[] = [];
let scrollLock: ScrollLockSnapshot | null = null;
let lastTop: HTMLDialogElement | null = null;
let removalObserver: MutationObserver | null = null;

function openEntries(): Entry[] {
  return shown.filter((entry) => entry.state === "open");
}

/** Open dialogs, in opening order. */
export function openModals(): readonly HTMLDialogElement[] {
  return openEntries().map((entry) => entry.dialog);
}

export function topModal(): HTMLDialogElement | null {
  return openEntries().at(-1)?.dialog ?? null;
}

export function isModalOpen(): boolean {
  return topModal() !== null;
}

function nearestDialog(target: EventTarget | null): HTMLDialogElement | null {
  return target instanceof Element ? target.closest("dialog") : null;
}

function report(detail: string): void {
  reportClientError("modal-layer", detail, { toast: false });
}

function notifyChange(): void {
  const top = topModal();
  if (top === lastTop) return;
  lastTop = top;
  window.dispatchEvent(new Event(MODAL_CHANGE));
}

function markBackdrops(): void {
  shown.forEach((entry, index) => {
    // Only the topmost shown dialog dims.
    entry.dialog.toggleAttribute(MODAL_ATTRIBUTES.covered, index !== shown.length - 1);
    entry.dialog.toggleAttribute(MODAL_ATTRIBUTES.over, index > 0);
  });
}

function captureStyles<Names extends readonly LockedStyle[]>(
  element: HTMLElement,
  names: Names,
): StyleValues<Names> {
  return Object.fromEntries(
    names.map((name) => [name, element.style[name]]),
  ) as StyleValues<Names>;
}

function restoreStyles<Names extends readonly LockedStyle[]>(
  element: HTMLElement,
  names: Names,
  values: StyleValues<Names>,
): void {
  for (const name of names) element.style[name] = values[name as Names[number]];
}

function lockDocumentScroll(): void {
  if (scrollLock) return;
  const html = document.documentElement;
  const body = document.body;
  const scrollLeft = window.scrollX;
  const scrollTop = window.scrollY;
  scrollLock = {
    scrollLeft,
    scrollTop,
    html: captureStyles(html, LOCKED_HTML_STYLES),
    body: captureStyles(body, LOCKED_BODY_STYLES),
  };
  const scrollbarWidth = Math.max(0, window.innerWidth - html.clientWidth);
  const bodyPadding = Number.parseFloat(getComputedStyle(body).paddingRight) || 0;
  html.style.overflow = "hidden";
  html.style.overscrollBehavior = "none";
  // iOS scrolls under overflow: hidden alone.
  body.style.position = "fixed";
  body.style.top = `-${scrollTop}px`;
  body.style.right = "0";
  body.style.bottom = "auto";
  body.style.left = `-${scrollLeft}px`;
  body.style.width = "100%";
  body.style.overflow = "hidden";
  if (scrollbarWidth > 0) {
    body.style.paddingRight = `${bodyPadding + scrollbarWidth}px`;
  }
}

function unlockDocumentScroll(): void {
  const snapshot = scrollLock;
  if (!snapshot) return;
  scrollLock = null;
  const html = document.documentElement;
  restoreStyles(html, LOCKED_HTML_STYLES, snapshot.html);
  restoreStyles(document.body, LOCKED_BODY_STYLES, snapshot.body);
  // Restore instantly despite smooth scrolling.
  html.style.scrollBehavior = "auto";
  window.scrollTo(snapshot.scrollLeft, snapshot.scrollTop);
  html.style.scrollBehavior = snapshot.html.scrollBehavior;
}

function finishRemoved(): void {
  for (const entry of [...shown].reverse()) {
    if (!entry.dialog.isConnected) finish(entry);
  }
}

function watchRemovals(): void {
  if (removalObserver) return;
  removalObserver = new MutationObserver(finishRemoved);
  removalObserver.observe(document, { childList: true, subtree: true });
}

function stopWatchingRemovals(): void {
  removalObserver?.disconnect();
  removalObserver = null;
}

const TABBABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function tabbableElements(dialog: HTMLDialogElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR)).filter(
    (element) =>
      element.tabIndex >= 0 &&
      nearestDialog(element) === dialog &&
      !element.closest("[hidden], [inert]"),
  );
}

/** Connected, shown, and not in a closed dialog. */
export function isReachable(element: HTMLElement): boolean {
  if (!element.isConnected || element.closest("[hidden], [inert]")) return false;
  const dialog = nearestDialog(element);
  return dialog === null || dialog.open;
}

/** The opener, else a reachable drop-down toggle. */
export function focusReturnTarget(opener: HTMLElement | null): HTMLElement | null {
  if (!opener) return null;
  if (isReachable(opener)) return opener;
  let dropdown = opener.closest<HTMLElement>("drop-down");
  while (dropdown) {
    const toggle = ownChild(dropdown, "[data-toggle]");
    if (toggle && isReachable(toggle)) return toggle;
    dropdown = dropdown.parentElement?.closest<HTMLElement>("drop-down") ?? null;
  }
  return null;
}

function returnFocus(entry: Entry): void {
  const target = focusReturnTarget(entry.opener);
  entry.opener = null;
  const remaining = openEntries().at(-1);
  if (remaining && !(target && remaining.dialog.contains(target))) {
    // The page under a modal is inert.
    remaining.focusInitial();
    if (!remaining.dialog.contains(document.activeElement)) {
      tabbableElements(remaining.dialog)[0]?.focus({ preventScroll: true });
    }
    return;
  }
  target?.focus({ preventScroll: true });
}

function closeAbove(entry: Entry): void {
  const index = shown.indexOf(entry);
  if (index === -1) return;
  for (const above of shown.slice(index + 1).reverse()) finish(above);
}

function clearLeaveLimit(entry: Entry): void {
  if (entry.leaveLimit !== null) window.clearTimeout(entry.leaveLimit);
  entry.leaveLimit = null;
}

/** Idempotent. */
function finish(entry: Entry): void {
  if (entry.state === "closed") return;
  closeAbove(entry);
  entry.state = "closed";
  entry.generation += 1;
  clearLeaveLimit(entry);
  if (entry.dialog.open) entry.dialog.close();
  const index = shown.indexOf(entry);
  if (index !== -1) shown.splice(index, 1);
  removeSurface(entry.surface);
  entry.dialog.removeAttribute(MODAL_ATTRIBUTES.covered);
  entry.dialog.removeAttribute(MODAL_ATTRIBUTES.over);
  markBackdrops();
  if (shown.length === 0) {
    stopWatchingRemovals();
    unlockDocumentScroll();
  }
  returnFocus(entry);
  notifyChange();
  // Layer already settled; a throw is reported.
  try {
    entry.options.onClosed?.();
  } catch (error) {
    report(`onClosed threw: ${String(error)}`);
  }
}

/** Undoes an open that never showed. */
function abandonOpen(entry: Entry): void {
  entry.opener = null;
  if (shown.length === 0) unlockDocumentScroll();
}

function refuseOpen(entry: Entry, detail: string): false {
  abandonOpen(entry);
  report(detail);
  return false;
}

function open(entry: Entry, opener: HTMLElement | undefined): boolean {
  if (entry.state === "open") return true;
  // A leave is timing, not a defect.
  if (entry.state === "leaving" || shown.some((other) => other.state === "leaving")) {
    return false;
  }
  if (!entry.surface.host.isConnected || !entry.dialog.isConnected) {
    return refuseOpen(entry, "dialog or host is detached");
  }
  const active = document.activeElement;
  entry.opener = opener ?? (active instanceof HTMLElement ? active : null);
  lockDocumentScroll();
  try {
    entry.dialog.showModal();
  } catch (error) {
    if (!isInvalidState(error)) {
      abandonOpen(entry);
      throw error;
    }
    return refuseOpen(entry, `showModal refused: ${String(error)}`);
  }
  // A cancelled beforetoggle is reported, not thrown.
  if (!entry.dialog.open) return refuseOpen(entry, "showModal left the dialog closed");
  entry.state = "open";
  entry.generation += 1;
  shown.push(entry);
  watchRemovals();
  pushSurface(entry.surface);
  markBackdrops();
  entry.focusInitial();
  notifyChange();
  return true;
}

function close(entry: Entry): void {
  if (entry.state === "closed") return;
  if (entry.state === "leaving") {
    // A detached host never ends its leave.
    if (!entry.surface.host.isConnected) finish(entry);
    return;
  }
  closeAbove(entry);
  entry.state = "leaving";
  // Inner panels close before the leave.
  removeSurface(entry.surface);
  markBackdrops();
  notifyChange();
  const leave = entry.options.leave;
  if (!entry.surface.host.isConnected || !leave) {
    finish(entry);
    return;
  }
  const generation = entry.generation;
  const finishThisClose: FinishLeave = () => {
    if (entry.generation === generation && entry.state === "leaving") finish(entry);
  };
  entry.leaveLimit = window.setTimeout(() => {
    if (entry.generation !== generation || entry.state !== "leaving") return;
    report("leave never called finish");
    finish(entry);
  }, LEAVE_LIMIT_MS);
  try {
    leave(finishThisClose);
  } catch (error) {
    report(`leave threw: ${String(error)}`);
    finishThisClose();
  }
}

export function attachModal(dialog: HTMLDialogElement, options: ModalOptions = {}): Modal {
  if (!dialog.hasAttribute(MODAL_ATTRIBUTES.modal)) {
    throw new TypeError("attachModal requires a <dialog data-modal>.");
  }
  if (options.host && !options.host.contains(dialog)) {
    throw new TypeError("attachModal: the host must contain the dialog.");
  }
  if (attached.has(dialog)) {
    throw new TypeError("attachModal: this dialog already has a modal.");
  }
  attached.add(dialog);
  let backdropPointer: PointerId | null = null;

  function chosenInitialFocus(): HTMLElement | null {
    try {
      return options.initialFocus?.() ?? null;
    } catch (error) {
      report(`initialFocus threw: ${String(error)}`);
      return null;
    }
  }

  const entry: Entry = {
    dialog,
    options,
    surface: { host: options.host ?? dialog, kind: "modal", close: () => close(entry) },
    state: "closed",
    opener: null,
    generation: 0,
    leaveLimit: null,
    focusInitial: () => {
      const target =
        chosenInitialFocus() ??
        Array.from(
          dialog.querySelectorAll<HTMLElement>(`[${MODAL_ATTRIBUTES.initial_focus}]`),
        ).find((element) => nearestDialog(element) === dialog);
      target?.focus();
    },
  };
  const dismiss = (): void => {
    if (entry.state !== "open") return;
    if (!options.dismiss) {
      close(entry);
      return;
    }
    try {
      options.dismiss();
    } catch (error) {
      // A broken veto must not trap anyone.
      report(`dismiss threw: ${String(error)}`);
      close(entry);
    }
  };
  const ownsEvent = (event: Event): boolean => nearestDialog(event.target) === dialog;

  dialog.addEventListener("cancel", (event) => {
    if (event.target !== dialog) return;
    // Not cancelable: the browser closes it.
    event.preventDefault();
    dismiss();
  });
  dialog.addEventListener("close", (event) => {
    // A queued close may follow a reopen.
    if (event.target === dialog && !dialog.open) finish(entry);
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab" || !ownsEvent(event) || topModal() !== dialog) return;
    const tabbable = tabbableElements(dialog);
    if (tabbable.length === 0) return;
    const first = tabbable[0];
    const last = tabbable[tabbable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !dialog.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.addEventListener("pointerdown", (event) => {
    backdropPointer = event.target === dialog ? event.pointerId : null;
  });
  dialog.addEventListener("pointerup", (event) => {
    const startedOnBackdrop = backdropPointer === event.pointerId;
    backdropPointer = null;
    if (startedOnBackdrop && event.target === dialog) dismiss();
  });
  dialog.addEventListener("pointercancel", () => {
    backdropPointer = null;
  });
  dialog.addEventListener("click", (event) => {
    if (!ownsEvent(event)) return;
    if ((event.target as Element).closest(`[${MODAL_ATTRIBUTES.dismiss}]`)) dismiss();
  });

  return {
    open: (opener) => open(entry, opener),
    close: () => close(entry),
    isOpen: () => entry.state === "open",
    state: () => entry.state,
    focusInitial: () => entry.focusInitial(),
  };
}

export function resetModalLayerForTests(): void {
  for (const entry of shown) {
    entry.state = "closed";
    entry.generation += 1;
    clearLeaveLimit(entry);
    removeSurface(entry.surface);
    if (entry.dialog.open) entry.dialog.close();
  }
  shown.length = 0;
  lastTop = null;
  stopWatchingRemovals();
  unlockDocumentScroll();
}
