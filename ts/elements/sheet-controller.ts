/** The bottom sheet's slide and lifecycle events. */
import { dispatchHide, type DropdownHideDetail, type MenuController } from "./menu-behavior.js";
import { MODAL_ATTRIBUTES } from "../generated/modal-attributes.js";
import { SHEET_ATTRIBUTES } from "../generated/sheet-attributes.js";
import { attachModal, isReachable, type FinishLeave } from "./modal-layer.js";
import { holdLeave, type CancelLeave } from "../motion.js";
import { clearLevel, popLevel, pushLevel, type LevelPlacement } from "./sheet-levels.js";

type SheetState = "closed" | "opening" | "open" | "closing";

interface PendingNavigation {
  hash: string;
  destination: HTMLElement;
  focusTarget: HTMLElement;
}

export type FrameHandle = number;

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

/** The sheet's hooks around open and close. */
export interface SheetCoreOptions {
  initialFocus?: () => HTMLElement | null;
  /** Runs before `dropdown:show`. */
  beforeShow?: () => void;
  /** Runs before `dropdown:hide`. */
  beforeHide?: () => void;
  /** Runs after `dropdown:hide`. */
  afterHide?: () => void;
  /** The `dropdown:hide` event's detail. */
  hideDetail?: () => DropdownHideDetail;
  /** Native cancel: Escape, back gesture. Default: dismiss. */
  cancel?: () => void;
  /** × and the backdrop. Default: close. */
  dismiss?: () => void;
  /** Set while the sheet is a level of the sheet below. */
  levelOf?: () => LevelPlacement | null;
}

export interface SheetCore {
  /** False unless this call opened it. */
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
  const panel = dialog.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.panel}]`);
  if (!panel) {
    throw new TypeError(`A bottom sheet requires [${SHEET_ATTRIBUTES.panel}].`);
  }

  let entered = false;
  let openFrame: FrameHandle | null = null;
  let cancelPendingLeave: CancelLeave | null = null;

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
    cancelPendingLeave?.();
    cancelPendingLeave = null;
    entered = false;
  };

  const modal = attachModal(dialog, {
    host,
    initialFocus: () =>
      options.initialFocus?.() ??
      dialog.querySelector<HTMLElement>(`[${MODAL_ATTRIBUTES.dismiss}]`),
    leave: (finish) => {
      cancelOpenFrame();
      render();
      const level = options.levelOf?.() ?? null;
      cancelPendingLeave = level
        ? popLevel(dialog, level.below, finish)
        : holdLeave(dialog, "slow-exit", finish);
    },
    cancel: options.cancel,
    dismiss: options.dismiss,
    onClosed: () => {
      clearMotion();
      clearLevel(dialog);
      try {
        options.beforeHide?.();
      } finally {
        // Listeners wait on it, whatever threw.
        render();
        dispatchHide(host, options.hideDetail?.());
      }
      options.afterHide?.();
    },
  });
  render();

  const open = (opener?: HTMLElement): boolean => {
    if (modal.state() !== "closed") return false;
    if (!modal.open(opener)) return false;
    try {
      options.beforeShow?.();
    } catch (error) {
      // No open sheet without its show.
      modal.close();
      throw error;
    }
    const level = options.levelOf?.() ?? null;
    if (level) {
      // A level's push is its entry; no slide-up follows.
      entered = true;
      pushLevel(dialog, level.below, level.belowTitle);
    } else {
      openFrame = window.requestAnimationFrame(() => {
        openFrame = null;
        entered = true;
        render();
      });
    }
    render();
    host.dispatchEvent(new CustomEvent("dropdown:show", { bubbles: true }));
    return true;
  };

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

  const open = (opener?: HTMLElement): void => {
    if (sheet.isOpen()) return;
    // A hidden trigger: the sheet is unavailable.
    if (!isReachable(toggle)) return;
    // Safari does not focus a clicked button.
    sheet.open(opener ?? toggle);
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
