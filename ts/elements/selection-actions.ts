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

interface StatementHost extends HTMLElement {
  statement(): SelectionStatement;
}

function hostOf(element: HTMLElement): StatementHost | null {
  const host = element.closest("selectable-table");
  if (!host) return null;
  const candidate = host as Partial<StatementHost> & HTMLElement;
  // Defined later in the same document, or never: an element that has not
  // upgraded answers no statement, and the change event will bring one.
  return typeof candidate.statement === "function"
    ? (candidate as StatementHost)
    : null;
}

/** How many rows a statement names. */
export function statementCount(statement: SelectionStatement): number {
  if (statement.mode === "some") return statement.keys.length;
  return Math.max(statement.count - statement.except.length, 0);
}

class SelectionActionsElement extends HTMLElement {
  // Set by the press, and never cleared: the table forgets the selection
  // while the form is being read, and what a person pressed is what posts.
  private posted = false;
  private host: StatementHost | null = null;
  private field: HTMLInputElement | null = null;

  connectedCallback(): void {
    this.field = this.querySelector<HTMLInputElement>(STATEMENT);
    if (!this.field) return;
    this.addEventListener("submit", this.onSubmit);
    // The event is dispatched on the table, not here, and a restored
    // selection announces itself before this element exists.
    const host = hostOf(this);
    if (!host) return;
    this.host = host;
    host.addEventListener(CHANGE, this.onChange);
    this.write(host.statement());
  }

  disconnectedCallback(): void {
    this.removeEventListener("submit", this.onSubmit);
    this.host?.removeEventListener(CHANGE, this.onChange);
    this.host = null;
  }

  private readonly onSubmit = (): void => {
    this.posted = true;
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
