import { readDropdownProps } from "../generated/props.js";
import { getBehavior } from "./dropdown-behaviors.js";
import { attachMenu, MenuController, MenuPlacement } from "./menu-behavior.js";
// Side-effect imports register the built-in behaviors before connectedCallback.
import "./behaviors/menu.js";
import "./behaviors/select.js";

// Finds the element's own [data-toggle]/[data-menu], ignoring any that belong to
// a nested <drop-down> (so a sub-dropdown never cross-wires its parent).
function ownChild(host: HTMLElement, selector: string): HTMLElement | null {
  for (const match of host.querySelectorAll<HTMLElement>(selector)) {
    if (match.closest("drop-down") === host) return match;
  }
  return null;
}

// The one generic dropdown element. attachMenu owns open/close/position/keyboard;
// a registered behavior (menu, select, …) declares the attachMenu options it
// needs and layers its own wiring. The element reads no type-specific attribute.
class DropdownElement extends HTMLElement {
  private controller?: MenuController;
  private teardown?: () => void;

  connectedCallback(): void {
    const props = readDropdownProps(this);
    const toggle = ownChild(this, "[data-toggle]");
    const menu = ownChild(this, "[data-menu]");
    if (!toggle || !menu) return;

    const behavior = getBehavior(props.behavior);
    if (props.behavior && !behavior) {
      // A named-but-unregistered behavior degrades to a bare open/close menu with
      // no wiring (e.g. a `select` dropdown that never PATCHes) — say so loudly
      // instead of failing silently. An empty behavior is intentional and quiet.
      console.error(
        `<drop-down> requested behavior "${props.behavior}" but none is registered; ` +
          "it will open/close but its behavior wiring is missing.",
      );
    }
    const controller = attachMenu(this, toggle, menu, {
      placement: props.placement as MenuPlacement,
      submenu: props.submenu,
      ...(behavior?.menuOptions?.(this) ?? {}),
    });
    this.controller = controller;
    this.teardown =
      behavior?.wire?.({ host: this, toggle, menu, controller }) ?? undefined;
  }

  disconnectedCallback(): void {
    this.teardown?.();
    this.teardown = undefined;
    this.controller?.destroy();
    this.controller = undefined;
  }
}

customElements.define("drop-down", DropdownElement);
