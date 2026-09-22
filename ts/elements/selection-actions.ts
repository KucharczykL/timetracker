/** <selection-actions> — the acts the selection line offers.
 *
 * The slot holds one form and one submit for each act. This writes what
 * the table stands on into the form's hidden field, and takes the submits
 * out of reach while nothing is selected.
 */

import { SelectionStatement } from "./selection-statement.js";
import {
  priorityPlusFitCount,
  priorityPlusTotalWidth,
} from "./priority-plus.js";

const STATEMENT = "[data-selection-statement]";
const SUBMITS = 'button[type="submit"]';
const CHANGE = "selectable-table:change";
const HOST = "selectable-table";
const LINE = "[data-selection-line]";
const CONTROLS = "[data-selection-controls]";
const ACTS_ROW = "[data-selection-acts-row]";
const ACT = "[data-selection-act]";
const OVERFLOW = "[data-selection-overflow]";
const OVERFLOW_ITEMS = "[data-selection-overflow-items]";

/** One act, and the width it takes in the line. */
interface OverflowAct {
  element: HTMLElement;
  width: number;
}

interface StatementHost extends HTMLElement {
  statement(): SelectionStatement;
}

/** The table this slot stands in, once it can answer.
 *
 * An element whose module runs before the table's has not upgraded, so it
 * carries no `statement` yet. Its later change events still reach this
 * one, which is why the subscription is never conditional on this answer.
 */
function askable(host: Element | null): StatementHost | null {
  const candidate = host as (Partial<StatementHost> & HTMLElement) | null;
  return candidate && typeof candidate.statement === "function"
    ? (candidate as StatementHost)
    : null;
}

/** How many rows a statement names. */
export function statementCount(statement: SelectionStatement): number {
  if (statement.mode === "some") return statement.keys.length;
  return Math.max(statement.count - statement.except.length, 0);
}

class SelectionActionsElement extends HTMLElement {
  // Set by the press, and cleared when the page outlives it. The table
  // forgets the selection while the form is being read, so what a person
  // pressed is what posts; a page that comes back is choosing again.
  private posted = false;
  private host: Element | null = null;
  private field: HTMLInputElement | null = null;
  // ── Priority-plus overflow ──────────────────────────────────────
  // The line, not the controls: the controls row is a flex item, so its
  // own width is what its content takes. Measuring room in it would shrink
  // as acts left it, and every act would end up behind the trigger.
  private line: HTMLElement | null = null;
  private controls: HTMLElement | null = null;
  private actsRow: HTMLElement | null = null;
  private overflowHost: HTMLElement | null = null;
  private overflowItems: HTMLElement | null = null;
  private acts: OverflowAct[] = [];
  // Taken the first time the line is shown, and never again: every width
  // reads 0 under the `hidden` the table clears at the first press, and
  // widths taken from inside the panel are the panel's, not the row's.
  private measured = false;
  private rowGap = 0;
  private actGap = 0;
  private furnitureWidth = 0;
  private overflowWidth = 0;
  private resizeObserver: ResizeObserver | null = null;
  private layoutQueued = false;

  connectedCallback(): void {
    this.field = this.querySelector<HTMLInputElement>(STATEMENT);
    if (!this.field) return;
    this.posted = false;
    this.addEventListener("submit", this.onSubmit);
    window.addEventListener("pageshow", this.onPageShow);
    // Ahead of the table: the row the acts lay out in is the line's, and a
    // slot standing outside a table would otherwise render a line that
    // wraps rather than one that collapses.
    this.setupOverflow();
    this.host = this.closest(HOST);
    if (!this.host) return;
    // Subscribed whether or not the table can answer yet.
    this.host.addEventListener(CHANGE, this.onChange);
    // The event is dispatched on the table, and only from its render, which
    // at connect runs on the restore branch alone -- before this element
    // upgrades. So a restored selection is asked for rather than waited on.
    const asked = askable(this.host);
    if (asked) this.write(asked.statement());
  }

  disconnectedCallback(): void {
    this.removeEventListener("submit", this.onSubmit);
    window.removeEventListener("pageshow", this.onPageShow);
    this.host?.removeEventListener(CHANGE, this.onChange);
    this.host = null;
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
  }

  // ── Priority-plus overflow ────────────────────────────────────────
  // The acts that no longer fit are MOVED into the trailing overflow
  // dropdown, rightmost first, and moved back as the line widens. The same
  // nodes travel, and the panel sits inside the one form, so a moved submit
  // still posts the one statement its `formaction` names.

  private setupOverflow(): void {
    this.line = this.closest<HTMLElement>(LINE);
    this.controls = this.closest<HTMLElement>(CONTROLS);
    this.actsRow = this.querySelector<HTMLElement>(ACTS_ROW);
    this.overflowHost = this.querySelector<HTMLElement>(OVERFLOW);
    this.overflowItems = this.querySelector<HTMLElement>(OVERFLOW_ITEMS);
    if (
      !this.line ||
      !this.controls ||
      !this.actsRow ||
      !this.overflowHost ||
      !this.overflowItems
    ) {
      return;
    }
    if (!this.actsRow.querySelector(ACT)) return;
    if (typeof ResizeObserver !== "undefined") {
      this.resizeObserver = new ResizeObserver(() => this.queueLayout());
      this.resizeObserver.observe(this.line);
    }
    this.layoutActs();
  }

