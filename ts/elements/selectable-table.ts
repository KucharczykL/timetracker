/** <selectable-table> — a data table's rows, selectable. */

import "./drop-down.js";
import { DropdownElement } from "./drop-down.js";
import { isRendered } from "../rendered.js";
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
  normalised,
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
const IDENTITY_SELECTOR = "[data-row-identity]";
// Every connected table, so the published height is the tallest line rather
// than whichever table wrote last.
const connected = new Set<SelectableTableElement>();
const ROW_SELECTOR = "tbody tr[data-selection-key]";
const LINE_HEIGHT_PROPERTY = "--selection-line";

export class SelectableTableElement extends HTMLElement {
  private props!: SelectableTableProps;
  private state: SelectionState = emptySelection();
  private anchorKey: string | null = null;
  private line: HTMLElement | null = null;
  private checkAlls: HTMLInputElement[] = [];
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
    this.checkAlls = Array.from(
      this.querySelectorAll<HTMLInputElement>("[data-selection-check-all]"),
    );
    this.countText = this.querySelector("[data-selection-count]");
    this.announcement = this.querySelector("[data-selection-announcement]");
    this.checkboxTemplate = this.querySelector(
      "template[data-selection-checkbox-template]",
    );
    if (!this.line) {
      // A server defect: no line, no selection.
      console.error("<selectable-table> has no [data-selection-line]", this);
      for (const checkAll of this.checkAlls) checkAll.hidden = true;
      return;
    }

