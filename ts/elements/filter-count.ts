import { readFilterCountProps } from "../generated/props.js";
import { FILTER_TREE_CHANGE_EVENT, FilterGroupElement } from "./filter-group.js";

// <filter-count> — live result-count badge for the nested filter builder (#195).
//
// Watches the page's <filter-group> for `filter-tree-change` events, debounces,
// and fetches the count endpoint for the group's current (incomplete-pruned)
// filter. States: "Counting…" (debounced or in-flight), "≈ N games" (settled),
// "count unavailable" (endpoint/network error) — never a bare 0 from an error.
//
// There is exactly one <filter-group> per builder (its nested groups are plain
// DOM, not separate custom elements), so the bubbled event's target is always
// that root group and `serializeForQuery()` returns the whole tree, read live
// from the widgets.

const DEBOUNCE_MS = 300;

// Must match the class the server bakes onto the initial <span> (see the
// FilterCount builder) so a fallback-created label looks identical.
const LABEL_CLASS = "text-type-body text-body";

export const COUNTING_TEXT = "Counting…";
export const UNAVAILABLE_TEXT = "count unavailable";

// The count endpoint's response shape (mirrors games.api.FilterCountOut).
interface CountResponse {
  count: number;
}

// The settled-count label. Exact `.count()`; the "≈" signals only that it
// tracks the last *settled* filter and may lag an in-progress edit.
export function totalText(
  count: number,
  nounSingular: string,
  nounPlural: string,
): string {
  return `≈ ${count} ${count === 1 ? nounSingular : nounPlural}`;
}

export function countEndpointUrl(
  endpoint: string,
  model: string,
  filterJson: string,
): string {
  return `${endpoint}?model=${encodeURIComponent(model)}&filter=${encodeURIComponent(filterJson)}`;
}

function isFilterGroup(element: Element): element is FilterGroupElement {
  return (
    element.tagName.toLowerCase() === "filter-group" &&
    typeof (element as Partial<FilterGroupElement>).serializeForQuery === "function"
  );
}

export class FilterCountElement extends HTMLElement {
  private model = "";
  private nounSingular = "";
  private nounPlural = "";
  private endpoint = "";
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private abortController: AbortController | null = null;
  // Monotonic id: a response whose id is no longer the latest is discarded, so a
  // slow earlier request cannot overwrite a newer count (AbortController stops the
  // in-flight one, this guards the just-completed one).
  private requestSequence = 0;
  private changeListener: ((event: Event) => void) | null = null;

  connectedCallback(): void {
    const props = readFilterCountProps(this);
    this.model = props.model;
    this.nounSingular = props.nounSingular;
    this.nounPlural = props.nounPlural;
    this.endpoint = props.endpoint;

    this.changeListener = (event: Event): void => {
      const target = event.target;
      if (target instanceof HTMLElement && isFilterGroup(target)) {
        this.scheduleCount(target);
      }
    };
    document.addEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);

    // Initial count — only if the group is already upgraded and ready (element
    // upgrade order is not guaranteed). Otherwise the first change event drives it.
    const group = document.querySelector("filter-group");
    if (group && isFilterGroup(group)) {
      this.scheduleCount(group);
    }
  }

  disconnectedCallback(): void {
    if (this.changeListener) {
      document.removeEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);
      this.changeListener = null;
    }
    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.abortController?.abort();
    this.abortController = null;
  }

  private scheduleCount(group: FilterGroupElement): void {
    this.render(COUNTING_TEXT);
    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
    }
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      void this.runCount(group);
    }, DEBOUNCE_MS);
  }

  private async runCount(group: FilterGroupElement): Promise<void> {
    this.abortController?.abort();
    const controller = new AbortController();
    this.abortController = controller;
    const sequence = ++this.requestSequence;

    try {
      // serializeForQuery reads every live widget; a throw here must also degrade
      // to "count unavailable" rather than escape as an unhandled rejection that
      // freezes the badge on "Counting…".
      const filterJson = JSON.stringify(group.serializeForQuery());
      const url = countEndpointUrl(this.endpoint, this.model, filterJson);
      const response = await fetch(url, { signal: controller.signal });
      if (sequence !== this.requestSequence) return;
      if (!response.ok) {
        this.render(UNAVAILABLE_TEXT);
        return;
      }
      const data = (await response.json()) as CountResponse;
      if (sequence !== this.requestSequence) return;
      this.render(totalText(data.count, this.nounSingular, this.nounPlural));
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (sequence !== this.requestSequence) return;
      this.render(UNAVAILABLE_TEXT);
    }
  }

  // Update the label in place, preserving the server-rendered <span>'s classes.
  private render(text: string): void {
    let label = this.querySelector("span");
    if (!label) {
      label = document.createElement("span");
      label.className = LABEL_CLASS;
      this.appendChild(label);
    }
    label.textContent = text;
  }
}

customElements.define("filter-count", FilterCountElement);