  private queueLayout(): void {
    if (this.layoutQueued) return;
    this.layoutQueued = true;
    requestAnimationFrame(() => {
      this.layoutQueued = false;
      this.layoutActs();
    });
  }

  /** Take every width, while every act still stands in the row.
   *
   * Answers false while the line is hidden, which is its state until the
   * first press: `offsetWidth` inside a `display:none` ancestor is 0, and
   * zeros cached here would spill every act for the life of the page.
   */
  private measure(): boolean {
    if (this.measured) return true;
    const line = this.line;
    const controls = this.controls;
    const actsRow = this.actsRow;
    const overflowHost = this.overflowHost;
    if (!line || !controls || !actsRow || !overflowHost) return false;
    if (!line.clientWidth) return false;
    const lineGap = parseFloat(getComputedStyle(line).columnGap) || 0;
    this.rowGap = parseFloat(getComputedStyle(controls).columnGap) || 0;
    this.actGap = parseFloat(getComputedStyle(actsRow).columnGap) || 0;
    this.acts = Array.from(actsRow.querySelectorAll<HTMLElement>(ACT)).map(
      (element) => ({ element, width: element.offsetWidth }),
    );
    overflowHost.classList.remove("hidden");
    this.overflowWidth = overflowHost.offsetWidth;
    overflowHost.classList.add("hidden");
    // Everything the line holds beside the acts: the controls standing
    // before this slot, and the line's own furniture around them.
    //
    // The child to skip is the one holding this element, never this element:
    // the slot sits in a wrapper of its own, so comparing identity counted
    // every act as furniture as well and left the line no room at all.
    this.furnitureWidth = 0;
    for (const child of Array.from(controls.children)) {
      if (child.contains(this)) continue;
      this.furnitureWidth += (child as HTMLElement).offsetWidth + this.rowGap;
    }
    for (const child of Array.from(line.children)) {
      if (child.contains(this)) continue;
      this.furnitureWidth += (child as HTMLElement).offsetWidth + lineGap;
    }
    this.measured = true;
    return true;
  }

  /** Public for tests: jsdom has no layout, so widths are stubbed and this
   *  is called rather than waited on. */
  layoutActs(): void {
    if (!this.measure()) return;
    const actsRow = this.actsRow;
    const overflowHost = this.overflowHost;
    const overflowItems = this.overflowItems;
    const line = this.line;
    if (!line || !actsRow || !overflowHost || !overflowItems || !this.acts.length) {
      return;
    }

    const widths = this.acts.map((act) => act.width);
    // First without the trigger's own reserve: where every act fits beside
    // the furniture, nothing spills and the trigger stays away.
    let fitCount: number;
    if (
      priorityPlusTotalWidth(widths, this.actGap) + this.furnitureWidth <=
      line.clientWidth
    ) {
      fitCount = this.acts.length;
    } else {
      const available =
        line.clientWidth -
        this.furnitureWidth -
        this.overflowWidth -
        this.actGap;
      fitCount = priorityPlusFitCount(widths, available, this.actGap);
    }

    this.acts.forEach((act, index) => {
      if (index >= fitCount && act.element.parentElement !== overflowItems) {
        overflowItems.appendChild(act.element);
      }
    });
    // Declaration order, in the row and in the panel alike: an act that
    // travelled and came back would otherwise trail the ones that stayed.
    for (let index = fitCount - 1; index >= 0; index--) {
      const element = this.acts[index].element;
      const successor =
        index + 1 < fitCount ? this.acts[index + 1].element : overflowHost;
      if (element.parentElement !== actsRow || element.nextElementSibling !== successor) {
        actsRow.insertBefore(element, successor);
      }
    }
    for (let index = fitCount; index < this.acts.length; index++) {
      const element = this.acts[index].element;
      if (element.nextElementSibling !== null || element.parentElement !== overflowItems) {
        overflowItems.appendChild(element);
      }
    }
    overflowHost.classList.toggle("hidden", fitCount === this.acts.length);
  }

  private readonly onSubmit = (): void => {
    this.posted = true;
  };

  /** A page that came back is a page choosing again.
   *
   * `connectedCallback` does not run for a restored document, so the latch
   * the press set would otherwise stand for the life of the tab, and the
   * next press would post the statement of the press before it.
   */
  private readonly onPageShow = (event: PageTransitionEvent): void => {
    if (!event.persisted) return;
    this.posted = false;
    const asked = askable(this.host);
    this.write(asked ? asked.statement() : { mode: "some", keys: [] });
  };

  private readonly onChange = (event: Event): void => {
    if (this.posted) return;
    this.write((event as CustomEvent<SelectionStatement>).detail);
  };

  private write(statement: SelectionStatement): void {
    if (!this.field) return;
    this.field.value = JSON.stringify(statement);
    const nothing = statementCount(statement) === 0;
    for (const submit of this.querySelectorAll<HTMLButtonElement>(SUBMITS)) {
      submit.disabled = nothing;
    }
  }
}

customElements.define("selection-actions", SelectionActionsElement);
