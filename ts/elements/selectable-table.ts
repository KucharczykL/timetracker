/** <selectable-table> — the personality a data table gains for acting on many
 * rows at once.
 *
 * Selection is a mode: off on every load, turned on by the Select toggle in
 * the footer's selection line. Only then does the element clone a checkbox
 * into each row's identity cell, so a page with no scripting renders none.
 * The element holds the selection, announces each change of scope, and
 * publishes the statement as `selectable-table:change` — the field that posts
 * it is #712's.
 *
 * The line's height is published as `--selection-line`, which the toast stack
 * and the version stamp read to stand off the corner they share with it.
 */

import {
  readSelectableTableProps,
  SelectableTableProps,
} from "../generated/props.js";
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
const ROW_SELECTOR = "tbody tr[data-selection-key]";
const LINE_HEIGHT_PROPERTY = "--selection-line";

export class SelectableTableElement extends HTMLElement {
  private props!: SelectableTableProps;
  private state: SelectionState = emptySelection();
  private anchorKey: string | null = null;
  private mode = false;
  private line: HTMLElement | null = null;
  private controls: HTMLElement | null = null;
  private toggle: HTMLElement | null = null;
  private checkAll: HTMLInputElement | null = null;
  private countText: HTMLElement | null = null;
  private announcement: HTMLElement | null = null;
  private checkboxTemplate: HTMLTemplateElement | null = null;
  private rowObserver: MutationObserver | null = null;

  connectedCallback(): void {
    this.props = readSelectableTableProps(this);
    this.line = this.querySelector("[data-selection-line]");
    this.controls = this.querySelector("[data-selection-controls]");
    this.toggle = this.querySelector("[data-selection-toggle]");
    this.checkAll = this.querySelector("[data-selection-check-all]");
    this.countText = this.querySelector("[data-selection-count]");
    this.announcement = this.querySelector("[data-selection-announcement]");
    this.checkboxTemplate = this.querySelector(
      "template[data-selection-checkbox-template]",
    );
    if (!this.line || !this.toggle) return;

    this.toggle.addEventListener("click", () => this.setMode(!this.mode));
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

    const body = this.querySelector("tbody");
    if (body && typeof MutationObserver !== "undefined") {
      // A row swapped in while the mode is on arrives undecorated, and a row
      // swapped out takes its key with it. Attributes are not observed: the
      // decoration is itself an attribute write.
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

  /** The mode, and with it every checkbox. Turning it off clears the
   * selection: a mark nobody can see is a mark nobody stated. */
  setMode(on: boolean): void {
    this.mode = on;
    this.toggleAttribute("data-selection-mode", false);
    if (on) this.setAttribute("data-selection-mode", "on");
    this.toggle?.setAttribute("aria-pressed", String(on));
    if (this.controls) this.controls.hidden = !on;
    if (on) {
      this.decorateRows();
      this.announce("Selecting rows.");
    } else {
      this.state = clearSelection();
      this.anchorKey = null;
      this.undecorateRows();
      this.announce("Selection off.");
    }
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
      cell.insertBefore(checkbox, cell.firstChild);
    }
  }

  private undecorateRows(): void {
    this.querySelectorAll(CHECKBOX_SELECTOR).forEach((checkbox) =>
      checkbox.remove(),
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
      // A menu inside the table answers Escape first and does not stop the
      // event, so a cleared selection would be a second, unasked-for act.
      if (event.defaultPrevented || !this.mode) return;
      this.onClear();
      return;
    }
    if (event.key !== " " || !event.shiftKey) return;
    const key = this.keyOf(event.target);
    if (key === null || !this.anchorKey) return;
    // The space would toggle the checkbox itself, which would take the anchor
    // back out of the range this press is taking in.
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
    this.render();
    this.announce("Selection cleared.");
  }

  private onRowsChanged(): void {
    if (!this.mode) return;
    this.decorateRows();
    const present = new Set(this.pageKeys());
    const kept = [...this.state.keys].filter((key) => present.has(key));
    this.state = { ...this.state, keys: new Set(kept) };
    this.render();
  }

  private count(): number {
    return selectionCount(this.state, this.props.count);
  }

  private countSentence(): string {
    return `${this.count()} selected`;
  }

  /** The checkboxes, the check-all, the count and the statement, from one
   * state — so nothing reads a mark off the DOM it wrote itself. */
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

  /** Public so a test with no layout engine can drive it, as
   * <responsive-table> exposes applyDecision. */
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

/** The row's name, for the checkbox that selects it: the identity cell's text
 * without the summary line, which repeats what the columns say. */
function identityName(cell: HTMLElement): string {
  const clone = cell.cloneNode(true) as HTMLElement;
  clone.querySelectorAll(CHECKBOX_SELECTOR).forEach((node) => node.remove());
  clone.querySelectorAll("[data-row-summary]").forEach((node) => node.remove());
  return clone.textContent?.trim() ?? "";
}

customElements.define("selectable-table", SelectableTableElement);
