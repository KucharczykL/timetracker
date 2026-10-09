// One layer owns every modal dialog.
import { reportClientError } from "../client-errors.js";
import { MODAL_ATTRIBUTES } from "../generated/modal-attributes.js";
import {
  clearStack,
  isSheetLevel,
  markStack,
  onStackResize,
  stopWatchingStack,
} from "./modal-stack.js";
import { holdLeave } from "../motion.js";
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
  /** Must call finish, now or later. Default: a centred fade. */
  leave?: (finish: FinishLeave) => void;
  /** Native cancel (Escape, back gesture); default dismiss.
   *
   * Best effort: the browser may close anyway.
   * onClosed is the one hook that always runs.
   */
  cancel?: () => void;
  /** Backdrop and dismiss control; default close. */
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

/** While one leaves, opens are refused. */
export function isModalLeaving(): boolean {
  return shown.some((entry) => entry.state === "leaving");
}

/** Takes nothing: it says only "the layer is quiet". */
export type SettledCallback = () => void;
export type CancelSettled = () => void;
//: A wrapper per call, so each cancels alone.
const settledCallbacks = new Set<{ callback: SettledCallback }>();
//: Nested closes and finishes in progress.
let settleDepth = 0;

/** Runs once no modal leaves; cancellable. */
export function whenSettled(callback: SettledCallback): CancelSettled {
  if (!isModalLeaving() && settleDepth === 0) {
    runSettled(callback);
    return () => undefined;
  }
  const queued = { callback };
  settledCallbacks.add(queued);
  return () => settledCallbacks.delete(queued);
}

//: Only an outermost close or finish flushes.
function settling(run: () => void): void {
  settleDepth += 1;
  try {
    run();
  } finally {
    settleDepth -= 1;
    if (settleDepth === 0) flushSettled();
  }
}

function flushSettled(): void {
  if (isModalLeaving()) return;
  const queued = [...settledCallbacks];
  settledCallbacks.clear();
  for (const { callback } of queued) runSettled(callback);
}

