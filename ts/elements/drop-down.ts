import { reportClientError } from "../client-errors.js";
import { readDropdownProps } from "../generated/props.js";
import { getBehavior } from "./dropdown-behaviors.js";
import { attachMenu, MenuController, MenuPlacement } from "./menu-behavior.js";
import { ownChild } from "./own-child.js";
// Side-effect imports register the built-in behaviors before connectedCallback.
import "./behaviors/menu.js";
import "./behaviors/select.js";
import "./behaviors/combobox.js";
import "./behaviors/inline-combobox.js";
import "./behaviors/choice-grid.js";
import "./behaviors/column-picker.js";
import "./behaviors/date-calendar.js";
import "./behaviors/sheet.js";


// The one generic dropdown element. A registered behavior may provide its own
// controller (the modal sheet does); otherwise attachMenu owns the usual
// open/close/position/keyboard behavior. The element reads no type-specific
// attribute.
export class DropdownElement extends HTMLElement {
  private controller?: MenuController;

  connectedCallback(): void {
    // Moved: rewiring would double-toggle.
    if (this.controller) return;
    const props = readDropdownProps(this);
    const toggle = ownChild(this, "[data-toggle]");
    const menu = ownChild(this, "[data-menu]");
    if (!toggle || !menu) {
      // Unwired, open() and close() would do nothing.
      reportClientError(
        "drop-down",
        `no own ${toggle ? "[data-menu]" : "[data-toggle]"}; it stays unwired`,
        { toast: false },
      );
      return;
    }

    const behavior = getBehavior(props.behavior);
    if (props.behavior && !behavior) {
      // A named-but-unregistered behavior degrades to a bare open/close menu with
      // no wiring (e.g. a `select` dropdown that never PATCHes) — say so loudly
      // instead of failing silently. An empty behavior is intentional and quiet.
      reportClientError(
        "drop-down",
        `behavior "${props.behavior}" is not registered; its wiring is missing`,
        { toast: false },
      );
    }
    const controller = behavior?.createController
      ? behavior.createController(this, toggle, menu)
      : attachMenu(this, toggle, menu, {
          placement: props.placement as MenuPlacement,
          submenu: props.submenu,
          ...(behavior?.menuOptions?.(this) ?? {}),
        });
    this.controller = controller;
    // wire()'s cleanup return is intentionally discarded. Every behavior binds
    // only to subtree-local nodes (toggle/menu/search input), so a real removal
    // GCs them with the detached subtree — nothing to unbind. Running that
    // cleanup in disconnectedCallback would instead break a MOVE: disconnect
    // fires on move too, and the reconnect guard above skips re-wiring, so the
    // moved dropdown would lose its behavior listeners for good.
    behavior?.wire?.({ host: this, toggle, menu, controller });
  }

  /** Opens without a toggle click; idempotent. */
  open(): void {
    this.controller?.open();
  }

  /** Closes without a toggle click; idempotent. */
  close(): void {
    this.controller?.close();
  }

  disconnectedCallback(): void {
    // The controller persists for reconnection.
    this.controller?.close();
  }
}

customElements.define("drop-down", DropdownElement);

declare global {
  interface HTMLElementTagNameMap {
    "drop-down": DropdownElement;
  }
}
