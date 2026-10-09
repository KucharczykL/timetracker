/** A dropdown panel becomes a sheet when narrow.
 *
 * One panel node moves between hosts.
 * CSS alone holds the breakpoint.
 */
import { reportClientError } from "../client-errors.js";
import { SHEET_ATTRIBUTES, SHEET_HOST_VALUE } from "../generated/sheet-attributes.js";
import type { MenuController } from "./menu-behavior.js";
import { closeTogether, type CancelSettled, isModalLeaving, whenSettled } from "./modal-layer.js";
import { attachSheetCore, type FrameHandle } from "./sheet-controller.js";
import { bottomSheet, enclosingSheet, type LevelPlacement } from "./sheet-levels.js";
import { clearAnchoredPosition } from "./anchored-position.js";
import { releaseFromTopLayer, returnToTopLayer } from "./surface-stack.js";

//: Content that opens a level or filters.
const STEADY_CONTENT_SELECTOR = "drop-down, [data-search-select-search]";

export interface NarrowSheetOptions {
  dialog: HTMLDialogElement;
  sentinel: HTMLElement;
  /** Its `aria-expanded` follows the sheet. */
  expandedToggle?: HTMLElement;
  sheetFocus?: (menu: HTMLElement) => HTMLElement | null;
  /** Holds the menu; default: the menu. */
  lent?: HTMLElement;
  /** Focus return when no opener is stated. */
  defaultOpener?: () => HTMLElement | null;
}

type CssValue = string; // e.g. "12px"

/** Where a lent node returns. */
interface LentPlace {
  parent: ParentNode & Node;
  next: Node | null;
}

/** One host at a time, or a move between. */
type SwitchState =
  | { kind: "closed" }
  | { kind: "anchored"; opener?: HTMLElement }
  | { kind: "sheet"; opener?: HTMLElement; place: LentPlace }
  | { kind: "moving"; opener?: HTMLElement; from: MoveOrigin };

/** The host a move left; a sheet's place empties once returned. */
type MoveOrigin = { host: "sheet"; place: LentPlace | null } | { host: "anchored" };

let sheetTitleCounter = 0;

function titleOf(sheet: HTMLDialogElement): string {
  return sheet.querySelector(`[${SHEET_ATTRIBUTES.title}]`)?.textContent?.trim() ?? "";
}

