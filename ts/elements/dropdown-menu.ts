import { readDropdownMenuProps } from "../generated/props.js";
import { attachMenu, MenuController, MenuPlacement } from "./menu-behavior.js";

const SUBMENU_CLOSE_DELAY_MS = 150;

// Finds the element's own [data-toggle]/[data-menu], ignoring any that belong to
// a nested <dropdown-menu> (so a sub-dropdown never cross-wires its parent).
function ownChild(host: HTMLElement, selector: string): HTMLElement | null {
  for (const match of host.querySelectorAll<HTMLElement>(selector)) {
    if (match.closest("dropdown-menu") === host) return match;
  }
  return null;
}

// Generic dropdown menu (navigation links, actions, checkboxes, submenus). All
// open/close + keyboard behavior lives in attachMenu; this element only adds
// hover-open + arrow-key handling for the submenu (placement="right-start") case.
class DropdownMenuElement extends HTMLElement {
  private controller?: MenuController;

  connectedCallback(): void {
    const props = readDropdownMenuProps(this);
    const toggle = ownChild(this, "[data-toggle]");
    const menu = ownChild(this, "[data-menu]");
    if (!toggle || !menu) return;

    const controller = attachMenu(this, toggle, menu, {
      placement: props.placement as MenuPlacement,
      submenu: props.submenu,
    });
    this.controller = controller;

    if (props.submenu) {
      // Hover open/close is for mouse only. On touch, pointerleave fires when
      // the finger lifts, which would close the submenu immediately; there a
      // tap toggles it instead (attachMenu's toggle click handler).
      let closeTimer = 0;
      this.addEventListener("pointerenter", (event) => {
        if (event.pointerType !== "mouse") return;
        window.clearTimeout(closeTimer);
        controller.open();
      });
      this.addEventListener("pointerleave", (event) => {
        if (event.pointerType !== "mouse") return;
        closeTimer = window.setTimeout(() => controller.close(), SUBMENU_CLOSE_DELAY_MS);
      });
      toggle.addEventListener("keydown", (event) => {
        if (event.key === "ArrowRight") {
          event.preventDefault();
          controller.open();
          controller.focusFirst();
        }
      });
      menu.addEventListener("keydown", (event) => {
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          controller.close();
          toggle.focus();
        }
      });
    }
  }

  disconnectedCallback(): void {
    this.controller?.destroy();
    this.controller = undefined;
  }
}

customElements.define("dropdown-menu", DropdownMenuElement);
