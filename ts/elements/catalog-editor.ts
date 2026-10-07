/**
 * <catalog-editor> — the Editions area of the Game form.
 *
 * A new row is a clone of a server-rendered <template>, never a fetch: the
 * server states the markup once and the browser only renumbers it. The
 * hidden count inputs are the posted truth about how many rows there are,
 * so appending a row means bumping the count beside it.
 *
 * Removal never renumbers. The bin states the row's `removed` input,
 * hides the row and shows the line after it; that line's Undo takes the
 * bin back. Renumbering would have to rewrite every later row's names,
 * ids, labels and the mark's value, and one miss silently writes the
 * wrong row. A re-render numbers afresh; the browser only ever appends.
 *
 * A row's accessible names follow its value.
 */

import {
  CATALOG_NAME_KINDS,
  CATALOG_NAME_SLOT,
  type CatalogNameKind,
} from "../generated/catalog-names.js";
import { SearchSelectElement } from "./search-select.js";

// Where a clone learns its own number. Mirrors the placeholders in
// games/catalog_form.py, which the templates are rendered with.
const EDITION_PLACEHOLDER = "__edition__";
const RELEASE_PLACEHOLDER = "__release__";

/** Which row a clone becomes. An edition template's one row is already
 *  row zero, so it names no release index. */
export interface RowIndices {
  edition: number;
  release?: number;
}

/** The same markup, numbered for the row it is about to become. */
export function renumbered(markup: string, indices: RowIndices): string {
  const numbered = markup.replaceAll(EDITION_PLACEHOLDER, String(indices.edition));
  return indices.release === undefined
    ? numbered
    : numbered.replaceAll(RELEASE_PLACEHOLDER, String(indices.release));
}

// A block and a card both hold their own `removed` input as a direct
// child, and a block holds its cards' ones deeper down.
const OWN_REMOVED_INPUT = ':scope > input[name$="-removed"]';

// The card's own mark, told apart from any control the card hosts.
// Mirrors CHOICE_CARD_MARK_ATTRIBUTE in common/components/choice_card.py.
const MARK_INPUT = "input[data-choice-card]";

// The two rows a mark sits inside. A card goes out on its own, and it
// also goes out under the block that holds it.
const ROW_SELECTORS = ["[data-catalog-release]", "[data-catalog-edition]"];

// A binned row's line, right after it.
const STUB = "[data-catalog-binned]";

// Mirrors CHOSEN_MARK_FIELD in games/catalog_form.py.
const CHOSEN_MARK = 'input[name="catalog-chosen-mark"]';

/** Whether this row states its own removal. */
function statesRemoval(row: HTMLElement): boolean {
  return row.querySelector<HTMLInputElement>(OWN_REMOVED_INPUT)?.value === "on";
}

/** Whether the row this mark sits in is going. */
function isGoing(mark: HTMLElement): boolean {
  return ROW_SELECTORS.some((selector) => {
    const row = mark.closest<HTMLElement>(selector);
    return row !== null && statesRemoval(row);
  });
}

/** The line this row leaves when binned, if drawn. */
function stubOf(row: Element): HTMLElement | null {
  const next = row.nextElementSibling;
  return next instanceof HTMLElement && next.matches(STUB) ? next : null;
}

/** Hidden by attribute and inline display, as the server draws. */
function setOutOfSight(element: HTMLElement, out: boolean): void {
  // `hidden` says what this is; the inline display says it in the one
  // place a Tailwind grid/flex utility on the row cannot outrank.
  element.hidden = out;
  element.style.display = out ? "none" : "";
}

/** Split, not `replace`, so `$` stays literal. */
export function filled(pattern: string, value: string, empty?: string): string {
  if (value === "" && empty !== undefined) return empty;
  return pattern.split(CATALOG_NAME_SLOT).join(value);
}

// Each name kind's control and row.
const FOLLOWED = {
  platform: {
    control: 'search-select[name$="-platform"]',
    row: "[data-catalog-release]",
    element: SearchSelectElement,
  },
  name: { control: 'input[name$="-name"]', row: "[data-catalog-edition]", element: HTMLInputElement },
} as const satisfies Record<
  CatalogNameKind,
  { control: string; row: string; element: typeof HTMLInputElement | typeof SearchSelectElement }