    for (const checkAll of this.checkAlls) {
      checkAll.addEventListener("change", () => this.onCheckAll(checkAll));
    }
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
      () => this.forget(),
    );
    this.addEventListener("click", (event) => this.onBodyClick(event));
    this.addEventListener("keydown", (event) => this.onKeyDown(event));

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
      this.setState(stored);
      // Nothing changed for the reader: the page arrived this way.
      if (this.count()) this.render();
      else forgetSelection(this.storageKey);
    }
    // No render otherwise: it would forget storage.
    //
    // An empty render forgets the path's stored value, which another
    // filter of this list may still hold. The server renders the empty
    // state already.

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

  /** Every change; zero rows is empty. */
  private setState(next: SelectionState): void {
    this.state = normalised(next, this.props.count);
  }

  private decorateRows(): void {
    const template = this.checkboxTemplate;
    if (!template) {
      console.error("<selectable-table> has no checkbox template", this);
      return;
    }
    for (const row of this.rows()) {
      const cell = row.querySelector<HTMLElement>('th[scope="row"]');
      if (!cell || cell.querySelector(CHECKBOX_SELECTOR)) continue;
      const checkbox = template.content.firstElementChild?.cloneNode(
        true,
      ) as HTMLInputElement | null;
      if (!checkbox) continue;
      const name = identityName(cell);
      if (!name) console.error("<selectable-table> row has no name", row);
      checkbox.setAttribute("aria-label", name);
      // The row a selectable cell states for it: the name's own line,
      // so the box centres on the name rather than on the summary
      // under it. A cell that states none takes the box itself.
      const identity = cell.querySelector<HTMLElement>(IDENTITY_SELECTOR) ?? cell;
      identity.insertBefore(checkbox, identity.firstChild);
    }
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
    const before = this.count();
    if (mouse.shiftKey && this.anchorKey) {
      this.applyRange(this.anchorKey, key, checkbox.checked);
    } else {
      this.setState(toggleKey(this.state, key));
      this.anchorKey = key;
    }
    this.render();
    this.announceAppearing(before);
  }

  private onKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      // The surface stack spent it first.
      if (this.count() && !event.defaultPrevented) this.onClear();
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
    const before = this.count();
    this.applyRange(this.anchorKey, key, !checkbox.checked);
    this.render();
    this.announceAppearing(before);
  }

  private applyRange(anchorKey: string, targetKey: string, checked: boolean): void {
    const keys = rangeKeys(this.pageKeys(), anchorKey, targetKey);
    this.setState(setPage(this.state, keys, checked));
    this.anchorKey = targetKey;
  }

  private onCheckAll(source: HTMLInputElement): void {
    const before = this.count();
    this.setState(setPage(this.state, this.pageKeys(), source.checked));
    this.anchorKey = null;
    this.render();
    if (!this.announceAppearing(before)) this.announce(this.countSentence());
  }

  private onAllMatching(): void {
    this.setState(selectAllMatching());
    this.anchorKey = null;
    this.render();
    this.announce(`${this.count()} selected, every row matching the filter.`);
  }

  /** An act on the selection empties it. */
  forget(): void {
    this.setState(emptySelection());
    this.anchorKey = null;
    this.render();
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
    this.setState(emptySelection());
    this.anchorKey = null;
    this.render();
    this.announce("Selection cleared.");
  }

  /** Focus target when the line hides. */
  private focusTarget(): HTMLInputElement | null {
    const header = this.checkAlls.find(
      (checkAll) => checkAll.closest("thead") && isRendered(checkAll),
    );
    if (header) return header;
    const rowBox = this.querySelector<HTMLInputElement>(CHECKBOX_SELECTOR);
    return rowBox && isRendered(rowBox) ? rowBox : null;
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
    // Nothing selected: no render, storage kept.
    //
    // An empty render forgets the value another filter keeps.
    if (!this.count()) return;
    if (gone.length) this.setState(forgetKeys(this.state, gone));
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
    for (const checkAll of this.checkAlls) {
      checkAll.checked = all === "checked";
      checkAll.indeterminate = all === "indeterminate";
    }
    if (this.countText) this.countText.textContent = this.countSentence();
    this.showLine(this.count() > 0);
    publishLineHeight();
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

  /** A line that hides hands its focus on. */
  private showLine(shown: boolean): void {
    if (!this.line || this.line.hidden === !shown) return;
    // Read before hiding: focus leaves a hidden element lazily.
    const hadFocus = this.line.contains(document.activeElement);
    // Close first: hiding strands a top-layer panel.
    if (!shown) {
      for (const menu of this.line.querySelectorAll("drop-down")) {
        if (menu instanceof DropdownElement) menu.close();
      }
    }
    this.line.hidden = !shown;
    if (hadFocus && !shown) this.focusTarget()?.focus({ preventScroll: true });
  }

  private announce(sentence: string): void {
    if (this.announcement) this.announcement.textContent = sentence;
  }

  /** Says the line appeared, from zero. */
  private announceAppearing(before: number): boolean {
    if (before || !this.count()) return false;
    this.announce(`${this.countSentence()}. Selection actions follow the table.`);
    return true;
  }

  /** The line's height while it shows, 0 otherwise. */
  lineHeight(): number {
    if (!this.line || this.line.hidden) return 0;
    return this.line.getBoundingClientRect().height;
  }

  /** Public: jsdom has no layout engine. */
  publishLineHeight(): void {
    publishLineHeight();
  }
}

// Text a reader skips, where no clip names.
const UNREAD_SELECTOR = `${CHECKBOX_SELECTOR}, [data-row-summary], [hidden], [aria-hidden="true"]`;
const CLIP_SELECTOR = "[data-truncated-clip]";

/** The row's shown name, once. */
function identityName(cell: HTMLElement): string {
  const identity = cell.querySelector<HTMLElement>(IDENTITY_SELECTOR) ?? cell;
  // Icon titles and tooltips sit outside it.
  const clip = identity.querySelector(CLIP_SELECTOR);
  if (clip) return clip.textContent.trim();
  const clone = identity.cloneNode(true) as HTMLElement;
  clone.querySelectorAll(UNREAD_SELECTOR).forEach((node) => node.remove());
  return clone.textContent.trim();
}

/** The tallest showing line, for the toasts. */
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
