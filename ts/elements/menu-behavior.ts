// Shared behavior for light-DOM dropdown menus: viewport-aware positioning,
// instant open/close (no animation — by design), ARIA wiring, full keyboard
// navigation, and single-open coordination. Used both by the <dropdown-menu>
// custom element and by the PATCH value-selectors (initDropdown).

export type MenuPlacement = "bottom-start" | "bottom-end" | "right-start";

export interface MenuOptions {
  // Where the menu opens relative to its toggle. Defaults to "bottom-start".
  placement?: MenuPlacement;
  // Which descendants count as navigable items. Defaults to the menuitem roles;
  // the PATCH selectors pass "[data-option]" (their options carry no role).
  itemSelector?: string;
  // Force the menu's width to match the toggle's (the value-selectors want this;
  // content-width menus like the navbar/played-row do not). Bottom-start only.
  matchToggleWidth?: boolean;
}

export interface MenuController {
  open: () => void;
  close: () => void;
  isOpen: () => boolean;
  focusFirst: () => void;
}

const VIEWPORT_MARGIN = 8;
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

  const enabledItems = (): HTMLElement[] =>
    Array.from(menu.querySelectorAll<HTMLElement>(itemSelector)).filter(
      (item) =>
        item.getAttribute("aria-disabled") !== "true" &&
        !item.hasAttribute("disabled"),
    );

  // The menu is positioned `fixed` while open so it escapes any clipping
  // ancestor (e.g. a table's overflow wrapper, issue #39) and flips when there
  // isn't enough room in the preferred direction.
  const positionMenu = (): void => {
    const rect = toggle.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.overflowY = "auto";

    if (placement === "right-start") {
      const menuWidth = menu.offsetWidth;
      const spaceRight = window.innerWidth - rect.right - VIEWPORT_MARGIN;
      const openLeft = menuWidth > spaceRight && rect.left - VIEWPORT_MARGIN > spaceRight;
      menu.style.top = `${rect.top}px`;
      menu.style.bottom = "auto";
      menu.style.left = `${openLeft ? rect.left - menuWidth : rect.right}px`;
      menu.style.maxHeight = `${Math.max(0, window.innerHeight - rect.top - VIEWPORT_MARGIN)}px`;
      return;
    }

    const spaceBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN;
    const spaceAbove = rect.top - VIEWPORT_MARGIN;
    const openUp = menu.scrollHeight > spaceBelow && spaceAbove > spaceBelow;
    menu.style.maxHeight = `${Math.max(0, openUp ? spaceAbove : spaceBelow)}px`;

    if (placement === "bottom-end") {
      // Right-align the menu's right edge with the toggle's, keeping the menu's
      // own width (it is usually wider than a compact toggle).
      menu.style.left = `${Math.max(VIEWPORT_MARGIN, rect.right - menu.offsetWidth)}px`;
    } else {
      menu.style.left = `${rect.left}px`;
      if (matchToggleWidth) menu.style.width = `${rect.width}px`;
    }

    // Set the unused vertical anchor to "auto" (not "") so the inline value wins
    // over any positioning utility class on the menu.
    if (openUp) {
      menu.style.top = "auto";
      menu.style.bottom = `${window.innerHeight - rect.top}px`;
    } else {
      menu.style.bottom = "auto";
      menu.style.top = `${rect.bottom}px`;
    }
  };

  const clearPosition = (): void => {
    for (const property of [
      "position",
      "top",
      "bottom",
      "left",
      "width",
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
    menu.hidden = false;
    positionMenu();
    toggle.setAttribute("aria-expanded", "true");
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    document.dispatchEvent(
      new CustomEvent<OpenMenuDetail>(OPEN_MENUS_EVENT, { detail: { host } }),
    );
  };

  const close = (): void => {
    if (!isOpen()) return;
    menu.hidden = true;
    clearPosition();
    toggle.setAttribute("aria-expanded", "false");
    window.removeEventListener("scroll", reposition, true);
    window.removeEventListener("resize", reposition);
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
    if (isOpen()) {
      close();
    } else {
      open();
      setActive(0);
    }
  });

  toggle.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!isOpen()) open();
      setActive(0);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen()) open();
      setActive(-1);
    } else if (event.key === "Escape") {
      close();
    }
  });

  menu.addEventListener("keydown", (event) => {
    const items = enabledItems();
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

  // Pointer activation for role-bearing items (the PATCH selectors' options have
  // no role and wire their own click handlers, so they are skipped here).
  menu.addEventListener("click", (event) => {
    const item = (event.target as HTMLElement).closest<HTMLElement>(itemSelector);
    if (!item || !menu.contains(item)) return;
    const role = item.getAttribute("role");
    if (!role || item.getAttribute("aria-haspopup")) return;
    if (role === "menuitemcheckbox" || role === "menuitemradio") {
      toggleChecked(item);
    } else {
      close();
    }
  });

  document.addEventListener("click", (event) => {
    if (isOpen() && !host.contains(event.target as Node)) close();
  });

  // Single-open coordination: close when any other (non-ancestor) menu opens.
  document.addEventListener(OPEN_MENUS_EVENT, (event) => {
    const detail = (event as CustomEvent<OpenMenuDetail>).detail;
    if (!detail || detail.host === host || host.contains(detail.host)) return;
    close();
  });

  return { open, close, isOpen, focusFirst };
}
