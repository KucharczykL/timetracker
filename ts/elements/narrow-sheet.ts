/** A dropdown panel becomes a sheet when narrow.
 *
 * One panel node moves between hosts.
 * CSS alone holds the breakpoint.
 */
import { SHEET_ATTRIBUTES, SHEET_HOST_VALUE } from "../generated/sheet-attributes.js";
import { reportClientError } from "../client-errors.js";
import type { MenuController } from "./menu-behavior.js";
import { attachSheetCore, type FrameHandle } from "./sheet-controller.js";
import { releaseFromTopLayer, returnToTopLayer } from "./surface-stack.js";

export interface NarrowSheetOptions {
  dialog: HTMLDialogElement;
  sentinel: HTMLElement;
  /** Its `aria-expanded` follows the sheet. */
  expandedToggle?: HTMLElement;
  sheetFocus?: (menu: HTMLElement) => HTMLElement | null;
}

/** Where a lent panel returns. */
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

  let state: SwitchState = { kind: "closed" };
  let frame: FrameHandle | null = null;

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
    if (next && next.parentNode === parent) parent.insertBefore(menu, next);
    else parent.appendChild(menu);
    returnToTopLayer(menu);
    menu.removeAttribute(SHEET_ATTRIBUTES.host);
  };

  const sheet = attachSheetCore(host, dialog, {
    initialFocus: () => options.sheetFocus?.(menu) ?? null,
    beforeShow: () => setExpanded(true),
    beforeHide: () => {
      const place = lentPlace();
      if (place) returnPanel(place);
      state = state.kind === "moving" ? { ...state, place: null } : { kind: "closed" };
      setExpanded(false);
    },
  });

  const openSheet = (opener: HTMLElement | undefined): void => {
    const parent = menu.parentNode;
    if (!parent) {
      reportClientError("narrow-sheet", "a detached panel cannot open", {
        toast: false,
      });
      return;
    }
    const place: PanelPlace = { parent, next: menu.nextSibling };
    state = { kind: "sheet", opener, place };
    let opened = false;
    try {
      body.appendChild(menu);
      releaseFromTopLayer(menu);
      menu.setAttribute(SHEET_ATTRIBUTES.host, SHEET_HOST_VALUE);
      opened = sheet.open(opener);
    } finally {
      // A refused open drops the tap.
      if (!opened) {
        returnPanel(place);
        state = { kind: "closed" };
      }
    }
  };

  /** True when a host opened. */
  const present = (opener: HTMLElement | undefined): boolean => {
    if (isNarrow()) openSheet(opener);
    else {
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
    if (present(opener)) window.addEventListener("resize", queueCheck);
  };

  const close = (): void => {
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
