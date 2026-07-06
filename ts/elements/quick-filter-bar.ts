/**
 * QuickFilterBar — the GitHub-style facet row above a list view (#197).
 *
 * The facets are a small form: Apply (or Enter in a facet input) serializes
 * ONLY the facet criteria (strict — flat single-segment data-path widgets,
 * nothing merged from the wider filter) and navigates via applyUrl. That
 * strictness is what guarantees the bar's output always satisfies the
 * server-side is_quick_editable predicate, so a filter the bar produced
 * reloads as editable. The degraded "Advanced filter active" state is
 * server-rendered plain links and never mounts this element.
 */
import type { LeafWidgetKind } from "../generated/filter-metadata.js";
import { readQuickFilterBarProps } from "../generated/props.js";
import { applyUrl } from "./filter-url.js";
import {
  parseJSONAttr,
  readLeafWidget,
  setupModifierToggles,
} from "./filter-widgets.js";

// One collapsible facet: the <drop-down data-quick-facet> node and its
// natural width in the row (measured once — ghost triggers have stable,
// label-driven widths).
interface OverflowFacet {
  element: HTMLElement;
  width: number;
}

class QuickFilterBarElement extends HTMLElement {
  private applyTarget = "";
  private facets: OverflowFacet[] = [];
  private row: HTMLElement | null = null;
  private overflowHost: HTMLElement | null = null;
  private overflowItems: HTMLElement | null = null;
  private rowGap = 0;
  private reservedWidth = 0;
  private resizeObserver: ResizeObserver | null = null;
  private layoutQueued = false;

  connectedCallback(): void {
    this.applyTarget = readQuickFilterBarProps(this).applyUrl;
    // Wires the number/string modifier selects (presence disables inputs,
    // BETWEEN reveals the second) — same delegated hook the flat bar uses.
    setupModifierToggles(this);
    this.querySelector("form")?.addEventListener("submit", this.onSubmit);
    this.setupOverflow();
  }

  disconnectedCallback(): void {
    this.querySelector("form")?.removeEventListener("submit", this.onSubmit);
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
  }

  // ── Priority-plus facet collapsing (#315) ────────────────────────────────
  // GitHub-style continuous collapse: no breakpoints. The row is watched by a
  // ResizeObserver; on every width change the facets that no longer fit are
  // MOVED (same DOM nodes — widget state, listeners and serializer scope all
  // survive) into the "⋯" overflow dropdown, rightmost first, and moved back
  // as the row widens.

  private setupOverflow(): void {
    this.row = this.querySelector<HTMLElement>("[data-quick-row]");
    this.overflowHost = this.querySelector<HTMLElement>("[data-quick-overflow]");
    this.overflowItems = this.querySelector<HTMLElement>(
      "[data-quick-overflow-items]",
    );
    if (!this.row || !this.overflowHost || !this.overflowItems) return;
    const facetElements = Array.from(
      this.row.querySelectorAll<HTMLElement>(":scope > [data-quick-facet]"),
    );
    if (!facetElements.length) return;

    // Measure once, while everything is in the row. The overflow trigger is
    // server-rendered hidden — unhide it for its own measurement.
    this.rowGap = parseFloat(getComputedStyle(this.row).columnGap) || 0;
    this.facets = facetElements.map((element) => ({
      element,
      width: element.offsetWidth,
    }));
    this.overflowHost.classList.remove("hidden");
    const overflowWidth = this.overflowHost.offsetWidth;
    this.overflowHost.classList.add("hidden");
    // Everything after the overflow host (the Apply/Clear group) is
    // permanent row furniture the facets must leave room for.
    let furnitureWidth = 0;
    let sibling = this.overflowHost.nextElementSibling;
    while (sibling) {
      furnitureWidth += (sibling as HTMLElement).offsetWidth + this.rowGap;
      sibling = sibling.nextElementSibling;
    }
    this.reservedWidth = furnitureWidth + overflowWidth + this.rowGap;

    if (typeof ResizeObserver !== "undefined") {
      this.resizeObserver = new ResizeObserver(() => this.queueLayout());
      this.resizeObserver.observe(this.row);
    }
    this.layoutOverflow();
  }

  private queueLayout(): void {
    if (this.layoutQueued) return;
    this.layoutQueued = true;
    requestAnimationFrame(() => {
      this.layoutQueued = false;
      this.layoutOverflow();
    });
  }

  // Public for tests (jsdom has no layout engine, so tests stub the widths
  // and call this directly).
  layoutOverflow(): void {
    const row = this.row;
    const overflowHost = this.overflowHost;
    const overflowItems = this.overflowItems;
    if (!row || !overflowHost || !overflowItems || !this.facets.length) return;

    const rowWidth = row.clientWidth;
    // First try without the "⋯" reserve: if every facet fits alongside the
    // permanent furniture, nothing collapses.
    const totalFacetsWidth = this.facets.reduce(
      (sum, facet) => sum + facet.width + this.rowGap,
      0,
    );
    const furnitureOnly = this.reservedWidth - this.rowGap - overflowHost.offsetWidth;
    let fitCount: number;
    if (totalFacetsWidth + Math.max(furnitureOnly, 0) <= rowWidth) {
      fitCount = this.facets.length;
    } else {
      let used = 0;
      fitCount = 0;
      const available = rowWidth - this.reservedWidth;
      for (const facet of this.facets) {
        used += facet.width + this.rowGap;
        if (used > available) break;
        fitCount += 1;
      }
    }

    this.facets.forEach((facet, index) => {
      if (index < fitCount) {
        if (facet.element.parentElement !== row) {
          row.insertBefore(facet.element, overflowHost);
        }
      } else if (facet.element.parentElement !== overflowItems) {
        overflowItems.appendChild(facet.element);
      }
    });
    // Order inside the row: re-inserting fit facets before the overflow host
    // in facet order keeps the original sequence stable even after round
    // trips through the overflow panel.
    for (let index = fitCount - 1; index >= 0; index--) {
      const element = this.facets[index].element;
      const successor =
        index + 1 < fitCount ? this.facets[index + 1].element : overflowHost;
      if (element.nextElementSibling !== successor) {
        row.insertBefore(element, successor);
      }
    }
    overflowHost.classList.toggle("hidden", fitCount === this.facets.length);
  }

  // Overridable so tests can assert the target without a real navigation.
  protected navigate(url: string): void {
    window.location.href = url;
  }

  private onSubmit = (event: Event): void => {
    event.preventDefault();
    this.navigate(applyUrl(this.applyTarget, this.serialize()));
  };

  // Strict facets-only serialization: one top-level {facet: criterion} entry
  // per non-empty flat widget. Reading is delegated to the shared
  // readLeafWidget dispatch (which handles the widget root being the
  // <search-select> itself), so a new leaf kind serviced there works here
  // without a parallel switch. The data-kind attribute is trusted as a
  // LeafWidgetKind — the server only stamps kinds from QUICK_FACET_KINDS,
  // contract-tested against the same vocabulary.
  private serialize(): Record<string, unknown> {
    const filter: Record<string, unknown> = {};
    this.querySelectorAll<HTMLElement>("[data-filter-widget]").forEach(
      (widget) => {
        const path = parseJSONAttr<string>(widget, "data-path");
        if (path.length !== 1) return; // facets are flat own-model fields
        const kind = (widget.getAttribute("data-kind") ?? "") as LeafWidgetKind;
        const criterion = readLeafWidget(widget, kind);
        if (criterion !== null) filter[path[0]] = criterion;
      },
    );
    return filter;
  }
}

customElements.define("quick-filter-bar", QuickFilterBarElement);
