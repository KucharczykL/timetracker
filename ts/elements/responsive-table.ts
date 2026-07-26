/** <responsive-table> — priority-plus column dropping for data tables.
 *
 * Wraps a data table's scroll region. It measures every column's natural
 * (max-content) width, then hides the lowest-priority columns until the table
 * fits the region — continuously, with no breakpoints. The decision is
 * expressed as table-level `[&_tr>*:nth-child(N)]:hidden` classes (safelisted
 * in input.css), so a row fragment htmx swaps into the live tbody inherits the
 * current decision without carrying any state of its own.
 *
 * The no-JS fallback (the `max-md` positional hiding) is scoped to
 * `responsive-table:not(:defined)`, so it stops matching the instant this
 * module registers the element; the first measured decision is applied
 * synchronously inside the upgrade, leaving no frame where both systems act.
 *
 * Per-column policy rides on the header cells: data-priority (drop order),
 * data-wrap (free text; measures capped because its max-content width is the
 * whole note on one line), data-shrinkable (the name column, squeezed by the
 * max-md greed below md, so it costs a flat floor there).
 */

// The guaranteed minimum for the squeezed name column below md — the "Name is
// at least ~150px" contract, and deliberately not a per-table constant.
const NAME_FLOOR_PX = 160;

// What a wrap column can cost at most: the 16rem TruncatedText cap plus cell
// padding. Above this it wraps instead of widening the table.
const WRAP_CAP_PX = 304;

// Tailwind's md boundary — the complement of the `max-md` gate on the
// shrinkable column's greed, so cost model and CSS flip on the same edge.
const ABOVE_MD_QUERY = "(min-width: 48rem)";

interface ColumnPolicy {
  priority: number;
  wrap: boolean;
  shrinkable: boolean;
}

/** The class hiding column `index` (0-based) table-wide — one selector covers
 * the header <th> and every row's cell. */
export function hiddenColumnClass(index: number): string {
  return `[&_tr>*:nth-child(${index + 1})]:hidden`;
}

/** Which columns to hide so the total cost fits `availableWidth`.
 *
 * Drop order is priority ascending (least important first), index descending
 * among equals (rightmost first). Column 0 never drops — it is the row header
 * that names every row. Not a prefix fit, which is why this does not reuse
 * priorityPlusFitCount: the QuickFilterBar collapses a row from the right,
 * while a table drops columns from anywhere in the middle.
 */
export function computeHiddenColumns(
  costs: number[],
  priorities: number[],
  availableWidth: number,
): Set<number> {
  const hidden = new Set<number>();
  let total = costs.reduce((sum, cost) => sum + cost, 0);
  if (total <= availableWidth) return hidden;
  const dropOrder = costs
    .map((_, index) => index)
    .slice(1)
    .sort(
      (left, right) => priorities[left] - priorities[right] || right - left,
    );
  for (const index of dropOrder) {
    if (total <= availableWidth) break;
    hidden.add(index);
    total -= costs[index];
  }
  return hidden;
}

/** Each column's fit cost from its measured natural width.
 *
 * A wrap column is flexible (it wraps rather than widening the table), so it
 * costs at most the cap. Below md the shrinkable first column is being
 * squeezed by the max-md greed, so its natural width is not what it will
 * render at — it costs the flat floor the fit must preserve for it.
 */
export function columnCosts(
  policies: ColumnPolicy[],
  naturalWidths: number[],
  aboveMd: boolean,
): number[] {
  return naturalWidths.map((width, index) => {
    const policy = policies[index];
    if (!policy) return width;
    if (policy.wrap) return Math.min(width, WRAP_CAP_PX);
    if (index === 0 && policy.shrinkable && !aboveMd) return NAME_FLOOR_PX;
    return width;
  });
}

export class ResponsiveTableElement extends HTMLElement {
  private region: HTMLElement | null = null;
  private table: HTMLTableElement | null = null;
  private policies: ColumnPolicy[] = [];
  private naturalWidths: number[] = [];
  private hasMeasurement = false;
  private relayoutQueued = false;
  private resizeObserver: ResizeObserver | null = null;
  private mutationObserver: MutationObserver | null = null;

