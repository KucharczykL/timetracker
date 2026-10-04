/** Modal bottom-sheet controller for the generic <drop-down> shell.
 *
 * The modal layer owns modality, focus, dismissal and the scroll lock.
 * This controller adds the slide, aria-expanded, the dropdown lifecycle
 * events and the close-then-navigate section-link path.
 */
import type { MenuController } from "./menu-behavior.js";
import { attachModal } from "./modal-layer.js";

type SheetState = "closed" | "opening" | "open" | "closing";

interface PendingNavigation {
  hash: string;
  destination: HTMLElement;
  focusTarget: HTMLElement;
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

  let state: SheetState = "closed";
  let closeTimer = 0;
  let openFrame = 0;
  let finishLeave: (() => void) | null = null;
  let pendingNavigation: PendingNavigation | null = null;

  const setState = (next: SheetState): void => {
    state = next;
    dialog.dataset.sheetState = next;
  };

  const clearMotion = (): void => {
    window.cancelAnimationFrame(openFrame);
    openFrame = 0;
    window.clearTimeout(closeTimer);
    closeTimer = 0;
    finishLeave = null;
  };
  setState("closed");

  const modal = attachModal(dialog, {
    host,
    // The native steps would pick the header's close button.
    initialFocus: () =>
      dialog.querySelector<HTMLElement>("nav a[href]") ??
      dialog.querySelector<HTMLElement>("[data-modal-dismiss]"),
    leave: (finish) => {
      if (prefersReducedMotion()) return false;
      window.cancelAnimationFrame(openFrame);
      setState("closing");
      finishLeave = finish;
      closeTimer = window.setTimeout(finish, CLOSE_FALLBACK_MS);
      return true;
    },
    onClosed: () => {
      const navigation = pendingNavigation;
      pendingNavigation = null;
      clearMotion();
      toggle.setAttribute("aria-expanded", "false");
      setState("closed");
      host.dispatchEvent(new CustomEvent("dropdown:hide", { bubbles: true }));
      if (navigation) navigateTo(navigation);
    },
  });

  const open = (): void => {
    if (state !== "closed") return;
    // A hidden trigger means the sheet is unavailable.
    if (!host.isConnected || toggle.closest("[hidden], [inert]")) return;
    // Safari does not focus a clicked button.
    if (!modal.open(toggle)) return;
    toggle.setAttribute("aria-expanded", "true");
    setState("opening");
    host.dispatchEvent(new CustomEvent("dropdown:show", { bubbles: true }));
    openFrame = window.requestAnimationFrame(() => {
      openFrame = 0;
      if (state === "opening") setState("open");
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
    if (
      state === "closing" &&
      event.target === panel &&
      event.propertyName === "transform"
    ) {
      finishLeave?.();
    }
  });

  return { open, close, isOpen, focusFirst: () => modal.focusInitial() };
}
