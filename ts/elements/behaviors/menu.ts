import { SHEET_ATTRIBUTES, SHEET_HOST_VALUE } from "../../generated/sheet-attributes.js";
import { registerBehavior } from "../dropdown-behaviors.js";
import { MenuOptions } from "../menu-behavior.js";

const SUBMENU_CLOSE_DELAY_MS = 150;

const MENU_ITEM = '[role="menuitem"], [role="menuitemcheckbox"], [role="menuitemradio"]';
const TABBABLE = [
  "button",
  "a[href]",
  "input",
  "select",
  "textarea",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

const isSubmenu = (host: HTMLElement): boolean =>
  host.getAttribute("submenu") === "true";

// A control inside a hidden ancestor below the menu is not shown.
const isShown = (element: HTMLElement, menu: HTMLElement): boolean => {
  const hidden = element.closest("[hidden]");
  return !(hidden && hidden !== menu && menu.contains(hidden));
};

// Owned by this menu: a nested submenu's own controls do not count.
const isOwnEnabled = (element: HTMLElement, menu: HTMLElement): boolean =>
  element.closest("[data-menu]") === menu &&
  !element.hasAttribute("disabled") &&
  element.getAttribute("aria-disabled") !== "true" &&
  isShown(element, menu);

/** The first enabled item of this menu, else its first tabbable control. */
export function menuSheetFocus(menu: HTMLElement): HTMLElement | null {
  const items = Array.from(menu.querySelectorAll<HTMLElement>(MENU_ITEM));
  const item = items.find((candidate) => isOwnEnabled(candidate, menu));
  if (item) return item;
  const controls = Array.from(menu.querySelectorAll<HTMLElement>(TABBABLE));
  return controls.find((candidate) => isOwnEnabled(candidate, menu)) ?? null;
}

// A submenu whose parent menu is a sheet opens by click only, never by hover.
const inParentSheet = (host: HTMLElement): boolean =>
  host.closest(`[${SHEET_ATTRIBUTES.host}="${SHEET_HOST_VALUE}"]`) !== null;

registerBehavior("menu", {
  menuOptions: (host): Partial<MenuOptions> => {
    if (!isSubmenu(host)) return {};
    const parentPanel = host.closest("[data-menu]") as HTMLElement | null;
    return parentPanel ? { horizontalAnchor: parentPanel } : {};
  },
  sheetFocus: menuSheetFocus,
  wire: ({ host, toggle, menu, controller }) => {
    if (!isSubmenu(host)) return;
    let closeTimer = 0;
    const onEnter = (event: PointerEvent) => {
      if (event.pointerType !== "mouse" || inParentSheet(host)) return;
      window.clearTimeout(closeTimer);
      controller.open();
    };
    const onLeave = (event: PointerEvent) => {
      if (event.pointerType !== "mouse" || inParentSheet(host)) return;
      closeTimer = window.setTimeout(() => controller.close(), SUBMENU_CLOSE_DELAY_MS);
    };
    const onToggleKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowRight") return;
      event.preventDefault();
      controller.open();
      controller.focusFirst();
    };
    const onMenuKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft") return;
      event.preventDefault();
      controller.close();
      toggle.focus();
    };
    host.addEventListener("pointerenter", onEnter);
    host.addEventListener("pointerleave", onLeave);
    toggle.addEventListener("keydown", onToggleKey);
    menu.addEventListener("keydown", onMenuKey);
    return () => {
      host.removeEventListener("pointerenter", onEnter);
      host.removeEventListener("pointerleave", onLeave);
      toggle.removeEventListener("keydown", onToggleKey);
      menu.removeEventListener("keydown", onMenuKey);
    };
  },
});