/** A menu item that acts, not one that opens a submenu. */
const ACTING_ITEM_SELECTOR = `[role="menuitem"]:not([aria-haspopup])`;

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
  if (!lent.contains(menu)) {
    throw new TypeError("A lent node must hold the menu.");
  }
  let state: SwitchState = { kind: "closed" };
  let frame: FrameHandle | null = null;
  let viewportFrame: FrameHandle | null = null;
  let cancelRetry: CancelSettled | null = null;
  /** The sheet below, while this host opened as its level. */
  let levelBelow: HTMLDialogElement | null = null;

  const isNarrow = (): boolean => sentinel.getClientRects().length > 0;
  const setExpanded = (expanded: boolean): void =>
    options.expandedToggle?.setAttribute("aria-expanded", String(expanded));

  const isOpen = (): boolean => anchored.isOpen() || sheet.isOpen();

  const lentPlace = (): LentPlace | null => {
    if (state.kind === "sheet") return state.place;
    if (state.kind === "moving" && state.from.host === "sheet") return state.from.place;
    return null;
  };

  const returnLent = (place: LentPlace): void => {
    const { parent, next } = place;
    if (!parent.isConnected) {
      reportClientError("narrow-sheet", "the lent node's home left the page", {
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

  const levelOf = (): LevelPlacement | null =>
    levelBelow ? { below: levelBelow, belowTitle: titleOf(levelBelow) } : null;
  // A level's × and backdrop close the whole chain; Escape only itself.
  const dismissSheet = (): void => {
    if (levelBelow) closeTogether(bottomSheet(dialog));
    else sheet.close();
  };

  const sheet = attachSheetCore(host, dialog, {
    initialFocus: () => options.sheetFocus?.(menu) ?? null,
    cancel: () => sheet.close(),
    dismiss: dismissSheet,
    levelOf,
    beforeShow: () => {
      setExpanded(true);
      watchViewport();
    },
    beforeHide: () => {
      unwatchViewport();
      const place = lentPlace();
      levelBelow = null;
      try {
        if (place) returnLent(place);
      } finally {
        //: A failed return must not wedge it.
        if (state.kind !== "moving") {
          state = { kind: "closed" };
        } else if (state.from.host === "sheet") {
          state = { ...state, from: { host: "sheet", place: null } };
        }
        setExpanded(false);
      }
    },
    hideDetail: () => ({ moving: state.kind === "moving" }),
  });

  dialog
    .querySelector<HTMLElement>(`[${SHEET_ATTRIBUTES.back}]`)
    ?.addEventListener("click", () => sheet.close());
  // Capture: the close runs before the item's own click handler.
  dialog.addEventListener(
    "click",
    (event) => {
      if (!levelBelow) return;
      const item = (event.target as Element).closest(ACTING_ITEM_SELECTOR);
      if (!item || item.closest("dialog") !== dialog) return;
      closeTogether(bottomSheet(dialog));
    },
    { capture: true },
  );

  /** False when it did not open. */
  const openSheet = (stated: HTMLElement | undefined): boolean => {
    const opener = stated ?? options.defaultOpener?.() ?? undefined;
    const parent = lent.parentNode;
    if (!parent) {
      reportClientError("narrow-sheet", "a detached lent node cannot open", {
        toast: false,
      });
      return false;
    }
    const place: LentPlace = { parent, next: lent.nextSibling };
    state = { kind: "sheet", opener, place };
    levelBelow = enclosingSheet(host);
    let opened = false;
    try {
      // Stamped before the move; blurs read it.
      lent.setAttribute(SHEET_ATTRIBUTES.host, SHEET_HOST_VALUE);
      menu.setAttribute(SHEET_ATTRIBUTES.host, SHEET_HOST_VALUE);
      body.appendChild(lent);
      // Room for a level or a search: one height.
      dialog.toggleAttribute(
        SHEET_ATTRIBUTES.steady,
        levelBelow !== null || lent.querySelector(STEADY_CONTENT_SELECTOR) !== null,
      );
      // A leave the release cancelled never clears the anchored geometry.
      clearAnchoredPosition(menu);
      releaseFromTopLayer(menu);
      opened = sheet.open(opener);
    } finally {
      // A refused open drops the tap.
      if (!opened) {
        levelBelow = null;
        returnLent(place);
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
    // A level stays put; its first sheet's close closes it.
    if (levelBelow) return;
    if (state.kind !== "anchored" && state.kind !== "sheet") return;
    const inSheet = state.kind === "sheet";
    if (isNarrow() === inSheet) return;
    const from: MoveOrigin =
      state.kind === "sheet" ? { host: "sheet", place: state.place } : { host: "anchored" };
    state = { kind: "moving", opener: state.opener, from };
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
    const { opener } = state;
    const fromSheet = state.from.host === "sheet";
    //: The other host may hide it.
    const shown = opener && opener.getClientRects().length > 0 ? opener : undefined;
    if (!present(shown)) {
      unwatch();
      return;
    }
    //: The sheet's focus returned to a hidden opener.
    if (fromSheet && anchored.isOpen()) {
      options.sheetFocus?.(menu)?.focus({ preventScroll: true });
    }
  });

  const open = (opener?: HTMLElement): void => {
    // Open, or lent and leaving.
    if (state.kind !== "closed") return;
    dropRetry();
    if (present(opener)) window.addEventListener("resize", queueCheck);
  };

  function dropRetry(): void {
    cancelRetry?.();
    cancelRetry = null;
  }

  // A tap during another sheet's leave.
  function retryOnSettle(opener: HTMLElement | undefined): void {
    dropRetry();
    cancelRetry = whenSettled(() => {
      cancelRetry = null;
      if (state.kind !== "closed") return;
      if (!isNarrow()) {
        //: Widened during the leave: open anchored.
        if (!present(opener)) {
          reportClientError("narrow-sheet", "a retried anchored open was refused", {
            toast: false,
          });
          return;
        }
      } else if (!openSheet(opener)) {
        reportClientError("narrow-sheet", "a retried open was refused again", {
          toast: false,
        });
        return;
      }
      if (isOpen()) window.addEventListener("resize", queueCheck);
    });
  }

  const close = (): void => {
    dropRetry();
    // A close cancels a pending move.
    if (state.kind === "moving") {
      const place = lentPlace();
      state = place
        ? { kind: "sheet", opener: state.opener, place }
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
