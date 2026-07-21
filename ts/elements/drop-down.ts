import { readDropdownProps } from "../generated/props.js";
import { getBehavior } from "./dropdown-behaviors.js";
import { attachMenu, MenuController, MenuPlacement } from "./menu-behavior.js";
// Side-effect imports register the built-in behaviors before connectedCallback.
import "./behaviors/menu.js";
import "./behaviors/select.js";
import "./behaviors/combobox.js";
import "./behaviors/inline-combobox.js";
import "./behaviors/sheet.js";

// Finds the element's own [data-toggle]/[data-menu], ignoring any that belong to
// a nested <drop-down> (so a sub-dropdown never cross-wires its parent).
function ownChild(host: HTMLElement, selector: string): HTMLElement | null {
  for (const match of host.querySelectorAll<HTMLElement>(selector)) {
    if (match.closest("drop-down") === host) return match;
  }
  return null;
}

// The one generic dropdown element. A registered behavior may provide its own
// controller (the modal sheet does); otherwise attachMenu owns the usual
// open/close/position/keyboard behavior. The element reads no type-specific
// attribute.
class DropdownElement extends HTMLElement {
  private controller?: MenuController;
  private unbindDocument?: () => void;

  connectedCallback(): void {
    if (this.controller) {
      // Reconnection (e.g. a moved node): element-local wiring traveled
      // with the subtree, so only the document listeners need re-attaching.
      // Re-running attachMenu would stack a second toggle handler and every
      // click would open-then-close.
      this.unbindDocument = this.controller.bindDocument();
      return;
    }
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
    const controller = behavior?.createController
      ? behavior.createController(this, toggle, menu)
      : attachMenu(this, toggle, menu, {
          placement: props.placement as MenuPlacement,
          submenu: props.submenu,
          ...(behavior?.menuOptions?.(this) ?? {}),
        });
    this.controller = controller;
    this.unbindDocument = controller.bindDocument();
    // wire()'s cleanup return is intentionally discarded. Every behavior binds
    // only to subtree-local nodes (toggle/menu/search input), so a real removal
    // GCs them with the detached subtree — nothing to unbind. Running that
    // cleanup in disconnectedCallback would instead break a MOVE: disconnect
    // fires on move too, and the reconnect guard above skips re-wiring, so the
    // moved dropdown would lose its behavior listeners for good.
    behavior?.wire?.({ host: this, toggle, menu, controller });
  }

  /** Open the dropdown programmatically. The inline-combobox host calls this
   *  from its widget's focus/typing handlers (the input is the trigger, not a
   *  toggle click). Idempotent — attachMenu's open() no-ops if already open.
   *  Safe to call before connect/upgrade — no-op. */
  open(): void {
    this.controller?.open();
  }

  /** Close the dropdown programmatically (e.g. after a consumer handles a
   *  pick inside the panel). Safe to call before connect/upgrade — no-op. */
  close(): void {
    this.controller?.close();
  }

  disconnectedCallback(): void {
    // Close (an open panel would linger at stale fixed coordinates) and
    // drop the document listeners; the controller and element-local wiring
    // persist for reconnection.
    this.controller?.close();
    this.unbindDocument?.();
    this.unbindDocument = undefined;
  }
}

customElements.define("drop-down", DropdownElement);
