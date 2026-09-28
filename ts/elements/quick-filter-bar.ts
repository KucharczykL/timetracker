/**
 * QuickFilterBar — the GitHub-style facet row above a list view.
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
import { wirePresetDelete } from "./presets.js";
import {
  readLeafWidget,
  setupDeselectableRadios,
  setupModifierToggles,
} from "./filter-widgets.js";
import { readJSONProp, reportClientError } from "../client-errors.js";
import {
  OverflowItem,
  priorityPlusFitCount,
  priorityPlusTotalWidth,
} from "./priority-plus.js";

// Applied facets spill after idle ones.
interface SpillableFacet extends OverflowItem {
  readonly applied: boolean;
}

// The preset picker's search-select change payload: `last` is
// the picked row, whose data-filter attribute carries the preset's filter
// JSON.
interface PresetChangeDetail {
  name: string;
  values: string[];
  last: { value: string; label: string; data: Record<string, string> } | null;
}

class QuickFilterBarElement extends HTMLElement {
  private applyTarget = "";
  private perPage = "";
  private facets: SpillableFacet[] = [];
  // Fit sequence: applied facets, then idle ones.
  private priority: SpillableFacet[] = [];
  private overflowLabel = "";
  private overflowLabelApplied = "";
  private row: HTMLElement | null = null;
  private overflowHost: HTMLElement | null = null;
  private overflowItems: HTMLElement | null = null;
  private overflowTrigger: HTMLElement | null = null;
  private overflowMark: HTMLElement | null = null;
  private rowGap = 0;
  private reservedWidth = 0;
  // Measured unhidden; re-reading it while hidden answers 0.
  private overflowWidth = 0;
  private resizeObserver: ResizeObserver | null = null;
  private layoutQueued = false;
  private disposePresetDelete: (() => void) | null = null;

  connectedCallback(): void {
    const props = readQuickFilterBarProps(this);
    this.applyTarget = props.applyUrl;
    this.perPage = props.perPage;
    this.overflowLabel = props.overflowLabel;
    this.overflowLabelApplied = props.overflowLabelApplied;
    // Wires the number/string modifier selects (presence disables inputs,
    // BETWEEN reveals the second) and the bool facets' deselectable radios.
    setupModifierToggles(this);
    setupDeselectableRadios(this);
    this.querySelector("form")?.addEventListener("submit", this.onSubmit);
    this.addEventListener("search-select:change", this.onPresetPick);
    const picker = this.querySelector<HTMLElement>("[data-preset-picker]");
    const select = picker?.querySelector<HTMLElement>("search-select");
    const presetApiUrl = select?.getAttribute("search-url")?.split("?")[0];
    if (presetApiUrl) this.disposePresetDelete = wirePresetDelete(this, presetApiUrl);
    this.setupOverflow();
  }

  disconnectedCallback(): void {
    this.querySelector("form")?.removeEventListener("submit", this.onSubmit);
    this.removeEventListener("search-select:change", this.onPresetPick);
    this.disposePresetDelete?.();
    this.disposePresetDelete = null;
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
  }

  // A pick inside the Load-preset picker navigates to the list carrying the
  // preset's filter JSON. Facet search-selects bubble the same event; the
  // [data-preset-picker] guard scopes this to the picker.
  private onPresetPick = (event: Event): void => {
    const detail = (event as CustomEvent<PresetChangeDetail>).detail;
    if (!detail?.last) return;
    const picker = (event.target as HTMLElement | null)?.closest<HTMLElement>(
      "[data-preset-picker]",
    );
    if (!picker || !this.contains(picker)) return;
    try {
      const raw = detail.last.data.filter ?? "";
      const filter = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
      // Preset state replaces live URL state.
      const sort = detail.last.data.sort ?? "";
      const perPage = detail.last.data.per_page ?? "";
      this.navigate(applyUrl(this.applyTarget, filter, sort, perPage));
    } catch (error) {
      reportClientError("quick-filter-bar[preset]", String(error));
      // Keep the "preset load failed" console substring (e2e crash guard).
      console.error("quick-filter-bar: preset load failed", error);
      window.toast("Preset is not a valid filter.", "error");
    }
  };

  // ── Priority-plus facet collapsing ────────────────────────────────
  // GitHub-style continuous collapse: no breakpoints. The row is watched by a
  // ResizeObserver; on every width change the facets that no longer fit are
  // MOVED (same DOM nodes — widget state, listeners and serializer scope all
  // survive) into the "⋯" overflow dropdown and moved back as the row widens.
  // Row and menu keep declared order.

  private setupOverflow(): void {
    this.row = this.querySelector<HTMLElement>("[data-quick-row]");
    this.overflowHost = this.querySelector<HTMLElement>("[data-quick-overflow]");
    this.overflowItems = this.querySelector<HTMLElement>(
      "[data-quick-overflow-items]",
    );
    this.overflowTrigger = this.querySelector<HTMLElement>(
      "[data-quick-overflow-trigger]",
    );
    this.overflowMark = this.querySelector<HTMLElement>("[data-quick-overflow-mark]");
    if (!this.row) return;
    if (!this.overflowHost || !this.overflowItems) {
      reportClientError("quick-filter-bar", "overflow host or items missing", {
        toast: false,
      });
      return;
    }
    // The collapse still works without the mark.
    if (!this.overflowTrigger || !this.overflowMark) {
      reportClientError("quick-filter-bar", "overflow trigger or mark missing", {
        toast: false,
      });
    }
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
      applied: element.hasAttribute("data-quick-facet-applied"),
    }));
    this.priority = [
      ...this.facets.filter((facet) => facet.applied),
      ...this.facets.filter((facet) => !facet.applied),
    ];
    this.overflowHost.classList.remove("hidden");
    this.overflowWidth = this.overflowHost.offsetWidth;
    this.overflowHost.classList.add("hidden");
    // Every non-facet child is permanent row furniture.
    //
    // Reading only the host's following siblings missed the leading field, so
    // the facets claimed room that was taken and the row wrapped instead of
    // collapsing one. The host is measured above, unhidden, and added once.
    let furnitureWidth = 0;
    for (const child of Array.from(this.row.children)) {
      if (child === this.overflowHost) continue;
      if ((child as HTMLElement).matches("[data-quick-facet]")) continue;
      furnitureWidth += (child as HTMLElement).offsetWidth + this.rowGap;
    }
    this.reservedWidth = furnitureWidth + this.overflowWidth + this.rowGap;

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
    const facetWidths = this.priority.map((facet) => facet.width);
    const totalFacetsWidth = priorityPlusTotalWidth(facetWidths, this.rowGap);
    const furnitureOnly = this.reservedWidth - this.rowGap - this.overflowWidth;
    let fitCount: number;
    if (totalFacetsWidth + Math.max(furnitureOnly, 0) <= rowWidth) {
      fitCount = this.priority.length;
    } else {
      const available = rowWidth - this.reservedWidth;
      fitCount = priorityPlusFitCount(facetWidths, available, this.rowGap);
    }
    const kept = new Set(this.priority.slice(0, fitCount));
    const inRow = this.facets.filter((facet) => kept.has(facet));
    const spilled = this.facets.filter((facet) => !kept.has(facet));

    // Moves only misplaced facets.
    let successor: Element = overflowHost;
    for (const facet of [...inRow].reverse()) {
      if (facet.element.nextElementSibling !== successor) {
        row.insertBefore(facet.element, successor);
      }
      successor = facet.element;
    }
    // Unchanged menu stays put: keeps open panels.
    const menuOrder = Array.from(overflowItems.children);
    const menuInOrder =
      menuOrder.length === spilled.length &&
      spilled.every((facet, index) => menuOrder[index] === facet.element);
    if (!menuInOrder) {
      for (const facet of spilled) overflowItems.appendChild(facet.element);
    }

    overflowHost.classList.toggle("hidden", spilled.length === 0);
    const holdsApplied = spilled.some((facet) => facet.applied);
    this.overflowMark?.classList.toggle("invisible", !holdsApplied);
    this.overflowTrigger?.setAttribute(
      "aria-label",
      holdsApplied ? this.overflowLabelApplied : this.overflowLabel,
    );
  }

  // Overridable so tests can assert the target without a real navigation.
  protected navigate(url: string): void {
    window.location.href = url;
  }

  private onSubmit = (event: Event): void => {
    event.preventDefault();
    // Page size is server-normalized; the raw URL may be invalid.
    const params = new URLSearchParams(window.location.search);
    const sort = params.get("sort") ?? "";
    this.navigate(applyUrl(this.applyTarget, this.serialize(), sort, this.perPage));
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
        const path = readJSONProp<string[]>(widget, "data-path", []);
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
