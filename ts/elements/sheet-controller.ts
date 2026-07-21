/** Modal bottom-sheet controller for the generic <drop-down> shell.
 *
 * The shell supplies stable trigger/panel IDs and public open/close methods;
 * this controller deliberately supplies none of attachMenu's anchored geometry
 * or ARIA-menu keyboard model. A native <dialog> owns modality while this layer
 * owns the cross-browser Tab boundary, animation, backdrop gestures, scroll
 * locking, and the close-then-navigate section-link path.
 */
import {
  type MenuController,
  notifyDropdownOpen,
  OPEN_MENUS_EVENT,
  type OpenMenuDetail,
} from "./menu-behavior.js";

type SheetState = "closed" | "opening" | "open" | "closing";

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

interface PendingNavigation {
  hash: string;
  destination: HTMLElement;
  focusTarget: HTMLElement;
}

interface ActiveSheet {
  host: HTMLElement;
  closeImmediately: () => void;
}

const CLOSE_FALLBACK_MS = 250;
let activeSheet: ActiveSheet | null = null;

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function sameDocumentDestination(link: HTMLAnchorElement): PendingNavigation | null {
  const url = new URL(link.href, window.location.href);
  if (
    url.origin !== window.location.origin ||
    url.pathname !== window.location.pathname ||
    url.search !== window.location.search ||
    !url.hash
  ) {
    return null;
  }
  const id = decodeURIComponent(url.hash.slice(1));
  const destination = document.getElementById(id);
  if (!destination) return null;
  const focusTarget =
    destination.querySelector<HTMLElement>("[data-settings-section-heading]") ??
    destination;
  return { hash: url.hash, destination, focusTarget };
}

function navigateTo(pending: PendingNavigation): void {
  if (window.location.hash !== pending.hash) window.location.hash = pending.hash;
  // Setting an already-current hash does not scroll in every browser. Always
  // make the final placement explicit, then move the accessibility context
  // without allowing focus itself to undo the scroll-margin placement.
  pending.destination.scrollIntoView({ block: "start" });
  pending.focusTarget.focus({ preventScroll: true });
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
    (element) => element.tabIndex >= 0 && !element.closest("[hidden], [inert]"),
  );
}

