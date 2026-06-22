import { registerBehavior } from "../dropdown-behaviors.js";
import { MenuOptions } from "../menu-behavior.js";

const SUBMENU_CLOSE_DELAY_MS = 150;

const isSubmenu = (host: HTMLElement): boolean =>
  host.getAttribute("submenu") === "true";

registerBehavior("menu", {
  menuOptions: (host): Partial<MenuOptions> => {
    if (!isSubmenu(host)) return {};
    const parentPanel = host.closest("[data-menu]") as HTMLElement | null;
    return parentPanel ? { horizontalAnchor: parentPanel } : {};
  },
  wire: ({ host, toggle, menu, controller }) => {
    if (!isSubmenu(host)) return;
    let closeTimer = 0;
    const onEnter = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      window.clearTimeout(closeTimer);
      controller.open();
    };
    const onLeave = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
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
