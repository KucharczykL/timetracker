/**
 * ModalDialog — the confirm-overlay element (issue #303).
 *
 * The delete/refund/split confirm modals are server-rendered (Modal component,
 * common/components/primitives.py) and swapped into #global-modal-container by
 * htmx. They used to be dismissable only by an inline
 * `onclick="this.closest('#…').remove()"` on their Cancel button — no Escape,
 * no backdrop click, no aria. This element gives them the shared dismiss
 * contract instead: Escape + a click on the backdrop (via bindPopupDismiss,
 * anchored on the inner panel so a click anywhere outside it counts) + any
 * `[data-modal-dismiss]` control. Dismissing removes the overlay — the confirm
 * modals are throwaway.
 *
 * `data-manage="false"` keeps the element inert: the session-reset confirm is
 * wrapped in <session-actions>, which owns its open/close and its own
 * bindPopupDismiss; a second engine on the inner overlay would fight it.
 */
import { bindPopupDismiss } from "../utils.js";

class ModalDialogElement extends HTMLElement {
  private cleanup: (() => void) | null = null;

  connectedCallback(): void {
    if (this.getAttribute("data-manage") === "false") return;
    // Anchor the outside-click dismiss on the panel, not the overlay: a click
    // on the backdrop is "outside" the panel (but inside the overlay), so
    // bindPopupDismiss closes it; a click inside the panel does not.
    const panel = this.querySelector<HTMLElement>("[data-modal-panel]") ?? this;
    this.addEventListener("click", this.onClick);
    this.cleanup = bindPopupDismiss({
      host: panel,
      isOpen: () => this.isConnected,
      close: () => this.dismiss(),
    });
  }

  disconnectedCallback(): void {
    this.cleanup?.();
    this.cleanup = null;
    this.removeEventListener("click", this.onClick);
  }

  // An explicit dismiss control inside the panel (the Cancel button) — the
  // no-JS replacement for the old inline onclick=remove().
  private onClick = (event: MouseEvent): void => {
    if ((event.target as Element).closest("[data-modal-dismiss]")) this.dismiss();
  };

  private dismiss(): void {
    this.remove();
  }
}

customElements.define("modal-dialog", ModalDialogElement);
