// Shared positioning/keyboard core for light-DOM dropdowns: viewport-aware
// positioning, instant open/close (no animation — by design), ARIA wiring, full
// keyboard navigation, and single-open coordination. Driven by the generic
// <drop-down> element; type-specific wiring lives in the registered behaviors
// (menu, select). The bottom-* panel geometry is the shared positionAnchored
// (also used by the pop-over tooltip); the right-start submenu keeps its own.
import { type Align, positionAnchored, VIEWPORT_MARGIN } from "./anchored-position.js";

export type MenuPlacement =
  | "bottom-start"
  | "bottom-center"
  | "bottom-end"
  | "right-start";

export interface MenuOptions {
  // Where the menu opens relative to its toggle. Defaults to "bottom-start".
  placement?: MenuPlacement;
  // Which descendants count as navigable items. Defaults to the menuitem roles;
  // the PATCH selectors pass "[data-option]" (their options carry no role).
  itemSelector?: string;
  // Force the menu's width to match the toggle's (the value-selectors want this;
  // content-width menus like the navbar/played-row do not). Honored for the
  // bottom-start/right-start branch (not bottom-end/bottom-center).
  matchToggleWidth?: boolean;
  // A submenu opens (idempotently) on click instead of toggling — it is already
  // hover-opened on mouse, so a click must not toggle it closed.
  submenu?: boolean;
  // Element whose edges anchor the menu *horizontally* (right-start only),
  // instead of the toggle. A submenu passes its parent panel so the flyout sits
  // flush at the panel's edge regardless of the toggle row's padding/margin —
  // the toggle still anchors the *vertical* position (it aligns with the hovered
  // row). Defaults to the toggle.
  horizontalAnchor?: HTMLElement;
}

export interface MenuController {
  open: () => void;
  close: () => void;
  isOpen: () => boolean;
  focusFirst: () => void;
  // Attaches the document-level listeners (outside-click close, single-open
  // coordination) and returns their detacher. Called once per connection by
  // <drop-down>: element-local wiring persists with the subtree across DOM
  // moves, so reconnection re-binds only what disconnection removed.
  bindDocument: () => () => void;
}

// A hairline gap between a submenu flyout and its parent panel edge. Purely
// aesthetic: flush edges read as one merged surface; 1px of daylight makes the
// flyout legible as a distinct, layered panel without looking detached.
const SUBMENU_GAP = 1;
const OPEN_MENUS_EVENT = "dropdown-menu:open";
const TYPEAHEAD_RESET_MS = 500;

interface OpenMenuDetail {
  host: HTMLElement;
}

