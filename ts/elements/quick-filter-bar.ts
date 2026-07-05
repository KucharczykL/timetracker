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
import { readQuickFilterBarProps } from "../generated/props.js";
import { applyUrl } from "./filter-url.js";
import { readFilterSelect } from "./search-select.js";
import {
  buildSetCriterion,
  parseJSONAttr,
  readBoolWidget,
  readDateWidget,
  readNumberWidget,
  readStringWidget,
  setupModifierToggles,
} from "./filter-widgets.js";

// One facet widget's criterion, dispatched by its data-kind. The set branch
// reads the <search-select> pills directly (the widget root IS the
// search-select, so the flat bar's readSearchSelect stamping pass does not
// apply); the scalar branches reuse the shared flat-bar readers.
function readFacetWidget(
  widget: HTMLElement,
  kind: string,
): Record<string, unknown> | null {
  switch (kind) {
    case "set": {
      const { included, excluded, modifier } = readFilterSelect(widget);
      return buildSetCriterion(included, excluded, modifier);
    }
    case "number":
      return readNumberWidget(widget) as Record<string, unknown> | null;
    case "date":
      return readDateWidget(widget) as Record<string, unknown> | null;
    case "string":
      return readStringWidget(widget);
    case "bool":
      return readBoolWidget(widget) as Record<string, unknown> | null;
    default:
      return null;
  }
}

class QuickFilterBarElement extends HTMLElement {
  private applyTarget = "";

  connectedCallback(): void {
    this.applyTarget = readQuickFilterBarProps(this).applyUrl;
    // Wires the number/string modifier selects (presence disables inputs,
    // BETWEEN reveals the second) — same delegated hook the flat bar uses.
    setupModifierToggles(this);
    this.querySelector("form")?.addEventListener("submit", this.onSubmit);
  }

  disconnectedCallback(): void {
    this.querySelector("form")?.removeEventListener("submit", this.onSubmit);
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
  // per non-empty flat widget.
  private serialize(): Record<string, unknown> {
    const filter: Record<string, unknown> = {};
    this.querySelectorAll<HTMLElement>("[data-filter-widget]").forEach(
      (widget) => {
        const path = parseJSONAttr<string>(widget, "data-path");
        if (path.length !== 1) return; // facets are flat own-model fields
        const kind = widget.getAttribute("data-kind") ?? "";
        const criterion = readFacetWidget(widget, kind);
        if (criterion !== null) filter[path[0]] = criterion;
      },
    );
    return filter;
  }
}

customElements.define("quick-filter-bar", QuickFilterBarElement);
