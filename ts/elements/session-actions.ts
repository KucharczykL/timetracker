import { readSessionActionsProps } from "../generated/props.js";
import { nowISOUTC, bindPopupDismiss } from "../utils.js";
import { renderSessionRow } from "../session-row.js";

// Row actions for a session. Finish/reset drive PATCH /api/session/<id> with the
// client's own "now"; on success the API returns the updated SessionOut and the
// row is rebuilt in place (renderSessionRow). Reset is destructive (it overwrites
// the original start time), so it goes through an inline confirm modal. Edit and
// Delete are plain links the server rendered — this element ignores them.
class SessionActionsElement extends HTMLElement {
  private dismissCleanup: (() => void) | null = null;
  private modal: HTMLElement | null = null;

  connectedCallback(): void {
    const props = readSessionActionsProps(this);
    this.modal = this.querySelector<HTMLElement>("[data-reset-modal]");

    this.querySelector<HTMLElement>("[data-finish]")?.addEventListener("click", () => {
      this.patch(props.apiUrl, props.csrf, { timestamp_end: nowISOUTC() });
    });

    this.querySelector<HTMLElement>("[data-reset]")?.addEventListener("click", () => {
      this.openModal();
    });
    this.querySelector<HTMLElement>("[data-reset-cancel]")?.addEventListener("click", () => {
      this.closeModal();
    });
    this.querySelector<HTMLElement>("[data-reset-confirm]")?.addEventListener("click", () => {
      this.closeModal();
      this.patch(props.apiUrl, props.csrf, { timestamp_start: nowISOUTC() });
    });

    if (this.modal) {
      // Escape also dismisses the confirm modal. Cleaned up on disconnect (the
      // old element is discarded when the row is swapped).
      this.dismissCleanup = bindPopupDismiss({
        host: this.modal,
        isOpen: () => !!this.modal && !this.modal.hidden,
        close: () => this.closeModal(),
      });
    }
  }

  disconnectedCallback(): void {
    this.dismissCleanup?.();
    this.dismissCleanup = null;
    // If the row was swapped while the modal was still portaled to <body>,
    // discard the orphaned overlay so it doesn't linger.
    if (this.modal && this.modal.parentElement === document.body) {
      this.modal.remove();
    }
  }

  // While open, the modal is portaled to <body> so it is NOT a descendant of
  // the hovered <tr> — otherwise the viewport-covering overlay keeps that row's
  // :hover stuck (and blocks every other row). It returns to this element's
  // light DOM on close, so a row clone on reset still carries the modal markup.
  private openModal(): void {
    if (!this.modal) return;
    document.body.appendChild(this.modal);
    this.modal.hidden = false;
  }

  private closeModal(): void {
    if (!this.modal) return;
    this.modal.hidden = true;
    this.appendChild(this.modal);
  }

  private patch(apiUrl: string, csrf: string, body: Record<string, string>): void {
    const row = this.closest("tr");
    if (!row) return;
    window
      .fetchWithHtmxTriggers(apiUrl, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(body),
      })
      .then((response) => {
        // fetch resolves on 4xx/5xx — check explicitly so a rejected change
        // doesn't look successful.
        if (!response.ok) throw new Error(`PATCH ${apiUrl} → ${response.status}`);
        return response.json();
      })
      .then((session) => {
        // No optimistic update: the whole row is rebuilt from the server's
        // response, so on error (below) the original row is simply left as-is.
        row.replaceWith(renderSessionRow(session, row as HTMLTableRowElement));
      })
      .catch((error) => {
        console.error("Failed to update session", apiUrl, error);
        window.toast("Couldn't save your change — please try again.", "error");
      });
  }
}

customElements.define("session-actions", SessionActionsElement);