export function attachSheet(
  host: HTMLElement,
  toggle: HTMLElement,
  target: HTMLElement,
): MenuController {
  if (!(target instanceof HTMLDialogElement)) {
    throw new TypeError('drop-down behavior="sheet" requires a <dialog> target.');
  }
  const dialog = target;
  const panel = dialog.querySelector<HTMLElement>("[data-sheet-panel]");
  if (!panel) {
    throw new TypeError('drop-down behavior="sheet" requires [data-sheet-panel].');
  }

  let state: SheetState = "closed";
  let lifecycleOpen = false;
  let scrollLock: ScrollLockSnapshot | null = null;
  let closeTimer = 0;
  let openFrame = 0;
  let backdropPointer: number | null = null;
  let pendingNavigation: PendingNavigation | null = null;
  let owner: ActiveSheet;

  const setState = (next: SheetState): void => {
    state = next;
    dialog.dataset.sheetState = next;
  };

  const lockDocumentScroll = (): void => {
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
  };

  const unlockDocumentScroll = (): void => {
    const snapshot = scrollLock;
    if (!snapshot) return;
    scrollLock = null;
    const html = document.documentElement;
    const body = document.body;
    html.style.overflow = snapshot.htmlOverflow;
    html.style.overscrollBehavior = snapshot.htmlOverscrollBehavior;
    // Force an instant restoration even if the page enables smooth scrolling.
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
  };

  const clearMotion = (): void => {
    window.cancelAnimationFrame(openFrame);
    openFrame = 0;
    window.clearTimeout(closeTimer);
    closeTimer = 0;
  };

  const finishClose = (): void => {
    const wasOpen = lifecycleOpen;
    const navigation = pendingNavigation;
    pendingNavigation = null;
    clearMotion();
    if (dialog.open) dialog.close();
    lifecycleOpen = false;
    toggle.setAttribute("aria-expanded", "false");
    setState("closed");
    unlockDocumentScroll();
    if (activeSheet === owner) activeSheet = null;
    if (wasOpen) {
      host.dispatchEvent(new CustomEvent("dropdown:hide", { bubbles: true }));
    }
    if (navigation) navigateTo(navigation);
  };

  const isOpen = (): boolean => lifecycleOpen && dialog.open;

  const focusFirst = (): void => {
    const first =
      dialog.querySelector<HTMLElement>("[data-sheet-initial-focus]") ??
      dialog.querySelector<HTMLElement>("nav a[href]") ??
      dialog.querySelector<HTMLElement>("[data-sheet-dismiss]");
    first?.focus();
  };

  const open = (): void => {
    if (state !== "closed" || dialog.open) return;
    // A sheet's scroll snapshot is meaningful only when it starts from the
    // unlocked document. Close any previously active sheet synchronously—an
    // animated overlap would let the first sheet restore styles underneath the
    // second, and the second would later restore the first sheet's locked state.
    while (activeSheet && activeSheet !== owner) {
      activeSheet.closeImmediately();
    }
    lockDocumentScroll();
    try {
      dialog.showModal();
    } catch (error) {
      toggle.setAttribute("aria-expanded", "false");
      setState("closed");
      unlockDocumentScroll();
      console.error("Unable to open modal bottom sheet.", error);
      return;
    }
    lifecycleOpen = true;
    activeSheet = owner;
    toggle.setAttribute("aria-expanded", "true");
    setState("opening");
    notifyDropdownOpen(host);
    host.dispatchEvent(new CustomEvent("dropdown:show", { bubbles: true }));
    focusFirst();
    openFrame = window.requestAnimationFrame(() => {
      openFrame = 0;
      if (state === "opening") setState("open");
    });
  };

  const close = (): void => {
    if (!lifecycleOpen && !dialog.open) {
      // Failed-open/disconnect cleanup remains safe and idempotent.
      toggle.setAttribute("aria-expanded", "false");
      unlockDocumentScroll();
      setState("closed");
      return;
    }
    if (state === "closing") return;
    if (!host.isConnected || prefersReducedMotion()) {
      finishClose();
      return;
    }
    setState("closing");
    closeTimer = window.setTimeout(finishClose, CLOSE_FALLBACK_MS);
  };

  const onToggleClick = (): void => (isOpen() ? close() : open());
  const onCancel = (event: Event): void => {
    event.preventDefault();
    close();
  };
  const onDialogKeyDown = (event: KeyboardEvent): void => {
    // The modal top layer makes the background inert, but browser focus loops
    // differ at the sequential-navigation boundary. Keep Tab inside locally;
    // Escape intentionally remains owned only by the native cancel event.
    if (event.key !== "Tab") return;
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
  };
  const onPointerDown = (event: PointerEvent): void => {
    backdropPointer = event.target === dialog ? event.pointerId : null;
  };
  const onPointerCancel = (): void => {
    backdropPointer = null;
  };
  const onDialogClick = (event: MouseEvent): void => {
    const clicked = event.target as Element;
    if (clicked.closest("[data-sheet-dismiss]")) {
      close();
      return;
    }
    const link = clicked.closest<HTMLAnchorElement>("nav a[href]");
    if (link) {
      const navigation = sameDocumentDestination(link);
      if (!navigation) return;
      event.preventDefault();
      pendingNavigation = navigation;
      close();
      return;
    }
    if (event.target === dialog && backdropPointer !== null) close();
    backdropPointer = null;
  };
  const onPanelTransitionEnd = (event: TransitionEvent): void => {
    if (
      state === "closing" &&
      event.target === panel &&
      event.propertyName === "transform"
    ) {
      finishClose();
    }
  };
  const onNativeClose = (): void => finishClose();
  const onOtherDropdownOpen = (event: Event): void => {
    const detail = (event as CustomEvent<OpenMenuDetail>).detail;
    if (!detail || detail.host === host || host.contains(detail.host)) return;
    close();
  };

  toggle.addEventListener("click", onToggleClick);
  dialog.addEventListener("cancel", onCancel);
  dialog.addEventListener("keydown", onDialogKeyDown);
  dialog.addEventListener("pointerdown", onPointerDown);
  dialog.addEventListener("pointercancel", onPointerCancel);
  dialog.addEventListener("click", onDialogClick);
  dialog.addEventListener("close", onNativeClose);
  panel.addEventListener("transitionend", onPanelTransitionEnd);

  const bindDocument = (): (() => void) => {
    document.addEventListener(OPEN_MENUS_EVENT, onOtherDropdownOpen);
    return () => {
      document.removeEventListener(OPEN_MENUS_EVENT, onOtherDropdownOpen);
    };
  };

  owner = { host, closeImmediately: finishClose };

  return { open, close, isOpen, focusFirst, bindDocument };
}
