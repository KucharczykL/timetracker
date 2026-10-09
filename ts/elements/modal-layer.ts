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
import { clearLeaving, holdLeave, markLeaving } from "../motion.js";
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
export type ModalHook = () => void;

export interface LeaveContext {
  /** Part of a chain closing at once. */
  readonly together: boolean;
}

export interface ModalOptions {
  /** The surface host; defaults to the dialog. */
  host?: HTMLElement;
  initialFocus?: () => HTMLElement | null;
  /** Must call finish. Default: centred fade. */
  leave?: (finish: FinishLeave, context: LeaveContext) => void;
  /** Escape, back gesture, back control; default dismiss. */
  cancel?: ModalHook;
  /** Backdrop and dismiss control; default close. */
  dismiss?: ModalHook;
  /** Runs before focus returns. */
  beforeFocusReturn?: ModalHook;
  /** Runs last, after focus return. */
  onClosed?: ModalHook;
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
  /** The chain this modal leaves with. */
  group: readonly Entry[] | null;
  focusInitial(): void;
  requestCancel(): void;
  requestDismiss(): void;
}

type Step = "cancel" | "dismiss";

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
    reported("a settle callback", callback);
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
  for (const { callback } of queued) reported("a settle callback", callback);
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

/** Topmost dialog that is not a level. */
function dimOwnerIndex(): number {
  for (let index = shown.length - 1; index >= 0; index -= 1) {
    if (!isSheetLevel(shown[index].dialog)) return index;
  }
  return shown.length - 1;
}

function markBackdrops(): void {
  // Levels never cover the dialog below.
  const owner = dimOwnerIndex();
  shown.forEach((entry, index) => {
    entry.dialog.toggleAttribute(MODAL_ATTRIBUTES.covered, index < owner);
    // Levels never dim their own backdrop.
    entry.dialog.toggleAttribute(
      MODAL_ATTRIBUTES.over,
      index > 0 && !isSheetLevel(entry.dialog),
    );
  });
}

type StepName = string; // e.g. "markStack"

/** A throw is reported; the layer stays settled. */
function reported(name: StepName, step: () => void): void {
  try {
    step();
  } catch (error) {
    report(`${name} threw: ${String(error)}`);
  }
}

function markDepth(): void {
  reported("markStack", () => markStack(shown));
}

function unmarkDepth(dialog: HTMLDialogElement): void {
  reported("clearStack", () => clearStack(dialog));
}

function unmarkBackdrop(dialog: HTMLDialogElement): void {
  dialog.removeAttribute(MODAL_ATTRIBUTES.covered);
  dialog.removeAttribute(MODAL_ATTRIBUTES.over);
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
  if (remaining && target && remaining.dialog.contains(target)) {
    target.focus({ preventScroll: true });
    // A hidden target takes no focus.
    if (document.activeElement !== target) focusInto(remaining);
    return;
  }
  // The page under a modal is inert.
  if (remaining) focusInto(remaining);
  else target?.focus({ preventScroll: true });
}

function focusInto(entry: Entry): void {
  entry.focusInitial();
  if (!entry.dialog.contains(document.activeElement)) {
    tabbableElements(entry.dialog)[0]?.focus({ preventScroll: true });
  }
}

/** Finishes modals above; no focus return. */
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
  const group = entry.group;
  entry.group = null;
  closeAbove(entry);
  entry.state = "closed";
  entry.generation += 1;
  clearLeaveLimit(entry);
  if (entry.dialog.open) entry.dialog.close();
  const index = shown.indexOf(entry);
  if (index !== -1) shown.splice(index, 1);
  removeSurface(entry.surface);
  unmarkBackdrop(entry.dialog);
  clearLeaving(entry.dialog);
  unmarkDepth(entry.dialog);
  markShown();
  if (shown.length === 0) {
    stopWatchingRemovals();
    stopWatchingStack();
    unlockDocumentScroll();
  }
  const lowest = group?.[0] ?? entry;
  reported("beforeFocusReturn", () => entry.options.beforeFocusReturn?.());
  // In a chain, the lowest returns focus.
  if (returnsFocus && lowest === entry) returnFocus(entry);
  else entry.opener = null;
  notifyChange();
  // Layer already settled; a throw is reported.
  reported("onClosed", () => entry.options.onClosed?.());
  // A chain whose top ended elsewhere still ends.
  for (const member of [...(group ?? [])].reverse()) {
    if (member.state === "leaving") finishEntry(member, returnsFocus);
  }
}

