import { reportClientError } from "../client-errors.js";
import { type LogSectionsProps, readLogSectionsProps } from "../generated/props.js";
import { FORM_DIALOG_RELOAD, type FormDialogReloadDetail } from "./form-dialog/events.js";
import { browser } from "./form-dialog/navigation.js";
import { MODAL_CHANGE, attachModal, type Modal } from "./modal-layer.js";
import type { SearchSelectChangeDetail } from "./search-select.js";

const SECTION_DIALOG = "data-log-section";
const SECTION_DIALOG_SELECTOR = `dialog[${SECTION_DIALOG}]`;
const SECTION_DONE = "data-log-section-done";
const SECTION_EDIT = "data-log-section-edit";
/** Space-separated fields that hold a section. */
const SECTION_HOLDS = "data-log-section-holds";
const SECTION_IDLE = "data-log-section-idle";
const SECTION_HELD = "data-log-section-held";
const GAME_FIELD = "game";

/** A section the generated props name. */
type Section = Exclude<LogSectionsProps["openSection"], "">;
/** Adding a section fails compilation here. */
const SECTION_MEMBERS: Record<Section, true> = { playtime: true, more: true };

function isSection(value: string): value is Section {
  return Object.hasOwn(SECTION_MEMBERS, value);
}

function report(detail: string): void {
  reportClientError("log-sections", detail, { toast: false });
}

/** Section named by a dialog; null if unknown. */
function sectionOf(dialog: Element): Section | null {
  const name = dialog.getAttribute(SECTION_DIALOG) ?? "";
  return isSection(name) ? name : null;
}

function fieldHolds(field: HTMLInputElement | HTMLTextAreaElement): boolean {
  if (field instanceof HTMLInputElement && field.type === "checkbox") return field.checked;
  return field.value.trim() !== "";
}

/** Section holds once any field does. */
function sectionHolds(dialog: HTMLDialogElement): boolean {
  const names = (dialog.getAttribute(SECTION_HOLDS) ?? "").split(" ").filter(Boolean);
  return names.some((name) =>
    Array.from(
      dialog.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(`[name="${name}"]`),
    ).some(fieldHolds),
  );
}

/** Opens each section's dialog from its opener. */
class LogSectionsElement extends HTMLElement {
  /** Keyed by dialog; a move keeps handles. */
  private readonly modals = new Map<HTMLDialogElement, Modal>();
  /** Opens once the layer allows it. */
  private pending: Section | null = null;

  connectedCallback(): void {
    // A reload replaced these dialogs.
    for (const dialog of this.modals.keys()) {
      if (!this.contains(dialog)) this.modals.delete(dialog);
    }
    for (const dialog of this.querySelectorAll<HTMLDialogElement>(SECTION_DIALOG_SELECTOR)) {
      if (this.modals.has(dialog)) continue;
      if (sectionOf(dialog) === null) {
        report(`dialog names no known section: ${dialog.getAttribute(SECTION_DIALOG)}`);
        continue;
      }
      // Every close keeps the fields.
      this.modals.set(dialog, attachModal(dialog));
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
  }

  /** Opener reads "held" while section holds. */
  private readonly syncHeld = (): void => {
    for (const dialog of this.querySelectorAll<HTMLDialogElement>(SECTION_DIALOG_SELECTOR)) {
      const section = sectionOf(dialog);
      if (section === null) continue;
      const held = sectionHolds(dialog);
      for (const opener of this.querySelectorAll<HTMLElement>(`[${SECTION_EDIT}="${section}"]`)) {
        opener.querySelector(`[${SECTION_IDLE}]`)?.toggleAttribute("hidden", held);
        opener.querySelector(`[${SECTION_HELD}]`)?.toggleAttribute("hidden", !held);
      }
    }
  };

  private open(section: Section, opener?: HTMLElement): boolean {
    const dialog = this.querySelector<HTMLDialogElement>(`dialog[${SECTION_DIALOG}="${section}"]`);
    const modal = dialog ? this.modals.get(dialog) : undefined;
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

  /** Picking a game reloads the page. */
  private readonly onGamePick = (event: Event): void => {
    const detail = (event as CustomEvent<SearchSelectChangeDetail>).detail;
    const picked = detail.values[0];
    if (detail.name !== GAME_FIELD || detail.none || !picked) return;
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
      const name = edit.getAttribute(SECTION_EDIT) ?? "";
      if (isSection(name)) this.open(name, edit);
      else report(`opener names no known section: ${name}`);
      return;
    }
    const done = target?.closest(`[${SECTION_DONE}]`);
    const dialog = done?.closest<HTMLDialogElement>(SECTION_DIALOG_SELECTOR);
    if (dialog) this.modals.get(dialog)?.close();
  };
}

customElements.define("log-sections", LogSectionsElement);
