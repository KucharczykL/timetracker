// Hosts a test widget as the server does.
import "../elements/drop-down.js";

/** Wraps a widget in its host. */
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

/** The face, the widget and its sheet. */
export function sheetHosted(widget: HTMLElement, { create = false } = {}): HTMLElement {
  const host = hosted(widget);
  host.insertAdjacentHTML(
    "afterbegin",
    `<div data-search-select-face>
      <button type="button" data-search-select-face-open aria-expanded="false">
        <span data-search-select-face-name></span><span data-search-select-face-value></span>
      </button>
      <button type="button" data-search-select-face-clear hidden>×</button>
      ${create ? '<a href="/new" data-form-dialog="header" data-search-select-dialog-create data-search-select-face-create>+</a>' : ""}
    </div>`,
  );
  host.insertAdjacentHTML(
    "beforeend",
    `<dialog data-modal data-dropdown-sheet>
      <div data-sheet-panel>
        <div><h2 data-dropdown-sheet-title></h2><button data-modal-dismiss type="button">×</button></div>
        <div data-sheet-body></div>
      </div>
    </dialog>
    <span data-dropdown-narrow></span>`,
  );
  return host;
}

/** Makes a sheet host narrow, or wide. */
export function setNarrow(host: HTMLElement, narrow: boolean): void {
  const rects = () => (narrow ? [new DOMRect(0, 0, 1, 1)] : []) as unknown as DOMRectList;
  host.querySelector<HTMLElement>("[data-dropdown-narrow]")!.getClientRects = rects;
  host.querySelector<HTMLElement>("[data-search-select-face]")!.getClientRects = rects;
}

/** A press: pointerdown, pointerup, then click. */
export function press(target: EventTarget): void {
  const init = { bubbles: true, composed: true, isPrimary: true, button: 0, pointerId: 1 };
  target.dispatchEvent(new PointerEvent("pointerdown", init));
  target.dispatchEvent(new PointerEvent("pointerup", init));
  target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}
