/** <selectable-table> — a data table's selection mode. */

import {
  readSelectableTableProps,
  SelectableTableProps,
} from "../generated/props.js";
import {
  forgetSelection,
  readSelection,
  storageKeyFor,
  writeSelection,
} from "./selection-storage.js";
import {
  CheckAllState,
  checkAllState,
  clearSelection,
  emptySelection,
  rangeKeys,
  selectAllMatching,
  SelectionState,
  selectionCount,
  setPage,
  statementFor,
  toggleKey,
} from "./selection-statement.js";

const CHECKBOX_SELECTOR = "[data-selection-checkbox]";
const HIDDEN_CHECKBOX_CLASS = "invisible";
const ROW_SELECTOR = "tbody tr[data-selection-key]";
const LINE_HEIGHT_PROPERTY = "--selection-line";

export class SelectableTableElement extends HTMLElement {
  private props!: SelectableTableProps;
  private state: SelectionState = emptySelection();
  private anchorKey: string | null = null;
  private mode = false;
  private line: HTMLElement | null = null;
  private controls: HTMLElement | null = null;
  private toggles: HTMLElement[] = [];
  private checkAll: HTMLInputElement | null = null;
  private countText: HTMLElement | null = null;
  private announcement: HTMLElement | null = null;
  private checkboxTemplate: HTMLTemplateElement | null = null;
  private rowObserver: MutationObserver | null = null;
  private storageKey = "";
  private knownKeys = new Set<string>();

  connectedCallback(): void {
    this.props = readSelectableTableProps(this);
    this.line = this.querySelector("[data-selection-line]");
    this.controls = this.querySelector("[data-selection-controls]");
    this.toggles = Array.from(
      this.querySelectorAll<HTMLElement>("[data-selection-toggle]"),
    );
    this.checkAll = this.querySelector("[data-selection-check-all]");
    this.countText = this.querySelector("[data-selection-count]");
    this.announcement = this.querySelector("[data-selection-announcement]");
    this.checkboxTemplate = this.querySelector(
      "template[data-selection-checkbox-template]",
    );
    if (!this.line || !this.toggles.length) return;

    for (const toggle of this.toggles) {
      toggle.addEventListener("click", () => this.setMode(!this.mode));
    }
    this.checkAll?.addEventListener("change", () => this.onCheckAll());
    this.querySelector("[data-selection-all-matching]")?.addEventListener(
      "click",
      () => this.onAllMatching(),
    );
    this.querySelector("[data-selection-clear]")?.addEventListener("click", () =>
      this.onClear(),
    );
    this.addEventListener("click", (event) => this.onBodyClick(event));
    this.addEventListener("keydown", (event) => this.onKeyDown(event));

    // Built at connect, hidden until the mode: a checkbox added later would
    // move every row.
    this.decorateRows();
    this.knownKeys = new Set(this.pageKeys());

    // A selection outlives the page it was made on: the list's other pages
    // find it again, and the mode comes back with it.
    this.storageKey = storageKeyFor(window.location.pathname);
    const stored = readSelection(this.storageKey, this.props.filter);
    if (stored) {
      this.state = stored;
      // Nothing changed for the reader: the page arrived this way.
      this.setMode(true, false);
    }

    const body = this.querySelector("tbody");
    if (body && typeof MutationObserver !== "undefined") {
      // A swapped row arrives undecorated.
      this.rowObserver = new MutationObserver(() => this.onRowsChanged());
      this.rowObserver.observe(body, { childList: true });
    }
  }

  disconnectedCallback(): void {
    this.rowObserver?.disconnect();
    this.rowObserver = null;
    document.documentElement.style.removeProperty(LINE_HEIGHT_PROPERTY);
  }

  private rows(): HTMLElement[] {
    return Array.from(this.querySelectorAll<HTMLElement>(ROW_SELECTOR));
  }

  private pageKeys(): string[] {
    return this.rows().map((row) => row.getAttribute("data-selection-key") ?? "");
  }

  /** The mode, and with it every checkbox. */
  setMode(on: boolean, announce = true): void {
    this.mode = on;
    this.toggleAttribute("data-selection-mode", false);
    if (on) this.setAttribute("data-selection-mode", "on");
    for (const toggle of this.toggles) {
      toggle.setAttribute("aria-pressed", String(on));
    }
    if (this.line) this.line.hidden = !on;
    if (!on) {
      this.state = clearSelection();
      this.anchorKey = null;
      if (this.storageKey) forgetSelection(this.storageKey);
    }
    this.showCheckboxes(on);
    if (announce) this.announce(on ? "Selecting rows." : "Selection off.");
    this.render();
    this.publishLineHeight();
  }

  private decorateRows(): void {
    const template = this.checkboxTemplate;
    if (!template) return;
    for (const row of this.rows()) {
      const cell = row.querySelector<HTMLElement>('th[scope="row"]');
      if (!cell || cell.querySelector(CHECKBOX_SELECTOR)) continue;
      const checkbox = template.content.firstElementChild?.cloneNode(
        true,
      ) as HTMLInputElement | null;
      if (!checkbox) continue;
      checkbox.setAttribute("aria-label", identityName(cell));
      checkbox.classList.toggle(HIDDEN_CHECKBOX_CLASS, !this.mode);
      cell.insertBefore(checkbox, cell.firstChild);
    }
  }

