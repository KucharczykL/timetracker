import { readFilterBuilderProps } from "../generated/props.js";
import { FILTER_TREE_CHANGE_EVENT, FilterGroupElement } from "./filter-group.js";
import { PresetDropdown, savePreset, setupPresetDropdown } from "./presets.js";

// <filter-builder> — the builder-page toolbar (#196). Owns Load/Save preset,
// Apply, Clear; drives the sibling <filter-group>. Preset load/save/delete is
// shared with filter-bar.ts via presets.ts (#264).

export function applyUrl(listUrl: string, filter: Record<string, unknown>): string {
  if (Object.keys(filter).length === 0) return listUrl;
  return listUrl + "?filter=" + encodeURIComponent(JSON.stringify(filter));
}

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
  private presetSaveUrl = "";
  private incompleteCount = 0;
  private changeListener: ((event: Event) => void) | null = null;
  private presets: PresetDropdown | null = null;

  // Build the toolbar buttons into this element. Called when the element is
  // test-created (no server-rendered children) so tests can querySelector for
  // the data-* hooks without needing Python to render the page.
  private ensureToolbar(): void {
    if (this.querySelector("[data-apply]")) return; // already server-rendered
    this.innerHTML = `
      <div class="flex flex-wrap gap-3 items-center mb-4">
        <div class="relative">
          <button type="button" data-load-presets="">Load preset ▾</button>
          <div data-preset-dropdown="" class="hidden absolute z-10 mt-1 min-w-[12rem] rounded-lg border border-default-medium bg-body shadow-lg">
            <ul class="py-1"></ul>
          </div>
        </div>
        <input type="text" data-preset-name="" placeholder="Preset name…" />
        <button type="button" data-save-preset="">Save as preset…</button>
        <button type="button" data-apply="">Apply</button>
        <button type="button" data-clear="">Clear</button>
      </div>`;
  }

  connectedCallback(): void {
    const props = readFilterBuilderProps(this);
    this.mode = props.mode;
    this.applyTarget = props.applyUrl;
    this.presetSaveUrl = props.presetSaveUrl;

    this.ensureToolbar();
    this.addEventListener("click", this.onClick);
    this.presets = setupPresetDropdown({
      root: this,
      dropdownSelector: "[data-preset-dropdown]",
      listUrl: props.presetListUrl,
      mode: props.mode,
      onPick: (filter) => {
        // A loadFilter throw (valid JSON, bad filter shape) propagates back
        // into the controller's catch → "not a valid filter" toast.
        this.group()?.loadFilter(filter);
        this.querySelector("[data-preset-dropdown]")?.classList.add("hidden");
      },
    });
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
    this.presets?.dispose();
    this.presets = null;
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
    const group = this.group();
    const filterIsEmpty =
      !group || Object.keys(group.serializeForQuery()).length === 0;
    apply.disabled = this.incompleteCount > 0 && !filterIsEmpty;
  }

  // Preset delete/pick clicks are handled by the presets.ts controller's own
  // delegated listener; this branch set is disjoint from it (the dropdown is a
  // sibling of the toolbar buttons, so closest() never crosses between them).
  private onClick = (event: Event): void => {
    const target = event.target as HTMLElement;
    if (target.closest("[data-apply]")) return this.onApply();
    if (target.closest("[data-clear]")) return this.group()?.clear();
    if (target.closest("[data-load-presets]")) return this.onLoadPresets();
    if (target.closest("[data-save-preset]")) return this.onSavePreset();
  };

  private onApply(): void {
    const group = this.group();
    if (!group) return;
    this.navigate(applyUrl(this.applyTarget, group.serializeForQuery()));
  }

  private onLoadPresets(): void {
    const dropdown = this.querySelector<HTMLElement>("[data-preset-dropdown]");
    if (!dropdown) return;
    dropdown.classList.toggle("hidden");
    if (dropdown.classList.contains("hidden")) return;
    void this.presets?.refresh();
  }

  private onSavePreset(): void {
    const input = this.querySelector<HTMLInputElement>("[data-preset-name]");
    const group = this.group();
    if (!input || !group) return;
    const name = input.value.trim();
    if (!name) {
      window.toast("Preset name is required.", "error");
      return;
    }
    void savePreset(this.presetSaveUrl, {
      name,
      mode: this.mode,
      filter: group.serialize(),
    }).then((response) => {
      // Keep the typed name around when the server rejected the save (its
      // error toast already fired) so the user can correct and retry.
      if (response?.ok) input.value = "";
    });
  }
}

customElements.define("filter-builder", FilterBuilderElement);
