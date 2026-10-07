/** The bottom sheet's slide and lifecycle events. */
import type { MenuController } from "./menu-behavior.js";
import { MODAL_ATTRIBUTES } from "../generated/modal-attributes.js";
import { attachModal, isReachable, type FinishLeave } from "./modal-layer.js";

type SheetState = "closed" | "opening" | "open" | "closing";

interface PendingNavigation {
  hash: string;
  destination: HTMLElement;
  focusTarget: HTMLElement;
}

type TimerHandle = number;
type FrameHandle = number;

interface PendingLeave {
  finish: FinishLeave;
  timer: TimerHandle;
}

// A missed transitionend; under the layer's cap.
const CLOSE_FALLBACK_MS = 250;

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
    destination.querySelector<HTMLElement>(
      "[data-sectioned-page-section-heading]",
    ) ??
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

/** The sheet's hooks around a close. */
export interface SheetCoreOptions {
  initialFocus?: () => HTMLElement | null;
  /** Runs before `dropdown:show`. */
  beforeShow?: () => void;
  /** Runs before `dropdown:hide`. */
  beforeHide?: () => void;
  /** Runs after `dropdown:hide`. */
  afterHide?: () => void;
}

export interface SheetCore {
  /** False when the modal layer refused. */
  open: (opener?: HTMLElement) => boolean;
  close: () => void;
  isOpen: () => boolean;
  focusFirst: () => void;
}

/** A sheet with no toggle of its own. */
export function attachSheetCore(
  host: HTMLElement,
  dialog: HTMLDialogElement,
  options: SheetCoreOptions = {},
): SheetCore {
  const panel = dialog.querySelector<HTMLElement>("[data-sheet-panel]");
  if (!panel) {
    throw new TypeError("A bottom sheet requires [data-sheet-panel].");
  }

  let entered = false;
  let openFrame: FrameHandle | null = null;
  let pendingLeave: PendingLeave | null = null;

  const sheetState = (): SheetState => {
    switch (modal.state()) {
      case "closed":
        return "closed";
      case "leaving":
        return "closing";
      case "open":
        return entered ? "open" : "opening";
    }
  };
  const render = (): void => {
    dialog.dataset.sheetState = sheetState();
  };

  const cancelOpenFrame = (): void => {
    if (openFrame !== null) window.cancelAnimationFrame(openFrame);
    openFrame = null;
  };

  const clearMotion = (): void => {
    cancelOpenFrame();
    if (pendingLeave) window.clearTimeout(pendingLeave.timer);
    pendingLeave = null;
    entered = false;
  };

  const modal = attachModal(dialog, {
    host,
    initialFocus: () =>
      options.initialFocus?.() ??
      dialog.querySelector<HTMLElement>(`[${MODAL_ATTRIBUTES.dismiss}]`),
    leave: (finish) => {
      if (prefersReducedMotion()) {
        finish();
        return;
      }
      cancelOpenFrame();
      pendingLeave = { finish, timer: window.setTimeout(finish, CLOSE_FALLBACK_MS) };
      render();
    },
    onClosed: () => {
      clearMotion();
      options.beforeHide?.();
      render();
      host.dispatchEvent(new CustomEvent("dropdown:hide", { bubbles: true }));
      options.afterHide?.();
    },
  });
  render();

  const open = (opener?: HTMLElement): boolean => {
    if (modal.state() !== "closed") return false;
    if (!modal.open(opener)) return false;
    options.beforeShow?.();
    render();
    host.dispatchEvent(new CustomEvent("dropdown:show", { bubbles: true }));
    openFrame = window.requestAnimationFrame(() => {
      openFrame = null;
      entered = true;
      render();
    });
    return true;
  };

  panel.addEventListener("transitionend", (event) => {
    // Tailwind's translate-y animates translate.
    if (event.target === panel && event.propertyName === "translate") {
      pendingLeave?.finish();
    }
  });

  return {
    open,
    close: () => modal.close(),
    isOpen: () => modal.isOpen(),
    focusFirst: () => modal.focusInitial(),
  };
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
  if (!dialog.querySelector("[data-sheet-panel]")) {
    throw new TypeError('drop-down behavior="sheet" requires [data-sheet-panel].');
  }

  let pendingNavigation: PendingNavigation | null = null;

  const sheet = attachSheetCore(host, dialog, {
    // Native steps would focus the close button.
    initialFocus: () => dialog.querySelector<HTMLElement>("nav a[href]"),
    beforeShow: () => toggle.setAttribute("aria-expanded", "true"),
    beforeHide: () => toggle.setAttribute("aria-expanded", "false"),
    afterHide: () => {
      const navigation = pendingNavigation;
      pendingNavigation = null;
      if (navigation) navigateTo(navigation);
    },
  });

  const open = (): void => {
    if (sheet.isOpen()) return;
    // A hidden trigger: the sheet is unavailable.
    if (!isReachable(toggle)) return;
    // Safari does not focus a clicked button.
    sheet.open(toggle);
  };

  toggle.addEventListener("click", () => (sheet.isOpen() ? sheet.close() : open()));
  dialog.addEventListener("click", (event) => {
    const clicked = event.target as Element;
    if (clicked.closest("dialog") !== dialog) return;
    const link = clicked.closest<HTMLAnchorElement>("nav a[href]");
    if (!link) return;
    const navigation = sameDocumentDestination(link);
    if (!navigation) return;
    event.preventDefault();
    pendingNavigation = navigation;
    sheet.close();
  });

  return { open, close: sheet.close, isOpen: sheet.isOpen, focusFirst: sheet.focusFirst };
}
