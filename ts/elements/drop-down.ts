import { reportClientError } from "../client-errors.js";
import { readDropdownProps } from "../generated/props.js";
import { SHEET_ATTRIBUTES } from "../generated/sheet-attributes.js";
import { getBehavior } from "./dropdown-behaviors.js";
import { attachMenu, MenuController, MenuOptions, MenuPlacement } from "./menu-behavior.js";
import { attachNarrowSheet } from "./narrow-sheet.js";
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

interface NarrowSheetParts {
  sheet: HTMLDialogElement;
  sentinel: HTMLElement;
}

// The one generic dropdown element. A registered behavior may provide its own
// controller (the modal sheet does); otherwise attachMenu owns the usual
// open/close/position/keyboard behavior. A dropdown sheet serves narrow
// viewports. The element reads no type-specific attribute.
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
    const narrow = this.narrowSheet();
    let controller: MenuController;
    if (behavior?.createController) {
      controller = behavior.createController(this, toggle, menu);
      if (narrow) {
        reportClientError(
          "drop-down",
          `behavior "${props.behavior}" brings its own controller; its sheet stays unused`,
          { toast: false },
        );
      }
    } else {
      const menuOptions: MenuOptions = {
        placement: props.placement as MenuPlacement,
        submenu: props.submenu,
        ...(behavior?.menuOptions?.(this) ?? {}),
      };
      const anchored = attachMenu(this, toggle, menu, {
        ...menuOptions,
        // The toggle opens whichever host fits.
        presenter: () => this.controller ?? anchored,
      });
      controller = anchored;
      if (narrow) {
        try {
          controller = attachNarrowSheet(this, menu, anchored, {
            dialog: narrow.sheet,
            sentinel: narrow.sentinel,
            expandedToggle: menuOptions.inlineTrigger ? undefined : toggle,
            sheetFocus: behavior?.sheetFocus,
          });
        } catch (error) {
          // The behavior still wires below.
          reportClientError("drop-down", `its sheet is unusable: ${String(error)}`, {
            toast: false,
          });
        }
      }
    }
    this.controller = controller;
    // wire()'s cleanup return is intentionally discarded. Every behavior binds
    // only to subtree-local nodes (toggle/menu/search input), so a real removal
    // GCs them with the detached subtree — nothing to unbind. Running that
    // cleanup in disconnectedCallback would instead break a MOVE: disconnect
    // fires on move too, and the reconnect guard above skips re-wiring, so the
    // moved dropdown would lose its behavior listeners for good.
    behavior?.wire?.({ host: this, toggle, menu, controller });
  }

  /** Its sheet and sentinel, or null. */
  private narrowSheet(): NarrowSheetParts | null {
    const sheet = ownChild(this, `[${SHEET_ATTRIBUTES.sheet}]`);
    const sentinel = ownChild(this, `[${SHEET_ATTRIBUTES.narrow}]`);
    if (!sheet && !sentinel) return null;
    if (sheet instanceof HTMLDialogElement && sentinel) return { sheet, sentinel };
    // A half-built sheet stays anchored.
    reportClientError(
      "drop-down",
      "a sheet needs a <dialog> and its narrow sentinel; it stays anchored",
      { toast: false },
    );
    return null;
  }

  /** Opens without a toggle click; idempotent. */
  open(opener?: HTMLElement): void {
    this.controller?.open(opener);
  }

  isOpen(): boolean {
    return this.controller?.isOpen() ?? false;
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