// Wires open/close + positioning + keyboard nav for one toggle/menu pair living
// inside `host`. Returns a small controller so callers (e.g. submenus) can drive
// it. Opening is instant; there is intentionally no transition.
export function attachMenu(
  host: HTMLElement,
  toggle: HTMLElement,
  menu: HTMLElement,
  options: MenuOptions = {},
): MenuController {
  const placement = options.placement ?? "bottom-start";
  const itemSelector =
    options.itemSelector ??
    '[role="menuitem"], [role="menuitemcheckbox"], [role="menuitemradio"]';
  const matchToggleWidth = options.matchToggleWidth ?? false;
  const isSubmenu = options.submenu ?? false;
  const horizontalAnchor = options.horizontalAnchor ?? toggle;

  // Items of *this* menu only — never those of a nested submenu (whose closest
  // [data-menu] is its own panel, not ours). Keeps roving/typeahead from
  // wandering into a submenu's hidden rows.
  const enabledItems = (): HTMLElement[] =>
    Array.from(menu.querySelectorAll<HTMLElement>(itemSelector)).filter(
      (item) =>
        item.closest("[data-menu]") === menu &&
        item.getAttribute("aria-disabled") !== "true" &&
        !item.hasAttribute("disabled"),
    );

  // bottom-* placements share the generic positionAnchored (with the tooltip);
  // the right-start submenu flyout has its own anchor/first-item geometry below.
  const positionMenu = (): void => {
    if (placement === "right-start") {
      positionSubmenu();
      return;
    }
    const align: Align =
      placement === "bottom-end"
        ? "end"
        : placement === "bottom-center"
          ? "center"
          : "start";
    positionAnchored(toggle, menu, {
      align,
      side: "bottom",
      gap: 0,
      // matchToggleWidth applies only to bottom-start.
      matchWidth: matchToggleWidth && align === "start",
      scrollable: true,
    });
  };

  // The submenu flyout (right-start): the horizontal anchor (its parent panel
  // edge) governs left/right and the flip decision; the toggle governs the
  // vertical position so the flyout lines up with the hovered row. This geometry
  // is submenu-specific (first-item alignment, SUBMENU_GAP), so it stays here
  // rather than in the shared positioner.
  const positionSubmenu = (): void => {
    const rect = toggle.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.overflowY = "auto";
    menu.style.right = "auto";
    menu.style.bottom = "auto";

    // A transformed/filtered ancestor (e.g. a nested submenu's backdrop-blur
    // parent panel) becomes the containing block for `position: fixed`, so fixed
    // coords are relative to it, not the viewport. Pin to (0,0) to measure that
    // origin, then convert viewport coords by subtracting it.
    menu.style.left = "0px";
    menu.style.top = "0px";
    const origin = menu.getBoundingClientRect();

    const clampLeft = (left: number): number =>
      Math.max(
        VIEWPORT_MARGIN,
        Math.min(left, window.innerWidth - menu.offsetWidth - VIEWPORT_MARGIN),
      );
    const setLeft = (viewportLeft: number): void => {
      menu.style.left = `${clampLeft(viewportLeft) - origin.x}px`;
    };
    const setTop = (viewportTop: number): void => {
      menu.style.top = `${viewportTop - origin.y}px`;
    };

    const anchor = horizontalAnchor.getBoundingClientRect();
    // Align the flyout's FIRST ITEM with the toggle row, not the panel's
    // border-box top — the panel's own top padding/border would otherwise push
    // the first row down by that amount. Measured from the live layout, so it
    // tracks any padding/border/header change instead of a hardcoded offset.
    const items = enabledItems();
    const firstItemInset = items.length
      ? items[0].getBoundingClientRect().top - origin.y
      : 0;
    const menuWidth = menu.offsetWidth;
    const spaceRight = window.innerWidth - anchor.right - VIEWPORT_MARGIN;
    const openLeft = menuWidth > spaceRight && anchor.left - VIEWPORT_MARGIN > spaceRight;
    menu.style.maxHeight = `${Math.max(0, window.innerHeight - rect.top - VIEWPORT_MARGIN)}px`;
    // SUBMENU_GAP of daylight on whichever side the flyout opens.
    setLeft(
      openLeft ? anchor.left - menuWidth - SUBMENU_GAP : anchor.right + SUBMENU_GAP,
    );
    setTop(rect.top - firstItemInset);
  };

  const clearPosition = (): void => {
    for (const property of [
      "position",
      "top",
      "bottom",
      "left",
      "right",
      "width",
      "min-width",
      "max-height",
      "overflow-y",
    ]) {
      menu.style.removeProperty(property);
    }
  };

  const reposition = (): void => {
    if (!menu.hidden) positionMenu();
  };

  const isOpen = (): boolean => !menu.hidden;

  const setActive = (index: number): void => {
    const items = enabledItems();
    if (items.length === 0) return;
    const clamped = (index + items.length) % items.length;
    items.forEach((item, position) => {
      item.tabIndex = position === clamped ? 0 : -1;
    });
    items[clamped].focus();
  };

  const focusFirst = (): void => setActive(0);

  const open = (): void => {
    if (isOpen()) return;
    // Pin to `fixed` BEFORE unhiding. The panel class is `absolute`; if it became
    // visible while still absolute it would join an ancestor scroll container's
    // overflow (the parent menu), spawn a transient scrollbar, and shift the
    // toggle we then measure — mis-anchoring a submenu opened from a low row.
    menu.style.position = "fixed";
    menu.hidden = false;
    positionMenu();
    toggle.setAttribute("aria-expanded", "true");
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    document.dispatchEvent(
      new CustomEvent<OpenMenuDetail>(OPEN_MENUS_EVENT, { detail: { host } }),
    );
    // Lifecycle seam for future consumers: behaviors or htmx (hx-on:dropdown:show)
    // can observe visibility here instead of via a JS callback. These bubble, so a
    // submenu open also fires dropdown:show on its ancestor <drop-down>s.
    host.dispatchEvent(new CustomEvent("dropdown:show", { bubbles: true }));
  };

  const close = (): void => {
    if (!isOpen()) return;
    menu.hidden = true;
    clearPosition();
    toggle.setAttribute("aria-expanded", "false");
    window.removeEventListener("scroll", reposition, true);
    window.removeEventListener("resize", reposition);
    host.dispatchEvent(new CustomEvent("dropdown:hide", { bubbles: true }));
  };

  const toggleChecked = (item: HTMLElement): void => {
    item.setAttribute(
      "aria-checked",
      item.getAttribute("aria-checked") === "true" ? "false" : "true",
    );
  };

  // Keyboard activation: submenu triggers open without closing the parent;
  // checkbox/radio items stay open; plain items close and refocus the toggle.
  const activate = (item: HTMLElement): void => {
    item.click();
    if (item.getAttribute("aria-haspopup")) return;
    const role = item.getAttribute("role");
    if (role !== "menuitemcheckbox" && role !== "menuitemradio") {
      close();
      toggle.focus();
    }
  };

  let typeaheadBuffer = "";
  let typeaheadTimer = 0;
  const typeahead = (character: string, fromIndex: number): void => {
    const items = enabledItems();
    if (items.length === 0) return;
    window.clearTimeout(typeaheadTimer);
    typeaheadBuffer += character.toLowerCase();
    typeaheadTimer = window.setTimeout(() => {
      typeaheadBuffer = "";
    }, TYPEAHEAD_RESET_MS);
    for (let offset = 1; offset <= items.length; offset++) {
      const index = (fromIndex + offset) % items.length;
      const text = (items[index].textContent ?? "").trim().toLowerCase();
      if (text.startsWith(typeaheadBuffer)) {
        setActive(index);
        return;
      }
    }
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    // Keyboard/synthetic clicks (Enter/Space, or activate()'s item.click()) report
    // detail === 0 and focus the first item; a real mouse click (detail >= 1) opens
    // without grabbing focus so hover drives the single highlight. A submenu opens
    // idempotently (hover-opened on mouse, so the click must not toggle it closed).
    const fromKeyboard = event.detail === 0;
    if (isSubmenu || !isOpen()) {
      open();
      if (fromKeyboard) setActive(0);
    } else {
      close();
    }
  });

  toggle.addEventListener("keydown", (event) => {
    // Arrow open/roving applies to a top-level toggle only. A submenu toggle is a
    // menuitem in its parent menu, so ArrowDown/Up must bubble up to the parent's
    // roving (it opens via ArrowRight / Enter — handled elsewhere), not open here.
    if (!isSubmenu && event.key === "ArrowDown") {
      event.preventDefault();
      if (!isOpen()) open();
      setActive(0);
    } else if (!isSubmenu && event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen()) open();
      setActive(-1);
    } else if (event.key === "Escape") {
      close();
    }
  });

  menu.addEventListener("keydown", (event) => {
    // Let a nested submenu handle its own keys (the event bubbles up to us).
    if ((event.target as HTMLElement).closest("[data-menu]") !== menu) return;
    const items = enabledItems();
    // An itemless menu (e.g. the combobox behavior's panel, whose inner widget
    // owns its own keyboard navigation) must not swallow arrow/Home/End — they
    // would preventDefault caret movement inside an inner input. Escape and Tab
    // still close below.
    if (items.length === 0 && event.key !== "Escape" && event.key !== "Tab") return;
    const currentIndex = items.findIndex((item) => item === document.activeElement);
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setActive(currentIndex + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        setActive(currentIndex - 1);
        break;
      case "Home":
        event.preventDefault();
        setActive(0);
        break;
      case "End":
        event.preventDefault();
        setActive(items.length - 1);
        break;
      case "Escape":
        event.preventDefault();
        close();
        toggle.focus();
        break;
      case "Tab":
        close();
        break;
      case "Enter":
      case " ": {
        const active = items[currentIndex];
        if (active) {
          event.preventDefault();
          activate(active);
        }
        break;
      }
      default:
        if (event.key.length === 1 && /\S/.test(event.key)) {
          typeahead(event.key, currentIndex);
        }
    }
  });

  // Mouse hover drives the active item, so the highlight follows the cursor and
  // only one item is ever highlighted (own items only — not a nested submenu's).
  menu.addEventListener("pointerover", (event) => {
    if (event.pointerType !== "mouse") return;
    const item = (event.target as HTMLElement).closest<HTMLElement>(itemSelector);
    if (!item || item.closest("[data-menu]") !== menu) return;
    const index = enabledItems().indexOf(item);
    if (index >= 0) setActive(index);
  });

  // Pointer activation for menu items. Listbox `option`s are owned by the select
  // behavior's own click handler, so ignore them here explicitly — don't rely on
  // that handler's stopPropagation to keep them out of this branch.
  menu.addEventListener("click", (event) => {
    const item = (event.target as HTMLElement).closest<HTMLElement>(itemSelector);
    if (!item || !menu.contains(item)) return;
    const role = item.getAttribute("role");
    if (role === "option") return;
    if (!role || item.getAttribute("aria-haspopup")) return;
    if (role === "menuitemcheckbox" || role === "menuitemradio") {
      toggleChecked(item);
    } else {
      close();
    }
  });

  // Containment must consult composedPath(): it is captured at dispatch time,
  // so a click whose handler synchronously removes its own target (a filter
  // pill's × inside a combobox panel) still counts as inside — by the time
  // this document listener runs, `host.contains(event.target)` is already
  // false for the detached node. The `contains` check stays as fallback for
  // synthetic events dispatched without a path.
  const onDocumentClick = (event: MouseEvent): void => {
    if (!isOpen()) return;
    const path = event.composedPath();
    const inside = path.length
      ? path.includes(host)
      : host.contains(event.target as Node);
    if (!inside) close();
  };

  // Single-open coordination: close when any other (non-ancestor) menu opens.
  const onOtherMenuOpen = (event: Event): void => {
    const detail = (event as CustomEvent<OpenMenuDetail>).detail;
    if (!detail || detail.host === host || host.contains(detail.host)) return;
    close();
  };

  // Bound per connection (see MenuController.bindDocument): unbound
  // document listeners would accumulate across htmx re-mounts or dangle
  // after a permanent removal.
  const bindDocument = (): (() => void) => {
    document.addEventListener("click", onDocumentClick);
    document.addEventListener(OPEN_MENUS_EVENT, onOtherMenuOpen);
    return () => {
      document.removeEventListener("click", onDocumentClick);
      document.removeEventListener(OPEN_MENUS_EVENT, onOtherMenuOpen);
    };
  };

  return { open, close, isOpen, focusFirst, bindDocument };
}
