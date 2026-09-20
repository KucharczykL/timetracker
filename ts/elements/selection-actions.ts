/** <selection-actions> — the acts the selection line offers.
 *
 * The slot holds one form and one submit for each act. This writes what
 * the table stands on into the form's hidden field, and takes the submits
 * out of reach while nothing is selected.
 */

import { SelectionStatement } from "./selection-statement.js";

const STATEMENT = "[data-selection-statement]";
const SUBMITS = 'button[type="submit"]';
const CHANGE = "selectable-table:change";
const HOST = "selectable-table";

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

  connectedCallback(): void {
    this.field = this.querySelector<HTMLInputElement>(STATEMENT);
    if (!this.field) return;
    this.posted = false;
    this.addEventListener("submit", this.onSubmit);
    window.addEventListener("pageshow", this.onPageShow);
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
