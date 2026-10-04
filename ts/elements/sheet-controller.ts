/** The bottom sheet's slide and lifecycle events. */
import type { MenuController } from "./menu-behavior.js";
import { attachModal, type FinishLeave } from "./modal-layer.js";

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

  let entered = false;
  let openFrame: FrameHandle = 0;
  let pendingLeave: PendingLeave | null = null;
  let pendingNavigation: PendingNavigation | null = null;

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

  const clearMotion = (): void => {
    window.cancelAnimationFrame(openFrame);
    openFrame = 0;
    if (pendingLeave) window.clearTimeout(pendingLeave.timer);
    pendingLeave = null;
    entered = false;
  };

  const modal = attachModal(dialog, {
    host,
    // Native steps would focus the close button.
    initialFocus: () =>
      dialog.querySelector<HTMLElement>("nav a[href]") ??
      dialog.querySelector<HTMLElement>("[data-modal-dismiss]"),
    leave: (finish) => {
      if (prefersReducedMotion()) {
        finish();
        return;
      }
      window.cancelAnimationFrame(openFrame);
      pendingLeave = { finish, timer: window.setTimeout(finish, CLOSE_FALLBACK_MS) };
      render();
    },
    onClosed: () => {
      const navigation = pendingNavigation;
      pendingNavigation = null;
      clearMotion();
      toggle.setAttribute("aria-expanded", "false");
      render();
      host.dispatchEvent(new CustomEvent("dropdown:hide", { bubbles: true }));
      if (navigation) navigateTo(navigation);
    },
  });
  render();

  const open = (): void => {
    if (modal.state() !== "closed") return;
    // A hidden trigger: the sheet is unavailable.
    if (!host.isConnected || toggle.closest("[hidden], [inert]")) return;
    // Safari does not focus a clicked button.
    if (!modal.open(toggle)) return;
    toggle.setAttribute("aria-expanded", "true");
    render();
    host.dispatchEvent(new CustomEvent("dropdown:show", { bubbles: true }));
    openFrame = window.requestAnimationFrame(() => {
      openFrame = 0;
      entered = true;
      render();
    });
  };

  const close = (): void => modal.close();
  const isOpen = (): boolean => modal.isOpen();

  toggle.addEventListener("click", () => (isOpen() ? close() : open()));
  dialog.addEventListener("click", (event) => {
    const clicked = event.target as Element;
    if (clicked.closest("dialog") !== dialog) return;
    const link = clicked.closest<HTMLAnchorElement>("nav a[href]");
    if (!link) return;
    const navigation = sameDocumentDestination(link);
    if (!navigation) return;
    event.preventDefault();
    pendingNavigation = navigation;
    close();
  });
  panel.addEventListener("transitionend", (event) => {
    // Tailwind's translate-y animates translate.
    if (event.target === panel && event.propertyName === "translate") {
      pendingLeave?.finish();
    }
  });

  return { open, close, isOpen, focusFirst: () => modal.focusInitial() };
}
