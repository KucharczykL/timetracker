// One layer owns every modal dialog.
//
// Modals nest: the stack holds them in opening order. The layer owns
// the scroll lock, the Tab boundary, dismissal, focus return and the
// backdrop marks. It knows no form and no fetch.
import { reportClientError } from "../client-errors.js";
import { ownChild } from "./own-child.js";
import { pushSurface, removeSurface, type ModalSurface } from "./surface-stack.js";

export const MODAL_CHANGE = "modal-layer:change";

export interface ModalOptions {
  /** The surface host; defaults to the dialog. */
  host?: HTMLElement;
  initialFocus?: () => HTMLElement | null;
  /** True: it calls finish itself. */
  leave?: (finish: () => void) => boolean;
  /** Escape, backdrop and dismiss control. */
  dismiss?: () => void;
  /** Runs last, after focus return. */
  onClosed?: () => void;
}

export interface Modal {
  open(opener?: HTMLElement | null): boolean;
  close(): void;
  isOpen(): boolean;
  focusInitial(): void;
}

type ModalState = "closed" | "open" | "leaving";

interface Entry {
  readonly dialog: HTMLDialogElement;
  readonly host: HTMLElement;
  readonly options: ModalOptions;
  readonly surface: ModalSurface;
  state: ModalState;
  opener: HTMLElement | null;
  /** Bumped on every open and finish. */
  generation: number;
  focusInitial(): void;
}

interface ScrollLockSnapshot {
  x: number;
  y: number;
  htmlOverflow: string;
  htmlOverscrollBehavior: string;
  htmlScrollBehavior: string;
  bodyPosition: string;
  bodyTop: string;
  bodyRight: string;
  bodyBottom: string;
  bodyLeft: string;
  bodyWidth: string;
  bodyOverflow: string;
  bodyPaddingRight: string;
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

export function topModal(): HTMLDialogElement | null {
  return openEntries().at(-1)?.dialog ?? null;
}

export function isModalOpen(): boolean {
  return topModal() !== null;
}

function nearestDialog(target: EventTarget | null): HTMLDialogElement | null {
  return target instanceof Element ? target.closest("dialog") : null;
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
    entry.dialog.toggleAttribute("data-modal-covered", index !== shown.length - 1);
    entry.dialog.toggleAttribute("data-modal-over", index > 0);
  });
}