//: Both paths report a throw alike.
function runSettled(callback: SettledCallback): void {
  try {
    callback();
  } catch (error) {
    report(`a settle callback threw: ${String(error)}`);
  }
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

/** The topmost dialog that is not a level; the only one, when all are levels. */
function dimOwnerIndex(): number {
  for (let index = shown.length - 1; index >= 0; index -= 1) {
    if (!isSheetLevel(shown[index].dialog)) return index;
  }
  return shown.length - 1;
}

function markBackdrops(): void {
  // A level belongs to the dialog below it, so it does not cover that dialog.
  const owner = dimOwnerIndex();
  shown.forEach((entry, index) => {
    entry.dialog.toggleAttribute(MODAL_ATTRIBUTES.covered, index < owner);
    entry.dialog.toggleAttribute(MODAL_ATTRIBUTES.over, index > 0);
  });
}

type StepName = string; // e.g. "markStack"

/** Cosmetic; a throw must not unsettle the layer. */
function cosmetic(name: StepName, step: () => void): void {
  try {
    step();
  } catch (error) {
    report(`${name} threw: ${String(error)}`);
  }
}

function markDepth(): void {
  cosmetic("markStack", () => markStack(shown));
}

function unmarkDepth(dialog: HTMLDialogElement): void {
  cosmetic("clearStack", () => clearStack(dialog));
}

function markShown(): void {
  markBackdrops();
  markDepth();
}

/** Measures the stack again; safe when empty. */
export function refreshModalStack(): void {
  markDepth();
}

onStackResize(refreshModalStack);

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

/** Finishes the modals above, without focus: the one below returns it. */
function closeAbove(entry: Entry): void {
  const index = shown.indexOf(entry);
  if (index === -1) return;
  for (const above of shown.slice(index + 1).reverse()) finish(above, false);
}

function clearLeaveLimit(entry: Entry): void {
  if (entry.leaveLimit !== null) window.clearTimeout(entry.leaveLimit);
  entry.leaveLimit = null;
}

/** Idempotent. */
function finish(entry: Entry, returnsFocus = true): void {
  settling(() => finishEntry(entry, returnsFocus));
}

function finishEntry(entry: Entry, returnsFocus: boolean): void {
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
  unmarkDepth(entry.dialog);
  markShown();
  if (shown.length === 0) {
    stopWatchingRemovals();
    stopWatchingStack();
    unlockDocumentScroll();
  }
  if (returnsFocus) returnFocus(entry);
  else entry.opener = null;
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
  markShown();
  entry.focusInitial();
  notifyChange();
  return true;
}

function close(entry: Entry): void {
  settling(() => closeEntry(entry));
}

function closeEntry(entry: Entry): void {
  if (entry.state === "closed") return;
  if (entry.state === "leaving") {
    // A detached host never ends its leave.
    if (!entry.surface.host.isConnected) finish(entry);
    return;
  }
  closeAbove(entry);
  markLeaving([entry]);
  runLeave(entry, () => finish(entry));
}

/** Marks modals leaving; inner panels close before their leave. */
function markLeaving(group: readonly Entry[]): void {
  for (const entry of group) {
    entry.state = "leaving";
    removeSurface(entry.surface);
  }
  markShown();
  notifyChange();
}

/** Runs the top's leave; `done` runs once it finishes, or at once when none. */
function runLeave(entry: Entry, done: () => void): void {
  const leave = entry.options.leave;
  if (!entry.surface.host.isConnected || !leave) {
    done();
    return;
  }
  const generation = entry.generation;
  const finishThisClose: FinishLeave = () => {
    if (entry.generation === generation && entry.state === "leaving") done();
  };
  entry.leaveLimit = window.setTimeout(() => {
    if (entry.generation !== generation || entry.state !== "leaving") return;
    report("leave never called finish");
    done();
  }, LEAVE_LIMIT_MS);
  try {
    leave(finishThisClose);
  } catch (error) {
    report(`leave threw: ${String(error)}`);
    finishThisClose();
  }
}

/** Finishes a group topmost first in one task; only the lowest returns focus. */
function finishGroup(group: readonly Entry[]): void {
  settling(() => {
    for (const entry of [...group].reverse()) finishEntry(entry, entry === group[0]);
  });
}

/** Closes a modal and every modal above it as one act. */
function closeGroup(first: Entry): void {
  settling(() => {
    if (first.state !== "open") return;
    const group = shown.slice(shown.indexOf(first));
    // A leave is already running above; the close waits for it.
    if (group.some((entry) => entry.state !== "open")) return;
    markLeaving(group);
    runLeave(group[group.length - 1], () => finishGroup(group));
  });
}

/** Closes the dialog and every modal stacked above it; one leave runs. */
export function closeTogether(dialog: HTMLDialogElement): void {
  const first = shown.find((entry) => entry.dialog === dialog);
  if (first) closeGroup(first);
}

/** A centred modal's exit: held until its fade ends. */
function centredLeave(dialog: HTMLDialogElement): (finish: FinishLeave) => void {
  return (finish) => {
    holdLeave(dialog, "medium-exit", finish);
  };
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
    options: { ...options, leave: options.leave ?? centredLeave(dialog) },
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
  const cancelNative = (): void => {
    if (!options.cancel) {
      dismiss();
      return;
    }
    if (entry.state !== "open") return;
    try {
      options.cancel();
    } catch (error) {
      report(`cancel threw: ${String(error)}`);
      close(entry);
    }
  };
  const ownsEvent = (event: Event): boolean => nearestDialog(event.target) === dialog;

  dialog.addEventListener("cancel", (event) => {
    if (event.target !== dialog) return;
    event.preventDefault();
    // Not cancelable: the browser closes it.
    if (event.cancelable) cancelNative();
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
    entry.dialog.removeAttribute(MODAL_ATTRIBUTES.covered);
    entry.dialog.removeAttribute(MODAL_ATTRIBUTES.over);
    unmarkDepth(entry.dialog);
  }
  shown.length = 0;
  settledCallbacks.clear();
  settleDepth = 0;
  stopWatchingStack();
  lastTop = null;
  stopWatchingRemovals();
  unlockDocumentScroll();
}
