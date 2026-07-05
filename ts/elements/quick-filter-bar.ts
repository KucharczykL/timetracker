/**
 * QuickFilterBar — the GitHub-style facet row above a list view (#197).
 *
 * Apply-on-change: any search-select:change bubbling from one of the bar's own
 * facet FilterSelects re-serializes ONLY the facet criteria (strict — flat
 * single-segment data-path set widgets, nothing merged from the wider filter)
 * and navigates via applyUrl. That strictness is what guarantees the bar's
 * output always satisfies the server-side is_quick_editable predicate, so a
 * filter the bar produced reloads as editable. The degraded "Advanced filter
 * active" state is server-rendered plain links and never mounts this element.
 */
import { readQuickFilterBarProps } from "../generated/props.js";
import { applyUrl } from "./filter-url.js";
import { readFilterSelect } from "./search-select.js";
import { buildSetCriterion, parseJSONAttr } from "./filter-widgets.js";

const FACET_WIDGET_SELECTOR = '[data-filter-widget][data-kind="set"]';

class QuickFilterBarElement extends HTMLElement {
  private applyTarget = "";

  connectedCallback(): void {
    this.applyTarget = readQuickFilterBarProps(this).applyUrl;
    this.addEventListener("search-select:change", this.onFacetChange);
  }

  disconnectedCallback(): void {
    this.removeEventListener("search-select:change", this.onFacetChange);
  }

  // Overridable so tests can assert the target without a real navigation.
  protected navigate(url: string): void {
    window.location.href = url;
  }

  // Only changes from the bar's own facet widgets navigate. Today nothing else
  // inside <quick-filter-bar> emits search-select:change, but the guard keeps a
  // future composed child (a preset picker, say) from navigating by accident.
  private onFacetChange = (event: Event): void => {
    const target = event.target as HTMLElement | null;
    const widget = target?.closest<HTMLElement>(FACET_WIDGET_SELECTOR);
    if (!widget || !this.contains(widget)) return;
    this.navigate(applyUrl(this.applyTarget, this.serialize()));
  };

  // Strict facets-only serialization: one top-level {facet: criterion} entry
  // per non-empty flat set widget. Reads each <search-select>'s pill state
  // directly (readFilterSelect) — the widget root IS the search-select, so the
  // flat bar's readSearchSelect stamping pass is unnecessary here.
  private serialize(): Record<string, unknown> {
    const filter: Record<string, unknown> = {};
    this.querySelectorAll<HTMLElement>(FACET_WIDGET_SELECTOR).forEach(
      (widget) => {
        const path = parseJSONAttr<string>(widget, "data-path");
        if (path.length !== 1) return; // facets are flat own-model fields
        const { included, excluded, modifier } = readFilterSelect(widget);
        const criterion = buildSetCriterion(included, excluded, modifier);
        if (criterion !== null) filter[path[0]] = criterion;
      },
    );
    return filter;
  }
}

customElements.define("quick-filter-bar", QuickFilterBarElement);
