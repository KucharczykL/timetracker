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
