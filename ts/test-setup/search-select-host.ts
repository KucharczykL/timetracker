// Hosts a test widget as the server does.
import "../elements/drop-down.js";

/** Wraps an unconnected widget in its inline-combobox host. */
export function hosted(widget: HTMLElement): HTMLElement {
  const host = document.createElement("drop-down");
  host.setAttribute("behavior", "inline-combobox");
  host.setAttribute("placement", "bottom-start");
  host.setAttribute("submenu", "false");
  widget.setAttribute("data-toggle", "");
  const panel =
    widget.querySelector<HTMLElement>("[data-search-select-panel]") ??
    widget.querySelector<HTMLElement>("[data-search-select-options]");
  panel?.setAttribute("data-menu", "");
  panel?.setAttribute("popover", "manual");
  host.append(widget);
  return host;
}

/** A press: pointerdown, pointerup, then click. */
export function press(target: EventTarget): void {
  const init = { bubbles: true, composed: true, isPrimary: true, button: 0, pointerId: 1 };
  target.dispatchEvent(new PointerEvent("pointerdown", init));
  target.dispatchEvent(new PointerEvent("pointerup", init));
  target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}