>;

/** Picked label or typed value; null: leave names. */
function shown(control: HTMLInputElement | SearchSelectElement): string | null {
  if (control instanceof HTMLInputElement) return control.value.trim();
  // Before wiring, the server's names stand.
  if (!control.wired) return null;
  return control.heldLabel()?.trim() ?? null;
}

class CatalogEditorElement extends HTMLElement {
  // A DOM move reconnects this node, and a second connect must not bind twice.
  private wired = false;
  // Set while the element moves the mark itself.
  private restating = false;

  connectedCallback(): void {
    // Chromium restores form values after upgrade.
    window.addEventListener("pageshow", this.onPageShow);
    if (this.wired) return;
    this.wired = true;
    // One delegated listener, so a cloned row needs no wiring of its own.
    this.addEventListener("click", this.onClick);
    // Text fields fire `input`; pickers fire a change.
    this.addEventListener("input", this.onInput);
    this.addEventListener("search-select:change", this.onInput);
    this.addEventListener("change", this.onChange);
    this.restateNames();
    // A refused page comes back with the rows the person left, bins and
    // all. The mark is repaired on arrival too, not only on a click.
    this.restateMark();
  }

  disconnectedCallback(): void {
    window.removeEventListener("pageshow", this.onPageShow);
  }

  private onPageShow = (): void => this.restateNames();

  private onInput = (event: Event): void => {
    const target = event.target as HTMLElement;
    for (const kind of CATALOG_NAME_KINDS) {
      if (!target.matches(FOLLOWED[kind].control)) continue;
      const row = target.closest<HTMLElement>(FOLLOWED[kind].row);
      if (row && this.contains(row)) this.restateRow(row, kind);
    }
  };

  /** Every row's names, from current values. */
  private restateNames(): void {
    for (const kind of CATALOG_NAME_KINDS) {
      for (const row of this.querySelectorAll<HTMLElement>(FOLLOWED[kind].row)) {
        this.restateRow(row, kind);
      }
    }
  }

  /** A person's pick of a mark is the chosen one. */
  private onChange = (event: Event): void => {
    const target = event.target as HTMLElement;
    if (this.restating || !(target instanceof HTMLInputElement)) return;
    if (!target.matches(MARK_INPUT) || !target.checked) return;
    const chosen = this.querySelector<HTMLInputElement>(CHOSEN_MARK);
    if (chosen) chosen.value = target.value;
  };

  /** One row's names of one kind, its line's too. */
  private restateRow(row: HTMLElement, kind: CatalogNameKind): void {
    const selector = `[data-catalog-name-of="${kind}"]`;
    const nodes = [
      ...row.querySelectorAll<HTMLElement>(selector),
      ...(stubOf(row)?.querySelectorAll<HTMLElement>(selector) ?? []),
    ];
    if (nodes.length === 0) return;
    const control = row.querySelector(FOLLOWED[kind].control);
    if (!control) {
      console.error(`<catalog-editor> row has no ${kind} control`, row);
      return;
    }
    // Script order may leave it un-upgraded.
    customElements.upgrade(control);
    if (!(control instanceof FOLLOWED[kind].element)) {
      console.error(`<catalog-editor> ${kind} control is the wrong element`, control);
      return;
    }
    const value = shown(control);
    if (value === null) return;
    for (const node of nodes) {
      const pattern = node.dataset.catalogName;
      if (pattern === undefined) {
        console.error("<catalog-editor> name hook has no pattern", node);
        continue;
      }
      const name = filled(pattern, value, node.dataset.catalogNameEmpty);
      // Labelled controls keep children; others hold text.
      if (node.hasAttribute("aria-label")) {
        node.setAttribute("aria-label", name);
        if (node.hasAttribute("title")) node.title = name;
      } else {
        node.textContent = name;
      }
    }
  }