function requestStep(entry: Entry, step: Step): void {
  if (step === "cancel") entry.requestCancel();
  else entry.requestDismiss();
}

/** The step a pressed control asks. */
function pressedStep(target: Element): Step | null {
  if (target.closest(`[${MODAL_ATTRIBUTES.dismiss}]`)) return "dismiss";
  if (target.closest(`[${MODAL_ATTRIBUTES.cancel}]`)) return "cancel";
  return null;
}

/** A step pressed during a leave runs after it. */
function queueStep(step: Step): void {
  const run = (): void => {
    if (isModalLeaving()) {
      whenSettled(run);
      return;
    }
    const top = openEntries().at(-1);
    if (top) requestStep(top, step);
  };
  whenSettled(run);
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
  if (isModalLeaving()) return false;
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
  markChainLeaving([entry]);
  runLeave(entry, () => finish(entry));
}

/** Marks each modal leaving, as one chain. */
function markChainLeaving(group: readonly Entry[]): void {
  for (const entry of group) {
    entry.state = "leaving";
    entry.group = group.length > 1 ? group : null;
  }
  // Marked first: a removal closes surfaces above.
  for (const entry of [...group].reverse()) removeSurface(entry.surface);
  markShown();
  notifyChange();
}

/** Runs the top leave; then done. */
function runLeave(entry: Entry, done: () => void, together = false): void {
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
    leave(finishThisClose, { together });
  } catch (error) {
    report(`leave threw: ${String(error)}`);
    finishThisClose();
  }
}

/** Finishes a group; lowest returns focus. */
function finishGroup(group: readonly Entry[]): void {
  settling(() => {
    // Each member knows its chain; the lowest focuses.
    for (const entry of [...group].reverse()) finishEntry(entry, true);
  });
}

/** Closes a modal and those above it. */
function closeGroup(first: Entry): void {
  settling(() => {
    if (first.state !== "open") return;
    const group = shown.slice(shown.indexOf(first));
    // A leave above runs: close after it.
    if (group.some((entry) => entry.state !== "open")) {
      whenSettled(() => {
        if (first.state === "open") closeGroup(first);
      });
      return;
    }
    markChainLeaving(group);
    // Lower members fade their backdrops along.
    for (const member of group.slice(0, -1)) markLeaving(member.dialog);
    runLeave(group[group.length - 1], () => finishGroup(group), group.length > 1);
  });
}

/** Closes dialog and modals above; one leave. */
export function closeTogether(dialog: HTMLDialogElement): void {
  const first = shown.find((entry) => entry.dialog === dialog);
  if (first) closeGroup(first);
}

/** Centred modal exit; held until fade ends. */
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
    group: null,
    requestCancel: () => cancelNative(),
    requestDismiss: () => dismiss(),
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
    if (!event.cancelable) return;
    if (entry.state === "leaving") queueStep("cancel");
    else cancelNative();
  });
  // A leaving modal acts on nothing; steps queue.
  const holdWhileLeaving = (event: Event): void => {
    if (entry.state !== "leaving" || !ownsEvent(event)) return;
    if (event.type === "click") {
      const target = event.target as Element;
      const step = target === dialog ? "dismiss" : pressedStep(target);
      if (step) queueStep(step);
    }
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  for (const type of ["pointerdown", "pointerup", "click"] as const) {
    dialog.addEventListener(type, holdWhileLeaving, { capture: true });
  }
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
    const step = pressedStep(event.target as Element);
    if (step) requestStep(entry, step);
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
    entry.group = null;
    clearLeaveLimit(entry);
    removeSurface(entry.surface);
    if (entry.dialog.open) entry.dialog.close();
    unmarkBackdrop(entry.dialog);
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
