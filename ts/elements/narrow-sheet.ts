/** A dropdown panel becomes a sheet when narrow.
 *
 * One panel node moves between hosts.
 * CSS alone holds the breakpoint.
 */
import { reportClientError } from "../client-errors.js";
import { SHEET_ATTRIBUTES, SHEET_HOST_VALUE } from "../generated/sheet-attributes.js";
import type { MenuController } from "./menu-behavior.js";
import { isModalLeaving, whenSettled } from "./modal-layer.js";
import { attachSheetCore, type FrameHandle } from "./sheet-controller.js";
import { releaseFromTopLayer, returnToTopLayer } from "./surface-stack.js";

export interface NarrowSheetOptions {
  dialog: HTMLDialogElement;
  sentinel: HTMLElement;
  /** Its `aria-expanded` follows the sheet. */
  expandedToggle?: HTMLElement;
  sheetFocus?: (menu: HTMLElement) => HTMLElement | null;
  /** Node the sheet holds; default: menu. */
  lent?: HTMLElement;
  /** Focus return when no opener is stated. */
  opener?: () => HTMLElement | null;
}

type CssValue = string; // e.g. "12px"

/** Where a lent node returns. */
interface PanelPlace {
  parent: ParentNode & Node;
  next: Node | null;
}

/** One host at a time, or a move between. */
type SwitchState =
  | { kind: "closed" }
  | { kind: "anchored"; opener?: HTMLElement }
  | { kind: "sheet"; opener?: HTMLElement; place: PanelPlace }
  | { kind: "moving"; opener?: HTMLElement; place: PanelPlace | null };

let sheetTitleCounter = 0;

