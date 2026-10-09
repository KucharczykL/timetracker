import { reportClientError } from "../client-errors.js";
import { readLogSectionsProps } from "../generated/props.js";
import { FORM_DIALOG_RELOAD, type FormDialogReloadDetail } from "./form-dialog/events.js";
import { browser } from "./form-dialog/navigation.js";
import { MODAL_CHANGE, attachModal, type Modal } from "./modal-layer.js";
import type { SearchSelectChangeDetail } from "./search-select.js";

export const SECTION_DIALOG = "data-log-section";
export const SECTION_DONE = "data-log-section-done";
export const SECTION_EDIT = "data-log-section-edit";
/** Space-separated field names; one held value marks the section held. */
export const SECTION_HOLDS = "data-log-section-holds";
export const SECTION_IDLE = "data-log-section-idle";
export const SECTION_HELD = "data-log-section-held";
const GAME_FIELD = "game";

type Section = string; // e.g. "playtime"

function report(detail: string): void {
  reportClientError("log-sections", detail, { toast: false });
}

function fieldHolds(field: HTMLInputElement | HTMLTextAreaElement): boolean {
  if (field instanceof HTMLInputElement && field.type === "checkbox") return field.checked;
  return field.value.trim() !== "";
}

/** A section holds a value once one of its named fields does. */
function sectionHolds(dialog: HTMLDialogElement): boolean {
  const names = (dialog.getAttribute(SECTION_HOLDS) ?? "").split(" ").filter(Boolean);
  return names.some((name) =>
    Array.from(
      dialog.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(`[name="${name}"]`),
    ).some(fieldHolds),
  );
}

/** Each section's dialog opens from its opener; a picked game reloads the form. */
class LogSectionsElement extends HTMLElement {
  private readonly modals = new Map<Section, Modal>();
  /** Opens once the layer allows it. */
  private pending: Section | null = null;

  connectedCallback(): void {
    for (const dialog of this.querySelectorAll<HTMLDialogElement>(`dialog[${SECTION_DIALOG}]`)) {
      const section = dialog.getAttribute(SECTION_DIALOG) ?? "";
      if (this.modals.has(section)) continue;
      // Done, ×, Escape and the backdrop all close it and keep its fields.
      this.modals.set(section, attachModal(dialog));
    }
    this.addEventListener("input", this.syncHeld);
    this.addEventListener("change", this.syncHeld);
    this.addEventListener("click", this.onClick);
    this.addEventListener("search-select:change", this.onGamePick);
    this.syncHeld();
    const { openSection } = readLogSectionsProps(this);
    if (openSection) {
      this.pending = openSection;
      window.addEventListener(MODAL_CHANGE, this.openPending);
      queueMicrotask(this.openPending);
    }
  }

  disconnectedCallback(): void {
    this.removeEventListener("input", this.syncHeld);
    this.removeEventListener("change", this.syncHeld);
    this.removeEventListener("click", this.onClick);
    this.removeEventListener("search-select:change", this.onGamePick);
    window.removeEventListener(MODAL_CHANGE, this.openPending);
    this.pending = null;
    // A reload replaces the body, and its dialogs with it.
    this.modals.clear();
  }

  /** Each opener reads "held" while its section holds a value. */
  private readonly syncHeld = (): void => {
    for (const dialog of this.querySelectorAll<HTMLDialogElement>(`dialog[${SECTION_DIALOG}]`)) {
      const section = dialog.getAttribute(SECTION_DIALOG) ?? "";
      const held = sectionHolds(dialog);
      for (const opener of this.querySelectorAll<HTMLElement>(`[${SECTION_EDIT}="${section}"]`)) {
        opener.querySelector(`[${SECTION_IDLE}]`)?.toggleAttribute("hidden", held);
        opener.querySelector(`[${SECTION_HELD}]`)?.toggleAttribute("hidden", !held);
      }
    }
  };

  private open(section: Section, opener?: HTMLElement): boolean {
    const modal = this.modals.get(section);
    if (!modal) {
      report(`no dialog for section ${section}`);
      return true;
    }
    return modal.open(opener);
  }

  private readonly openPending = (): void => {
    if (this.pending === null || !this.isConnected) return;
    // Over its own dialog, never under it.
    if (this.closest("dialog")?.open === false) return;
    if (!this.open(this.pending)) return;
    this.pending = null;
    window.removeEventListener(MODAL_CHANGE, this.openPending);
  };

  /** A pick of a game reloads the page for that game; typed fields below it go. */
  private readonly onGamePick = (event: Event): void => {
    const detail = (event as CustomEvent<SearchSelectChangeDetail>).detail;
    if (detail.name !== GAME_FIELD || detail.none) return;
    const picked = detail.values[0];
    if (!picked) return;
    const { route, origin } = readLogSectionsProps(this);
    const url = new URL(route, location.href);
    url.searchParams.set("prefill_game", picked);
    if (origin) url.searchParams.set("origin", origin);
    if (this.closest("dialog[data-modal]")) {
      this.dispatchEvent(
        new CustomEvent<FormDialogReloadDetail>(FORM_DIALOG_RELOAD, {
          bubbles: true,
          detail: { url: url.href },
        }),
      );
      return;
    }
    browser.assign(url.href);
  };

  private readonly onClick = (event: MouseEvent): void => {
    const target = event.target as Element | null;
    const edit = target?.closest<HTMLElement>(`[${SECTION_EDIT}]`);
    if (edit && this.contains(edit)) {
      this.open(edit.getAttribute(SECTION_EDIT) ?? "", edit);
      return;
    }
    const done = target?.closest(`[${SECTION_DONE}]`);
    const dialog = done?.closest(`dialog[${SECTION_DIALOG}]`);
    if (dialog) this.modals.get(dialog.getAttribute(SECTION_DIALOG) ?? "")?.close();
  };
}

customElements.define("log-sections", LogSectionsElement);
