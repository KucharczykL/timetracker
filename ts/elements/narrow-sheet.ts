/** A dropdown panel opens as a sheet when narrow.
 *
 * One panel node: the sheet borrows it on open and
 * returns it before `dropdown:hide`. The sentinel shows
 * only when narrow; CSS alone holds the breakpoint.
 */
import { DROPDOWN_SHEET_ATTRIBUTES } from "../generated/dropdown-sheet-attributes.js";
import type { MenuController } from "./menu-behavior.js";
import { attachSheetCore } from "./sheet-controller.js";
import { releaseFromTopLayer, returnToTopLayer } from "./surface-stack.js";

export interface NarrowSheetOptions {
  dialog: HTMLDialogElement;
  sentinel: HTMLElement;
  /** Its `aria-expanded` follows the sheet. */
  expandedToggle: HTMLElement | null;
  sheetFocus?: () => HTMLElement | null;
}

interface PanelPlace {
  parent: Node;
  next: Node | null;
}

type FrameHandle = number;

let sheetTitleCounter = 0;

/** Clones carry no id; stamp per instance. */
function nameSheet(dialog: HTMLDialogElement): void {
  const title = dialog.querySelector<HTMLElement>(`[${DROPDOWN_SHEET_ATTRIBUTES.title}]`);
  if (!title) return;
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
  const body = dialog.querySelector<HTMLElement>(`[${DROPDOWN_SHEET_ATTRIBUTES.body}]`);
  if (!body) {
    throw new TypeError(`A dropdown sheet requires [${DROPDOWN_SHEET_ATTRIBUTES.body}].`);
  }
  nameSheet(dialog);

  // Where the panel lives while it is lent.
  let place: PanelPlace | null = null;
  let opener: HTMLElement | undefined;
  let pendingMove = false;
  let watching = false;
  let frame: FrameHandle | null = null;

  const isNarrow = (): boolean => sentinel.getClientRects().length > 0;

  const returnPanel = (): void => {
    if (!place) return;
    const { parent, next } = place;
    place = null;
    if (next && next.parentNode === parent) parent.insertBefore(menu, next);
    else parent.appendChild(menu);
    returnToTopLayer(menu);
    menu.removeAttribute(DROPDOWN_SHEET_ATTRIBUTES.host);
  };

  const sheet = attachSheetCore(host, dialog, {
    initialFocus: () => options.sheetFocus?.() ?? null,
    beforeShow: () => options.expandedToggle?.setAttribute("aria-expanded", "true"),
    beforeHide: () => {
      returnPanel();
      options.expandedToggle?.setAttribute("aria-expanded", "false");
    },
  });

  const openSheet = (openedBy: HTMLElement | undefined): void => {
    place = { parent: menu.parentNode as Node, next: menu.nextSibling };
    body.appendChild(menu);
    releaseFromTopLayer(menu);
    menu.setAttribute(DROPDOWN_SHEET_ATTRIBUTES.host, "sheet");
    let opened = false;
    try {
      opened = sheet.open(openedBy);
    } finally {
      // A refused open drops the tap.
      if (!opened) returnPanel();
    }
  };

  const present = (): void => {
    if (isNarrow()) openSheet(opener);
    else anchored.open(opener);
  };

  const isOpen = (): boolean => anchored.isOpen() || sheet.isOpen();

  const unwatch = (): void => {
    if (!watching) return;
    watching = false;
    window.removeEventListener("resize", queueCheck);
    if (frame !== null) window.cancelAnimationFrame(frame);
    frame = null;
  };

  const checkHost = (): void => {
    frame = null;
    if (pendingMove || !isOpen()) return;
    const inSheet = sheet.isOpen();
    if (isNarrow() === inSheet) return;
    pendingMove = true;
    if (inSheet) sheet.close();
    else anchored.close();
  };

  function queueCheck(): void {
    if (frame === null) frame = window.requestAnimationFrame(checkHost);
  }

  const watch = (): void => {
    if (watching || !isOpen()) return;
    watching = true;
    window.addEventListener("resize", queueCheck);
  };

  host.addEventListener("dropdown:hide", (event) => {
    // Nested dropdowns bubble theirs.
    if (event.target !== host) return;
    if (!pendingMove) {
      unwatch();
      return;
    }
    pendingMove = false;
    present();
    if (!isOpen()) unwatch();
  });

  const open = (openedBy?: HTMLElement): void => {
    // Lent and leaving: nothing to open.
    if (isOpen() || place) return;
    opener = openedBy;
    pendingMove = false;
    present();
    watch();
  };

  const close = (): void => {
    pendingMove = false;
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
