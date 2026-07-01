import { readFilterSummaryProps } from "../generated/props.js";
import { FILTER_TREE_CHANGE_EVENT, FilterGroupElement } from "./filter-group.js";
import { summarize } from "./filter-tree/summary.js";
import type { SummaryContext, SummaryModel } from "./filter-tree/summary.js";
import type { FieldMeta, GroupNode } from "./filter-tree/types.js";

// <filter-summary> — read-only English readout of the sibling <filter-group>'s
// current filter tree (#194 summarize(), mounted for #196). Self-wiring like
// <filter-count>: listens on document for filter-tree-change, rebuilds text from
// group.getFilledTree() (filled-but-unpruned, so incomplete leaves show "…").

const LABEL_CLASS = "text-sm text-body";

// Canonical empty root group — summarize() returns "<Label> (all)." for this.
const EMPTY_TREE: GroupNode = { kind: "group", id: "root", connective: "AND", negate: false, children: [] };

// One reachable model's bundle as it arrives in the `models` prop JSON. `columns`
// entries are ComparableColumn objects ({value,label,group,operators}); the summary
// needs only value+label.
interface ModelBundleJson {
  fields: FieldMeta[];
  columns?: { value: string; label: string }[];
}

function isFilterGroup(element: Element): element is FilterGroupElement {
  return (
    element.tagName.toLowerCase() === "filter-group" &&
    typeof (element as Partial<FilterGroupElement>).getFilledTree === "function"
  );
}

export class FilterSummaryElement extends HTMLElement {
  private context: SummaryContext = { modelKey: "", modelLabel: "", models: {} };
  private changeListener: ((event: Event) => void) | null = null;

  connectedCallback(): void {
    const props = readFilterSummaryProps(this);
    this.context = {
      modelKey: props.model,
      modelLabel: props.modelLabel,
      models: this.parseModels(props.models),
    };

    this.changeListener = (event: Event): void => {
      const target = event.target;
      if (target instanceof HTMLElement && isFilterGroup(target)) this.update(target);
    };
    document.addEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);

    const group = document.querySelector("filter-group");
    if (group && isFilterGroup(group)) {
      this.update(group);
    } else {
      // The group is not yet upgraded (element upgrade order is not guaranteed).
      // Render the "all" state from an empty tree so the label is immediately
      // present; the group's initial connect dispatch (or the first user edit)
      // will overwrite it with the real tree once the group connects.
      this.renderText(summarize(EMPTY_TREE, this.context));
    }
  }

  disconnectedCallback(): void {
    if (this.changeListener) {
      document.removeEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);
      this.changeListener = null;
    }
  }

  private parseModels(raw: string): Record<string, SummaryModel> {
    const models: Record<string, SummaryModel> = {};
    let bundles: Record<string, ModelBundleJson> = {};
    if (raw) {
      try {
        bundles = JSON.parse(raw) as Record<string, ModelBundleJson>;
      } catch {
        console.warn("filter-summary: malformed models prop");
      }
    }
    for (const [key, bundle] of Object.entries(bundles)) {
      const fields = new Map<string, FieldMeta>();
      for (const meta of bundle.fields) fields.set(meta.name, meta);
      const columns = new Map<string, string>();
      for (const column of bundle.columns ?? []) columns.set(column.value, column.label);
      models[key] = { fields, columns: columns.size ? columns : undefined };
    }
    return models;
  }

  private update(group: FilterGroupElement): void {
    this.renderText(summarize(group.getFilledTree(), this.context));
  }

  private renderText(text: string): void {
    let label = this.querySelector("span");
    if (!label) {
      label = document.createElement("span");
      label.className = LABEL_CLASS;
      this.appendChild(label);
    }
    label.textContent = text;
  }
}

customElements.define("filter-summary", FilterSummaryElement);
