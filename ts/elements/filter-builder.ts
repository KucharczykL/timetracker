import { readFilterBuilderProps } from "../generated/props.js";
import { FILTER_TREE_CHANGE_EVENT, FilterGroupElement } from "./filter-group.js";
import {
  PRESET_LOAD_EVENT,
  PRESET_SAVE_EVENT,
  PresetSaveRequest,
  PresetState,
} from "./presets.js";
import { applyUrl } from "./filter-url.js";

// <filter-builder> — the builder-page toolbar and <preset-panel> host.

// Refuses a save by the rule that disables Apply.
export const INCOMPLETE_SAVE_REFUSAL =
  "Finish or remove the incomplete conditions before saving.";

function isFilterGroup(element: Element | null): element is FilterGroupElement {
  return (
    element instanceof HTMLElement &&
    element.tagName.toLowerCase() === "filter-group" &&
    typeof (element as Partial<FilterGroupElement>).serializeForQuery === "function"
  );
}

export class FilterBuilderElement extends HTMLElement {
  private mode = "";
  private applyTarget = "";
  // Apply and Save preserve list state; loading a preset replaces it.
  private sort = "";
  private perPage = "";
  private incompleteCount = 0;
  private changeListener: ((event: Event) => void) | null = null;

  // Build the toolbar buttons into this element. Called when the element is
  // test-created (no server-rendered children) so tests can querySelector for
  // the data-* hooks without needing Python to render the page. Tests append
  // their own <preset-panel> stand-in.
  private ensureToolbar(): void {
    if (this.querySelector("[data-apply]")) return; // already server-rendered
    this.innerHTML = `
      <div class="flex flex-wrap gap-3 items-center mb-4">
        <button type="button" data-apply="">Apply</button>
        <button type="button" data-clear="" aria-label="Clear filter"></button>
      </div>`;
  }

  connectedCallback(): void {
    const props = readFilterBuilderProps(this);
    this.mode = props.mode;
    this.applyTarget = props.applyUrl;
    this.sort = props.sort;
    this.perPage = props.perPage;

    this.ensureToolbar();
    this.addEventListener("click", this.onClick);
    this.addEventListener(PRESET_LOAD_EVENT, this.onPresetLoad);
    this.addEventListener(PRESET_SAVE_EVENT, this.onPresetSave);
    this.changeListener = (event: Event): void => {
      const detail = (event as CustomEvent<{ incompleteCount: number }>).detail;
      if (detail) {
        this.incompleteCount = detail.incompleteCount;
        this.syncApplyDisabled();
      }
    };
    document.addEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);
    // Seed Apply's disabled state from the server-seeded group NOW — no change
    // event fires on the initial tree, so a prefilled-but-incomplete leaf would
    // otherwise leave Apply wrongly enabled until the first edit.
    const group = this.group();
    if (group) this.incompleteCount = group.getIncompleteCount();
    this.syncApplyDisabled();
  }

  disconnectedCallback(): void {
    if (this.changeListener) {
      document.removeEventListener(FILTER_TREE_CHANGE_EVENT, this.changeListener);
      this.changeListener = null;
    }
    this.removeEventListener("click", this.onClick);
    this.removeEventListener(PRESET_LOAD_EVENT, this.onPresetLoad);
    this.removeEventListener(PRESET_SAVE_EVENT, this.onPresetSave);
  }

  // Overridable so tests can assert the target without a real navigation.
  protected navigate(url: string): void {
    window.location.href = url;
  }

  private group(): FilterGroupElement | null {
    const found = document.querySelector("filter-group");
    return isFilterGroup(found) ? found : null;
  }

  private syncApplyDisabled(): void {
    const apply = this.querySelector<HTMLButtonElement>("[data-apply]");
    if (!apply) return;
    // Disable Apply only when there are partially-filled criteria (field chosen but
    // value missing). A fully-blank filter (no fields started) is valid — it means
    // "show everything" — so incompleteCount from an all-empty tree does not block
    // Apply. serializeForQuery() prunes blank criteria before navigating.
    apply.disabled = this.holdsIncomplete();
  }

  private holdsIncomplete(): boolean {
    const group = this.group();
    const filterIsEmpty =
      !group || Object.keys(group.serializeForQuery()).length === 0;
    return this.incompleteCount > 0 && !filterIsEmpty;
  }

  private onClick = (event: Event): void => {
    const target = event.target as HTMLElement;
    if (target.closest("[data-apply]")) return this.onApply();
    if (target.closest("[data-clear]")) return this.group()?.clear();
  };

  // A loaded preset fills the tree.
  private onPresetLoad = (event: Event): void => {
    const preset = (event as CustomEvent<PresetState>).detail;
    this.group()?.loadFilter(preset.filter);
    this.sort = preset.sort;
    this.perPage = preset.perPage;
  };

  // serialize() misses live widget values.
  private onPresetSave = (event: Event): void => {
    event.stopPropagation();
    const request = (event as CustomEvent<PresetSaveRequest>).detail;
    const group = this.group();
    if (!group) return;
    if (this.holdsIncomplete()) {
      request.refusal = INCOMPLETE_SAVE_REFUSAL;
      return;
    }
    request.state = {
      filter: group.serializeForQuery(),
      sort: this.sort,
      perPage: this.perPage,
    };
  };

  private onApply(): void {
    const group = this.group();
    if (!group) return;
    this.navigate(
      applyUrl(this.applyTarget, group.serializeForQuery(), this.sort, this.perPage),
    );
  }
}

customElements.define("filter-builder", FilterBuilderElement);
