/**
 * <catalog-editor> — the Editions area of the Game form.
 *
 * A new row is a clone of a server-rendered <template>, never a fetch: the
 * server states the markup once and the browser only renumbers it. The
 * hidden count inputs are the posted truth about how many rows there are,
 * so appending a row means bumping the count beside it.
 *
 * Removal never renumbers. The bin states the row's `removed` input and
 * hides the row, leaving it in the form. Renumbering here would have to
 * rewrite every later row's names, ids, labels and the mark's value, and
 * one miss silently writes the wrong row. A re-render numbers afresh; the
 * browser only ever appends.
 */

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

/** Whether the bin has already taken the row this mark sits in. */
function isGoing(mark: HTMLElement): boolean {
  return ROW_SELECTORS.some(
    (selector) => mark.closest<HTMLElement>(selector)?.hidden === true,
  );
}

class CatalogEditorElement extends HTMLElement {
  // htmx can move this node, and a second connect must not bind twice.
  private wired = false;

  connectedCallback(): void {
    if (this.wired) return;
    this.wired = true;
    // One delegated listener, so a cloned row needs no wiring of its own.
    this.addEventListener("click", this.onClick);
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
    if (remove && this.contains(remove)) this.stateRemoved(remove);
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
    last.insertAdjacentHTML(
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
    last.insertAdjacentHTML(
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
    // `hidden` says what this is; the inline display says it in the one
    // place a Tailwind grid/flex utility on the row cannot outrank.
    row.hidden = true;
    row.style.display = "none";
    this.restateMark();
  }

  /**
   * The mark cannot sit on a row that is going, so it falls to one that
   * stays — visibly, while the person is still looking at the page.
   * `games/catalog_form.py` states the same rule for a post that
   * reaches it with the mark on a row nobody can see.
   */
  private restateMark(): void {
    const staying = [
      ...this.querySelectorAll<HTMLInputElement>(MARK_INPUT),
    ].filter((mark) => !isGoing(mark));
    const first = staying[0];
    if (!first || staying.some((mark) => mark.checked)) return;
    first.checked = true;
    first.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

customElements.define("catalog-editor", CatalogEditorElement);
