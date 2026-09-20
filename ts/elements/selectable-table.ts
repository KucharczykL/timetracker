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
  emptySelection,
  forgetKeys,
  isMarked,
  rangeKeys,
  selectAllMatching,
  SelectionStatement,
  SelectionState,
  selectionCount,
  setPage,
  statementFor,
  toggleKey,
} from "./selection-statement.js";

const CHECKBOX_SELECTOR = "[data-selection-checkbox]";
// Every connected table, so the published height is the tallest line rather
// than whichever table wrote last.
const connected = new Set<SelectableTableElement>();
const HIDDEN_CHECKBOX_CLASS = "invisible";
const ROW_SELECTOR = "tbody tr[data-selection-key]";
const LINE_HEIGHT_PROPERTY = "--selection-line";

export class SelectableTableElement extends HTMLElement {
  private props!: SelectableTableProps;
  private state: SelectionState = emptySelection();
  private anchorKey: string | null = null;
  private mode = false;
  private line: HTMLElement | null = null;
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
    connected.add(this);
    this.line = this.querySelector("[data-selection-line]");
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
    // An act on the selection ends it: the rows it named are gone, moved or
    // changed, so restoring that statement over what is left would act on
    // rows nobody chose. The slot below renders the form; the rule is stated
    // here, where the statement is kept.
    this.querySelector("[data-selection-actions]")?.addEventListener(
      "submit",
      () => this.forgetAndClose(),
    );
    this.addEventListener("click", (event) => this.onBodyClick(event));
    this.addEventListener("keydown", (event) => this.onKeyDown(event));

    // Built at connect, hidden until the mode.
    this.decorateRows();
    this.knownKeys = new Set(this.pageKeys());

    // A selection outlives the page it was made on.
    this.storageKey = storageKeyFor(this.props.scope, window.location.pathname);
    const stored = readSelection(this.storageKey, this.props.filter);
    if (stored && stored.mode === "all" && !this.props.count) {
      // A wider scope needs the count that named it; this page states none,
      // so the set it would claim is not the set that was chosen.
      forgetSelection(this.storageKey);
    } else if (stored) {
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
    connected.delete(this);
    publishLineHeight();
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
      this.state = emptySelection();
      this.anchorKey = null;
      if (this.storageKey) forgetSelection(this.storageKey);
    }
    this.showCheckboxes(on);
    publishLineHeight();
    if (announce) this.announce(on ? "Selecting rows." : "Selection off.");
    this.render();
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

  /** Visibility, never presence, so no row moves. */
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
      if (!this.mode) return;
      // Read after the press, not during it.
      //
      // An overlay that closes marks the press spent, but not always before
      // this handler runs: a menu inside the table answers first, while the
      // tooltip and the pickers listen on the document and answer later. A
      // microtask is drained between listeners and would still read false, so
      // the decision waits for the task after the dispatch.
      setTimeout(() => {
        if (!event.defaultPrevented && this.mode) this.onClear();
      });
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
    this.state = selectAllMatching();
    this.anchorKey = null;
    this.render();
    this.announce(`${this.count()} selected, every row matching the filter.`);
  }

  /** What an act on the selection leaves behind: nothing kept, mode off. */
  forgetAndClose(): void {
    this.setMode(false);
  }

  /** The statement this table stands on, asked for.
   *
   * The change event carries the same value, and is dispatched from
   * `render()` alone -- which at connect runs on the restore branch only,
   * before a descendant element upgrades. So the slot that posts the
   * statement pulls it once rather than waiting for a change that already
   * happened.
   */
  statement(): SelectionStatement {
    return statementFor(this.state, this.props.filter, this.props.count);
  }

  private onClear(): void {
    this.state = emptySelection();
    this.anchorKey = null;
    if (this.storageKey) forgetSelection(this.storageKey);
    this.render();
    this.announce("Selection cleared.");
  }

  private onRowsChanged(): void {
    this.decorateRows();
    // A key this page held and holds no longer has left.
    //
    // One it never held belongs to another page of the same list, which is
    // why the pruning reads what this page had rather than what it has.
    const present = new Set(this.pageKeys());
    const gone = [...this.knownKeys].filter((key) => !present.has(key));
    this.knownKeys = present;
    if (!gone.length) {
      if (this.mode) this.render();
      return;
    }
    this.state = forgetKeys(this.state, gone);
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
      checkbox.checked = isMarked(this.state, key);
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

  /** The line's height while the mode is on, 0 otherwise. */
  lineHeight(): number {
    if (!this.mode || !this.line) return 0;
    return this.line.getBoundingClientRect().height;
  }

  /** Public: jsdom has no layout engine. */
  publishLineHeight(): void {
    publishLineHeight();
  }
}

/** The row's name, without its summary line. */
function identityName(cell: HTMLElement): string {
  const clone = cell.cloneNode(true) as HTMLElement;
  clone.querySelectorAll(CHECKBOX_SELECTOR).forEach((node) => node.remove());
  clone.querySelectorAll("[data-row-summary]").forEach((node) => node.remove());
  return clone.textContent?.trim() ?? "";
}

/** The tallest line any table is showing, for the chrome that shares the
 * corner with it. One page may hold two selectable tables; the toasts stand
 * off whichever of them is open. */
function publishLineHeight(): void {
  const style = document.documentElement.style;
  let tallest = 0;
  for (const table of connected) tallest = Math.max(tallest, table.lineHeight());
  if (!tallest) {
    style.removeProperty(LINE_HEIGHT_PROPERTY);
    return;
  }
  style.setProperty(LINE_HEIGHT_PROPERTY, `${Math.round(tallest)}px`);
}

customElements.define("selectable-table", SelectableTableElement);
