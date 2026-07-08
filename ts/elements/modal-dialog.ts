/**
 * ModalDialog — the confirm-overlay element. Server-rendered by the Modal
 * component (common/components/primitives.py) and swapped into
 * #global-modal-container by htmx. Gives the confirm modals their dismiss
 * contract: Escape + a backdrop click (bindPopupDismiss, anchored on the inner
 * panel so any click outside it counts) + any `[data-modal-dismiss]` control.
 * Dismissing removes the throwaway overlay.
 *
 * `data-manage="false"` keeps the element inert — the session-reset confirm is
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
    // bindPopupDismiss closes it; a click inside the panel does not. The Modal
    // component always renders [data-modal-panel]; bail (rather than fall back to
    // `this`, which would treat a backdrop click as inside and silently kill
    // backdrop-dismiss) if the contract is ever broken.
    const panel = this.querySelector<HTMLElement>("[data-modal-panel]");
    if (!panel) return;
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

  // An explicit dismiss control inside the panel (the Cancel button).
  private onClick = (event: MouseEvent): void => {
    if ((event.target as Element).closest("[data-modal-dismiss]")) this.dismiss();
  };

  private dismiss(): void {
    this.remove();
  }
}

customElements.define("modal-dialog", ModalDialogElement);