/** Clones carry no id; stamp per instance. */
function nameSheet(dialog: HTMLDialogElement): void {
  const title = dialog.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.title}]`);
  if (!title) {
    throw new TypeError(`A dropdown sheet requires [${SHEET_ATTRIBUTES.title}].`);
  }
  sheetTitleCounter += 1;
  title.id = `dropdown-sheet-title-${sheetTitleCounter}`;
  dialog.setAttribute("aria-labelledby", title.id);
}

export function attachNarrowSheet(
  host: HTMLElement,
  menu: HTMLElement,
  anchored: MenuController,
  options: NarrowSheetOptions,
): MenuController {
  const { dialog, sentinel } = options;
  const body = dialog.querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.body}]`);
  if (!body) {
    throw new TypeError(`A dropdown sheet requires [${SHEET_ATTRIBUTES.body}].`);
  }
  nameSheet(dialog);

  const lent = options.lent ?? menu;
  let state: SwitchState = { kind: "closed" };
  let frame: FrameHandle | null = null;
  let viewportFrame: FrameHandle | null = null;
  let retry: object | null = null;

  const isNarrow = (): boolean => sentinel.getClientRects().length > 0;
  const setExpanded = (expanded: boolean): void =>
    options.expandedToggle?.setAttribute("aria-expanded", String(expanded));

  const isOpen = (): boolean => anchored.isOpen() || sheet.isOpen();

  const lentPlace = (): PanelPlace | null =>
    state.kind === "sheet" || state.kind === "moving" ? state.place : null;

  const returnPanel = (place: PanelPlace): void => {
    const { parent, next } = place;
    if (!parent.isConnected) {
      reportClientError("narrow-sheet", "the panel's home left the page", {
        toast: false,
      });
    }
    if (next && next.parentNode === parent) parent.insertBefore(lent, next);
    else parent.appendChild(lent);
    returnToTopLayer(menu);
    // Removed after the move; blurs read it.
    menu.removeAttribute(SHEET_ATTRIBUTES.host);
    lent.removeAttribute(SHEET_ATTRIBUTES.host);
  };

  const pixels = (value: number): CssValue => `${Math.max(0, Math.round(value))}px`;

  const measureViewport = (): void => {
    viewportFrame = null;
    const viewport = window.visualViewport;
    if (!viewport) return;
    const bottom = viewport.offsetTop + viewport.height;
    dialog.style.setProperty("--sheet-keyboard-inset", pixels(window.innerHeight - bottom));
    dialog.style.setProperty("--sheet-visible-height", pixels(viewport.height));
  };

  const queueMeasure = (): void => {
    if (viewportFrame === null) viewportFrame = window.requestAnimationFrame(measureViewport);
  };

  const watchViewport = (): void => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    viewport.addEventListener("resize", queueMeasure);
    viewport.addEventListener("scroll", queueMeasure);
    measureViewport();
  };

  const unwatchViewport = (): void => {
    window.visualViewport?.removeEventListener("resize", queueMeasure);
    window.visualViewport?.removeEventListener("scroll", queueMeasure);
    if (viewportFrame !== null) window.cancelAnimationFrame(viewportFrame);
    viewportFrame = null;
    dialog.style.removeProperty("--sheet-keyboard-inset");
    dialog.style.removeProperty("--sheet-visible-height");
  };

  const sheet = attachSheetCore(host, dialog, {
    initialFocus: () => options.sheetFocus?.(menu) ?? null,
    beforeShow: () => {
      setExpanded(true);
      watchViewport();
    },
    beforeHide: () => {
      unwatchViewport();
      const place = lentPlace();
      if (place) returnPanel(place);
      state = state.kind === "moving" ? { ...state, place: null } : { kind: "closed" };
      setExpanded(false);
    },
  });

  /** False when refused. */
  const openSheet = (stated: HTMLElement | undefined): boolean => {
    const opener = stated ?? options.opener?.() ?? undefined;
    const parent = lent.parentNode;
    if (!parent) {
      reportClientError("narrow-sheet", "a detached panel cannot open", {
        toast: false,
      });
      return false;
    }
    const place: PanelPlace = { parent, next: lent.nextSibling };
    state = { kind: "sheet", opener, place };
    let opened = false;
    try {
      // Stamped before the move; blurs read it.
      lent.setAttribute(SHEET_ATTRIBUTES.host, SHEET_HOST_VALUE);
      menu.setAttribute(SHEET_ATTRIBUTES.host, SHEET_HOST_VALUE);
      body.appendChild(lent);
      releaseFromTopLayer(menu);
      opened = sheet.open(opener);
    } finally {
      // A refused open drops the tap.
      if (!opened) {
        returnPanel(place);
        state = { kind: "closed" };
      }
    }
    return opened;
  };

  /** True when a host opened. */
  const present = (opener: HTMLElement | undefined): boolean => {
    if (isNarrow()) {
      if (!openSheet(opener) && isModalLeaving()) retryOnSettle(opener);
    } else {
      anchored.open(opener);
      state = anchored.isOpen() ? { kind: "anchored", opener } : { kind: "closed" };
    }
    return isOpen();
  };

  const checkHost = (): void => {
    frame = null;
    if (state.kind !== "anchored" && state.kind !== "sheet") return;
    const inSheet = state.kind === "sheet";
    if (isNarrow() === inSheet) return;
    state = { kind: "moving", opener: state.opener, place: lentPlace() };
    if (inSheet) sheet.close();
    else anchored.close();
  };

  const queueCheck = (): void => {
    if (frame === null) frame = window.requestAnimationFrame(checkHost);
  };

  const unwatch = (): void => {
    window.removeEventListener("resize", queueCheck);
    if (frame !== null) window.cancelAnimationFrame(frame);
    frame = null;
  };

  host.addEventListener("dropdown:hide", (event) => {
    // Nested dropdowns bubble theirs.
    if (event.target !== host) return;
    if (state.kind !== "moving") {
      state = { kind: "closed" };
      unwatch();
      return;
    }
    if (!present(state.opener)) unwatch();
  });

  const open = (opener?: HTMLElement): void => {
    // Open, or lent and leaving.
    if (state.kind !== "closed") return;
    retry = null;
    if (present(opener)) window.addEventListener("resize", queueCheck);
  };

  // A tap during another sheet's leave.
  function retryOnSettle(opener: HTMLElement | undefined): void {
    const token = {};
    retry = token;
    whenSettled(() => {
      if (retry !== token || state.kind !== "closed") return;
      retry = null;
      if (isNarrow() && openSheet(opener)) window.addEventListener("resize", queueCheck);
    });
  }

  const close = (): void => {
    retry = null;
    // A close cancels a pending move.
    if (state.kind === "moving") {
      state = state.place
        ? { kind: "sheet", opener: state.opener, place: state.place }
        : { kind: "closed" };
    }
    anchored.close();
    sheet.close();
  };

  return {
    open,
    close,
    isOpen,
    focusFirst: () => (sheet.isOpen() ? sheet.focusFirst() : anchored.focusFirst()),
  };
}