  /** Visibility, never presence: a checkbox that comes and goes would move
   * every row under the reader's hand. */
  private showCheckboxes(on: boolean): void {
    this.querySelectorAll(CHECKBOX_SELECTOR).forEach((checkbox) =>
      checkbox.classList.toggle(HIDDEN_CHECKBOX_CLASS, !on),
    );
  }

  private keyOf(target: EventTarget | null): string | null {
    if (!(target instanceof HTMLElement)) return null;
    if (!target.matches(CHECKBOX_SELECTOR)) return null;
    return target.closest("tr")?.getAttribute("data-selection-key") ?? null;
  }

  private onBodyClick(event: Event): void {
    const key = this.keyOf(event.target);
    if (key === null) return;
    const checkbox = event.target as HTMLInputElement;
    const mouse = event as MouseEvent;
    if (mouse.shiftKey && this.anchorKey) {
      this.applyRange(this.anchorKey, key, checkbox.checked);
    } else {
      this.state = toggleKey(this.state, key);
      this.anchorKey = key;
    }
    this.render();
  }

  private onKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      // A menu that closed marks the press spent.
      if (event.defaultPrevented || !this.mode) return;
      this.onClear();
      return;
    }
    if (event.key !== " " || !event.shiftKey) return;
    const key = this.keyOf(event.target);
    if (key === null || !this.anchorKey) return;
    // The space itself would toggle the anchor back.
    //
    // Without this the checkbox's own activation runs beside the range, and
    // the row the range starts from ends the press unmarked.
    event.preventDefault();
    const checkbox = event.target as HTMLInputElement;
    this.applyRange(this.anchorKey, key, !checkbox.checked);
    this.render();
  }

  private applyRange(anchorKey: string, targetKey: string, checked: boolean): void {
    const keys = rangeKeys(this.pageKeys(), anchorKey, targetKey);
    this.state = setPage(this.state, keys, checked);
    this.anchorKey = targetKey;
  }

  private onCheckAll(): void {
    const checked = this.checkAll?.checked ?? false;
    this.state = setPage(this.state, this.pageKeys(), checked);
    this.anchorKey = null;
    this.render();
    this.announce(this.countSentence());
  }

  private onAllMatching(): void {
    this.state = selectAllMatching(this.state);
    this.anchorKey = null;
    this.render();
    this.announce(`${this.count()} selected, every row matching the filter.`);
  }

  private onClear(): void {
    this.state = clearSelection();
    this.anchorKey = null;
    if (this.storageKey) forgetSelection(this.storageKey);
    this.render();
    this.announce("Selection cleared.");
  }

  private onRowsChanged(): void {
    this.decorateRows();
    // A key this page held and holds no longer has left the table; a key it
    // never held belongs to another page of the same list.
    const present = new Set(this.pageKeys());
    const gone = [...this.knownKeys].filter((key) => !present.has(key));
    this.knownKeys = present;
    if (!gone.length) {
      if (this.mode) this.render();
      return;
    }
    const kept = [...this.state.keys].filter((key) => !gone.includes(key));
    this.state = { ...this.state, keys: new Set(kept) };
    this.render();
  }

  private count(): number {
    return selectionCount(this.state, this.props.count);
  }

  private countSentence(): string {
    return `${this.count()} selected`;
  }

  /** One state, rendered to every part. */
  private render(): void {
    const pageKeys = this.pageKeys();
    for (const row of this.rows()) {
      const key = row.getAttribute("data-selection-key") ?? "";
      const checkbox = row.querySelector<HTMLInputElement>(CHECKBOX_SELECTOR);
      if (!checkbox) continue;
      checkbox.checked = this.state.all
        ? !this.state.except.has(key)
        : this.state.keys.has(key);
    }
    const all: CheckAllState = checkAllState(this.state, pageKeys);
    if (this.checkAll) {
      this.checkAll.checked = all === "checked";
      this.checkAll.indeterminate = all === "indeterminate";
    }
    if (this.countText) this.countText.textContent = this.countSentence();
    if (this.storageKey) {
      writeSelection(this.storageKey, this.props.filter, this.state);
    }
    this.dispatchEvent(
      new CustomEvent("selectable-table:change", {
        bubbles: true,
        detail: statementFor(this.state, this.props.filter, this.props.count),
      }),
    );
  }

  private announce(sentence: string): void {
    if (this.announcement) this.announcement.textContent = sentence;
  }

  /** Public: jsdom has no layout engine. */
  publishLineHeight(): void {
    const style = document.documentElement.style;
    if (!this.mode || !this.line) {
      style.removeProperty(LINE_HEIGHT_PROPERTY);
      return;
    }
    const height = this.line.getBoundingClientRect().height;
    style.setProperty(LINE_HEIGHT_PROPERTY, `${Math.round(height)}px`);
  }
}

/** The row's name, without its summary line. */
function identityName(cell: HTMLElement): string {
  const clone = cell.cloneNode(true) as HTMLElement;
  clone.querySelectorAll(CHECKBOX_SELECTOR).forEach((node) => node.remove());
  clone.querySelectorAll("[data-row-summary]").forEach((node) => node.remove());
  return clone.textContent?.trim() ?? "";
}

customElements.define("selectable-table", SelectableTableElement);