function lockDocumentScroll(): void {
  if (scrollLock) return;
  const html = document.documentElement;
  const body = document.body;
  const x = window.scrollX;
  const y = window.scrollY;
  scrollLock = {
    x,
    y,
    htmlOverflow: html.style.overflow,
    htmlOverscrollBehavior: html.style.overscrollBehavior,
    htmlScrollBehavior: html.style.scrollBehavior,
    bodyPosition: body.style.position,
    bodyTop: body.style.top,
    bodyRight: body.style.right,
    bodyBottom: body.style.bottom,
    bodyLeft: body.style.left,
    bodyWidth: body.style.width,
    bodyOverflow: body.style.overflow,
    bodyPaddingRight: body.style.paddingRight,
  };
  const scrollbarWidth = Math.max(0, window.innerWidth - html.clientWidth);
  const bodyPadding = Number.parseFloat(getComputedStyle(body).paddingRight) || 0;
  html.style.overflow = "hidden";
  html.style.overscrollBehavior = "none";
  // iOS scrolls under overflow: hidden alone.
  body.style.position = "fixed";
  body.style.top = `-${y}px`;
  body.style.right = "0";
  body.style.bottom = "auto";
  body.style.left = `-${x}px`;
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
  const body = document.body;
  html.style.overflow = snapshot.htmlOverflow;
  html.style.overscrollBehavior = snapshot.htmlOverscrollBehavior;
  // Restore instantly despite smooth scrolling.
  html.style.scrollBehavior = "auto";
  body.style.position = snapshot.bodyPosition;
  body.style.top = snapshot.bodyTop;
  body.style.right = snapshot.bodyRight;
  body.style.bottom = snapshot.bodyBottom;
  body.style.left = snapshot.bodyLeft;
  body.style.width = snapshot.bodyWidth;
  body.style.overflow = snapshot.bodyOverflow;
  body.style.paddingRight = snapshot.bodyPaddingRight;
  window.scrollTo(snapshot.x, snapshot.y);
  html.style.scrollBehavior = snapshot.htmlScrollBehavior;
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

function tabbableElements(dialog: HTMLDialogElement): HTMLElement[] {
  const selector = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");
  return Array.from(dialog.querySelectorAll<HTMLElement>(selector)).filter(
    (element) =>
      element.tabIndex >= 0 &&
      nearestDialog(element) === dialog &&
      !element.closest("[hidden], [inert]"),
  );
}

function isReachable(element: HTMLElement): boolean {
  return element.isConnected && !element.closest("[hidden], [inert]");
}

/** The opener, else an enclosing drop-down's toggle. */
function focusReturnTarget(opener: HTMLElement | null): HTMLElement | null {
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

/** Idempotent. */
function finish(entry: Entry): void {
  if (entry.state === "closed") return;
  closeAbove(entry);
  entry.state = "closed";
  entry.generation += 1;
  if (entry.dialog.open) entry.dialog.close();
  const index = shown.indexOf(entry);
  if (index !== -1) shown.splice(index, 1);
  removeSurface(entry.surface);
  entry.dialog.removeAttribute("data-modal-covered");
  entry.dialog.removeAttribute("data-modal-over");
  markBackdrops();
  if (shown.length === 0) {
    stopWatchingRemovals();
    unlockDocumentScroll();
  }
  returnFocus(entry);
  notifyChange();
  entry.options.onClosed?.();
}

function open(entry: Entry, opener: HTMLElement | null | undefined): boolean {
  if (entry.state === "open") return true;
  if (entry.state === "leaving" || shown.some((other) => other.state === "leaving")) {
    return false;
  }
  if (!entry.host.isConnected || !entry.dialog.isConnected) return false;
  const active = document.activeElement;
  entry.opener = opener ?? (active instanceof HTMLElement ? active : null);
  lockDocumentScroll();
  try {
    entry.dialog.showModal();
  } catch (error) {
    entry.opener = null;
    if (shown.length === 0) unlockDocumentScroll();
    reportClientError("modal-layer", `showModal refused: ${String(error)}`, {
      toast: false,
    });
    return false;
  }
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
    if (!entry.host.isConnected) finish(entry);
    return;
  }
  closeAbove(entry);
  entry.state = "leaving";
  // Inner panels close before the leave.
  removeSurface(entry.surface);
  markBackdrops();
  notifyChange();
  const leave = entry.options.leave;
  if (!entry.host.isConnected || !leave) {
    finish(entry);
    return;
  }
  const generation = entry.generation;
  const finishThisClose = (): void => {
    if (entry.generation === generation && entry.state === "leaving") finish(entry);
  };
  if (!leave(finishThisClose)) finishThisClose();
}

export function attachModal(dialog: HTMLDialogElement, options: ModalOptions = {}): Modal {
  if (!dialog.hasAttribute("data-modal")) {
    throw new TypeError("attachModal requires a <dialog data-modal>.");
  }
  if (attached.has(dialog)) {
    throw new TypeError("attachModal: this dialog already has a modal.");
  }
  attached.add(dialog);
  let backdropPointer: number | null = null;

  const entry: Entry = {
    dialog,
    host: options.host ?? dialog,
    options,
    surface: { host: options.host ?? dialog, kind: "modal", close: () => close(entry) },
    state: "closed",
    opener: null,
    generation: 0,
    focusInitial: () => {
      const target =
        options.initialFocus?.() ??
        Array.from(dialog.querySelectorAll<HTMLElement>("[data-modal-initial-focus]")).find(
          (element) => nearestDialog(element) === dialog,
        );
      target?.focus();
    },
  };
  const dismiss = (): void => {
    if (entry.state !== "open") return;
    if (options.dismiss) options.dismiss();
    else close(entry);
  };
  const ownsEvent = (event: Event): boolean => nearestDialog(event.target) === dialog;

  dialog.addEventListener("cancel", (event) => {
    if (event.target !== dialog) return;
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
    if ((event.target as Element).closest("[data-modal-dismiss]")) dismiss();
  });

  return {
    open: (opener) => open(entry, opener),
    close: () => close(entry),
    isOpen: () => entry.state === "open",
    focusInitial: () => entry.focusInitial(),
  };
}

export function resetModalLayerForTests(): void {
  for (const entry of shown) {
    entry.state = "closed";
    entry.generation += 1;
  }
  shown.length = 0;
  lastTop = null;
  stopWatchingRemovals();
  unlockDocumentScroll();
}
