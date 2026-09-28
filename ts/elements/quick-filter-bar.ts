/**
 * QuickFilterBar — the GitHub-style facet row above a list view.
 *
 * The facets are a small form: Apply (or Enter in a facet input) serializes
 * ONLY the facet criteria (strict — flat single-segment data-path widgets,
 * nothing merged from the wider filter) and navigates via applyUrl. That
 * strictness is what guarantees the bar's output always satisfies the
 * server-side is_quick_editable predicate, so a filter the bar produced
 * reloads as editable. In the degraded "Advanced filter active" state the
 * element holds no form and no row; it only hosts the Presets panel, whose
 * save states the page's filter from the `filter` prop.
 */
import type { LeafWidgetKind } from "../generated/filter-metadata.js";
import { readQuickFilterBarProps } from "../generated/props.js";
import { applyUrl } from "./filter-url.js";
import {
  PRESET_LOAD_EVENT,
  PRESET_SAVE_EVENT,
  PresetSaveRequest,
  PresetState,
} from "./presets.js";
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

// What a save states: the facets, or the degraded pill's page filter.
type StatedFilter =
  | { readonly kind: "facets" }
  | { readonly kind: "page"; readonly filter: Record<string, unknown> }
  | { readonly kind: "unreadable" };

const UNREADABLE_FILTER_REFUSAL = "The filter could not be read — reload the page.";

function readStatedFilter(raw: string): StatedFilter {
  if (!raw) return { kind: "facets" };
  try {
    const filter: unknown = JSON.parse(raw);
    if (typeof filter === "object" && filter !== null && !Array.isArray(filter)) {
      return { kind: "page", filter: filter as Record<string, unknown> };
    }
  } catch {
    // Reported below.
  }
  reportClientError("quick-filter-bar[filter]", raw, { toast: false });
  return { kind: "unreadable" };
}

class QuickFilterBarElement extends HTMLElement {
  private applyTarget = "";
  private perPage = "";
  // The degraded pill's filter; the facets state it otherwise.
  private statedFilter: StatedFilter = { kind: "facets" };
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

  connectedCallback(): void {
    const props = readQuickFilterBarProps(this);
    this.applyTarget = props.applyUrl;
    this.perPage = props.perPage;
    this.overflowLabel = props.overflowLabel;
    this.overflowLabelApplied = props.overflowLabelApplied;
    this.statedFilter = readStatedFilter(props.filter);
    // Wires the number/string modifier selects (presence disables inputs,
    // BETWEEN reveals the second) and the bool facets' deselectable radios.
    setupModifierToggles(this);
    setupDeselectableRadios(this);
    this.querySelector("form")?.addEventListener("submit", this.onSubmit);
    this.addEventListener(PRESET_LOAD_EVENT, this.onPresetLoad);
    this.addEventListener(PRESET_SAVE_EVENT, this.onPresetSave);
    this.setupOverflow();
  }

  disconnectedCallback(): void {
    this.querySelector("form")?.removeEventListener("submit", this.onSubmit);
    this.removeEventListener(PRESET_LOAD_EVENT, this.onPresetLoad);
    this.removeEventListener(PRESET_SAVE_EVENT, this.onPresetSave);
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
  }

  // A loaded preset replaces the live URL state.
  private onPresetLoad = (event: Event): void => {
    event.preventDefault();
    const preset = (event as CustomEvent<PresetState>).detail;
    this.navigate(applyUrl(this.applyTarget, preset.filter, preset.sort, preset.perPage));
  };

  // The facets as they stand, applied or not.
  private onPresetSave = (event: Event): void => {
    event.stopPropagation();
    const request = (event as CustomEvent<PresetSaveRequest>).detail;
    const stated = this.statedFilter;
    if (stated.kind === "unreadable") {
      request.answerWith({ kind: "refused", sentence: UNREADABLE_FILTER_REFUSAL });
      return;
    }
    request.answerWith({
      kind: "state",
      state: {
        filter: stated.kind === "page" ? stated.filter : this.serialize(),
        sort: this.currentSort(),
        perPage: this.perPage,
      },
    });
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
    this.navigate(
      applyUrl(this.applyTarget, this.serialize(), this.currentSort(), this.perPage),
    );
  };

  // Sort from the URL; per-page from the prop, the URL's may be invalid.
  private currentSort(): string {
    return new URLSearchParams(window.location.search).get("sort") ?? "";
  }

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