  connectedCallback(): void {
    this.region = this.querySelector<HTMLElement>('[role="region"]');
    this.table = this.querySelector<HTMLTableElement>("table");
    if (!this.region || !this.table) return;
    const headerCells = Array.from(
      this.table.querySelectorAll<HTMLElement>("thead th"),
    );
    // Headerless table: nothing declares column policy, so never drop.
    if (!headerCells.length) return;
    this.policies = headerCells.map((cell) => ({
      priority: Number(cell.getAttribute("data-priority") ?? "1"),
      wrap: cell.hasAttribute("data-wrap"),
      shrinkable: cell.hasAttribute("data-shrinkable"),
    }));

    // Synchronous first decision: the :not(:defined) fallback died when this
    // element was defined, and this replaces it before the next paint.
    this.measureAndFit();

    if (typeof ResizeObserver !== "undefined") {
      // A resize re-measures, not just re-fits: cell padding is responsive
      // (px-2 sm:px-3 lg:px-6) and the shrinkable column's max-md greed
      // corrupts its measurement below md, so widths cached in one
      // breakpoint regime are stale in another. The table is capped at the
      // page size and the work is frame-coalesced, so the extra layout pass
      // is cheap.
      this.resizeObserver = new ResizeObserver(() => this.queueRelayout());
      this.resizeObserver.observe(this.region);
    }
    const body = this.table.querySelector("tbody");
    if (body && typeof MutationObserver !== "undefined") {
      // Content changes (an htmx-swapped row, a cloned session row) change
      // natural widths. Attribute changes are deliberately not observed:
      // measurement itself toggles classes and inline styles, and must not
      // re-trigger itself.
      this.mutationObserver = new MutationObserver(() => this.queueRelayout());
      this.mutationObserver.observe(body, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    }
    // The first measure may have seen fallback-font metrics.
    document.fonts?.ready.then(() => this.queueRelayout());
  }

  disconnectedCallback(): void {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.mutationObserver?.disconnect();
    this.mutationObserver = null;
  }

  private queueRelayout(): void {
    if (this.relayoutQueued) return;
    this.relayoutQueued = true;
    requestAnimationFrame(() => {
      this.relayoutQueued = false;
      this.measureAndFit();
    });
  }

  private measureAndFit(): void {
    const region = this.region;
    const table = this.table;
    if (!region || !table) return;
    // Inside a display:none ancestor everything measures 0; the
    // ResizeObserver re-queues a measure when the region gains width.
    if (region.clientWidth === 0) return;
    this.naturalWidths = this.measureNaturalWidths(table);
    this.hasMeasurement = true;
    this.fit();
  }

  /** Every column's natural width, measured on the live table.
   *
   * Deliberately not an off-screen clone: connecting a clone would upgrade
   * every custom element inside it (row actions, tooltips, dropdowns) and pour
   * duplicate ids into the document. Instead the live table is forced to
   * max-content with the drop classes lifted, read, and reverted — all inside
   * one task, so no intermediate state is ever painted. In table layout the
   * header cell's resolved width IS the column's width, and a column at
   * display:none under the no-JS fallback becomes measurable the moment the
   * classes are lifted.
   */
  private measureNaturalWidths(table: HTMLTableElement): number[] {
    const removedClasses: string[] = [];
    this.policies.forEach((_, index) => {
      const dropClass = hiddenColumnClass(index);
      if (table.classList.contains(dropClass)) {
        table.classList.remove(dropClass);
        removedClasses.push(dropClass);
      }
    });
    const previousWidth = table.style.width;
    table.style.width = "max-content";
    const widths = Array.from(
      table.querySelectorAll<HTMLElement>("thead th"),
    ).map((cell) => cell.getBoundingClientRect().width);
    table.style.width = previousWidth;
    table.classList.add(...removedClasses);
    return widths;
  }

  private fit(): void {
    const region = this.region;
    const table = this.table;
    if (!region || !table || !this.hasMeasurement) return;
    const availableWidth = region.clientWidth;
    if (availableWidth === 0) return;
    const aboveMd = window.matchMedia?.(ABOVE_MD_QUERY).matches ?? true;
    this.applyDecision(this.naturalWidths, availableWidth, aboveMd);
  }

  // Public seam for tests (jsdom has no layout engine, so tests supply the
  // widths and viewport side directly), mirroring layoutOverflow on the
  // QuickFilterBar element.
  applyDecision(
    naturalWidths: number[],
    availableWidth: number,
    aboveMd: boolean,
  ): void {
    const table = this.table;
    if (!table) return;
    const costs = columnCosts(this.policies, naturalWidths, aboveMd);
    const priorities = this.policies.map((policy) => policy.priority);
    const hidden = computeHiddenColumns(costs, priorities, availableWidth);
    this.policies.forEach((_, index) => {
      table.classList.toggle(hiddenColumnClass(index), hidden.has(index));
    });
  }
}

customElements.define("responsive-table", ResponsiveTableElement);
