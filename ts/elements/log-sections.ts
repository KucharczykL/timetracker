import { reportClientError } from "../client-errors.js";
import { readLogSectionsProps } from "../generated/props.js";
import { MODAL_CHANGE, attachModal, type Modal } from "./modal-layer.js";

export const SECTION_DIALOG = "data-log-section";
export const SECTION_DONE = "data-log-section-done";
export const SECTION_EDIT = "data-log-section-edit";
export const SECTIONS_HINT = "data-log-sections-hint";
const TICK_SELECTOR = 'input[type="checkbox"][name="sections"]';

type Section = string; // e.g. "copy"

function report(detail: string): void {
  reportClientError("log-sections", detail, { toast: false });
}

/** Each ticked section opens its own dialog. */
class LogSectionsElement extends HTMLElement {
  private readonly modals = new Map<Section, Modal>();
  /** Opens once the layer allows it. */
  private pending: Section | null = null;

  connectedCallback(): void {
    for (const dialog of this.querySelectorAll<HTMLDialogElement>(`dialog[${SECTION_DIALOG}]`)) {
      const section = dialog.getAttribute(SECTION_DIALOG) ?? "";
      if (this.modals.has(section)) continue;
      this.modals.set(
        section,
        attachModal(dialog, {
          // ×, Escape, backdrop: the section is not added.
          dismiss: () => {
            const tick = this.tick(section);
            if (tick) tick.checked = false;
            this.modals.get(section)?.close();
          },
        }),
      );
    }
    this.addEventListener("change", this.onChange);
    this.addEventListener("click", this.onClick);
    this.addEventListener("search-select:change", this.syncTicks);
    this.syncTicks();
    const { openSection } = readLogSectionsProps(this);
    if (openSection) {
      this.pending = openSection;
      window.addEventListener(MODAL_CHANGE, this.openPending);
      queueMicrotask(this.openPending);
    }
  }

  disconnectedCallback(): void {
    this.removeEventListener("change", this.onChange);
    this.removeEventListener("click", this.onClick);
    this.removeEventListener("search-select:change", this.syncTicks);
    window.removeEventListener(MODAL_CHANGE, this.openPending);
    this.pending = null;
  }

  /** Every section needs a game. */
  private readonly syncTicks = (): void => {
    const held = Array.from(this.querySelectorAll<HTMLInputElement>('input[name="game"]')).some(
      (input) => input.value !== "",
    );
    for (const tick of this.querySelectorAll<HTMLInputElement>(TICK_SELECTOR)) {
      tick.disabled = !held;
    }
    for (const hint of this.querySelectorAll<HTMLElement>(`[${SECTIONS_HINT}]`)) {
      hint.hidden = held;
    }
  };

  private tick(section: Section): HTMLInputElement | null {
    return (
      Array.from(this.querySelectorAll<HTMLInputElement>(TICK_SELECTOR)).find(
        (input) => input.value === section,
      ) ?? null
    );
  }

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

  private readonly onChange = (event: Event): void => {
    const tick = event.target;
    if (!(tick instanceof HTMLInputElement) || !tick.matches(TICK_SELECTOR)) return;
    if (tick.checked) this.open(tick.value, tick);
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