  private onClick = (event: Event): void => {
    const target = event.target as HTMLElement;
    const add = target.closest<HTMLElement>("[data-catalog-add]");
    if (add && this.contains(add)) {
      if (add.dataset.catalogAdd === "edition") this.addEdition();
      else this.addRelease(add);
      return;
    }
    const remove = target.closest<HTMLElement>("[data-catalog-remove]");
    if (remove && this.contains(remove)) {
      this.stateRemoved(remove);
      return;
    }
    const restore = target.closest<HTMLElement>("[data-catalog-restore]");
    if (restore && this.contains(restore)) this.stateRestored(restore);
  };

  private template(kind: "edition" | "release"): HTMLTemplateElement | null {
    return this.querySelector<HTMLTemplateElement>(
      `template[data-catalog-template="${kind}"]`,
    );
  }

  private addEdition(): void {
    const template = this.template("edition");
    const blocks = this.querySelectorAll<HTMLElement>("[data-catalog-edition]");
    const last = blocks[blocks.length - 1];
    if (!template || !last) return;
    (stubOf(last) ?? last).insertAdjacentHTML(
      "afterend",
      renumbered(template.innerHTML, { edition: blocks.length }),
    );
    this.stateCount(
      this.querySelector<HTMLInputElement>('input[name="editions-count"]'),
      blocks.length + 1,
    );
    // A person who binned every row is adding the one the mark falls to.
    this.restateMark();
  }

  private addRelease(button: HTMLElement): void {
    const block = button.closest<HTMLElement>("[data-catalog-edition]");
    const template = this.template("release");
    if (!block || !template) return;
    const edition = Number(block.dataset.catalogEdition);
    const rows = block.querySelectorAll<HTMLElement>("[data-catalog-release]");
    const last = rows[rows.length - 1];
    if (!last || Number.isNaN(edition)) return;
    (stubOf(last) ?? last).insertAdjacentHTML(
      "afterend",
      renumbered(template.innerHTML, { edition, release: rows.length }),
    );
    this.stateCount(
      block.querySelector<HTMLInputElement>('input[name$="-releases-count"]'),
      rows.length + 1,
    );
    this.restateMark();
  }

  private stateCount(input: HTMLInputElement | null, count: number): void {
    if (input) input.value = String(count);
  }

  private stateRemoved(button: HTMLElement): void {
    const row =
      button.closest<HTMLElement>("[data-catalog-release]") ??
      button.closest<HTMLElement>("[data-catalog-edition]");
    if (!row) return;
    const removed = row.querySelector<HTMLInputElement>(OWN_REMOVED_INPUT);
    if (removed) removed.value = "on";
    setOutOfSight(row, true);
    const stub = stubOf(row);
    if (stub) {
      setOutOfSight(stub, false);
      stub.querySelector<HTMLElement>("[data-catalog-restore]")?.focus();
    }
    this.restateMark();
  }

  /** Undo: the row posts as if never binned. */
  private stateRestored(button: HTMLElement): void {
    const stub = button.closest<HTMLElement>(STUB);
    // The row precedes its line; not `closest`.
    // A release line sits inside its Edition, which `closest` finds.
    const row = stub?.previousElementSibling;
    if (!stub || !(row instanceof HTMLElement)) return;
    const removed = row.querySelector<HTMLInputElement>(OWN_REMOVED_INPUT);
    if (removed) removed.value = "";
    setOutOfSight(row, false);
    setOutOfSight(stub, true);
    row.querySelector<HTMLElement>("[data-catalog-remove]")?.focus();
    this.restateMark();
  }

  /** Chosen row while it stays, else fall. */
  private restateMark(): void {
    const staying = [
      ...this.querySelectorAll<HTMLInputElement>(MARK_INPUT),
    ].filter((mark) => !isGoing(mark));
    const chosenValue = this.querySelector<HTMLInputElement>(CHOSEN_MARK)?.value;
    const target =
      staying.find((mark) => chosenValue && mark.value === chosenValue) ??
      staying.find((mark) => mark.checked) ??
      staying[0];
    if (!target || target.checked) return;
    target.checked = true;
    this.restating = true;
    try {
      target.dispatchEvent(new Event("change", { bubbles: true }));
    } finally {
      this.restating = false;
    }
  }
}

customElements.define("catalog-editor", CatalogEditorElement);
