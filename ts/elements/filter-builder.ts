import { readFilterBuilderProps } from "../generated/props.js";
import { FILTER_TREE_CHANGE_EVENT, FilterGroupElement } from "./filter-group.js";
import { savePreset, wirePresetDelete } from "./presets.js";
import { applyUrl } from "./filter-url.js";

// <filter-builder> — the builder-page toolbar (#196). Owns Load/Save preset,
// Apply, Clear; drives the sibling <filter-group>. The Load-preset dropdown is
// the shared combobox picker (LoadPresetDropdown / <drop-down behavior=
// "combobox"> hosting a preset search-select, #297): this element only
// consumes its events — search-select:change to load the picked filter,
// search-select:action (via wirePresetDelete) for per-row deletion.

function isFilterGroup(element: Element | null): element is FilterGroupElement {
  return (
    element instanceof HTMLElement &&
    element.tagName.toLowerCase() === "filter-group" &&
    typeof (element as Partial<FilterGroupElement>).serializeForQuery === "function"
  );
}

interface PresetPickerHost extends HTMLElement {
  close?: () => void;
}

interface PresetWidget extends HTMLElement {
  clearSelection?: () => void;
}

interface PresetChangeDetail {
  name: string;
  values: string[];
  last: { value: string; label: string; data: Record<string, string> } | null;
}

export class FilterBuilderElement extends HTMLElement {
  private mode = "";
  private applyTarget = "";
  private presetApiUrl = "";
  // The active sort (a SortString), threaded from the list via the `sort` prop
  // (#77). Apply re-emits it and Save captures it; loading a preset overwrites
  // it with the preset's stored sort so a subsequent Apply restores that.
  private sort = "";
  // The active rows-per-page, threaded from the list via the `per_page` prop
  // (#337), handled exactly like `sort`: Apply re-emits it, Save captures it,
  // and loading a preset adopts the preset's stored size.
  private perPage = "";
  private incompleteCount = 0;
  private changeListener: ((event: Event) => void) | null = null;
  private disposePresetDelete: (() => void) | null = null;

  // Build the toolbar buttons into this element. Called when the element is
  // test-created (no server-rendered children) so tests can querySelector for
  // the data-* hooks without needing Python to render the page. The picker
  // stub is an empty [data-preset-picker] wrapper — tests append their own
  // search-select stand-ins inside it.
  private ensureToolbar(): void {
    if (this.querySelector("[data-apply]")) return; // already server-rendered
    this.innerHTML = `
      <div class="flex flex-wrap gap-3 items-center mb-4">
        <div data-preset-picker=""></div>
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
    this.presetApiUrl = props.presetApiUrl;
    this.sort = props.sort;
    this.perPage = props.perPage;

    this.ensureToolbar();
    this.addEventListener("click", this.onClick);
    this.addEventListener("search-select:change", this.onPresetPick);
    this.disposePresetDelete = wirePresetDelete(this, this.presetApiUrl);
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
    this.removeEventListener("search-select:change", this.onPresetPick);
    this.disposePresetDelete?.();
    this.disposePresetDelete = null;
  }

  // Overridable so tests can assert the target without a real navigation.
  protected navigate(url: string): void {
    window.location.href = url;
  }

  private group(): FilterGroupElement | null {
    const found = document.querySelector("filter-group");
    return isFilterGroup(found) ? found : null;
  }

  private picker(): PresetPickerHost | null {
    return this.querySelector<PresetPickerHost>("[data-preset-picker]");
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

  private onClick = (event: Event): void => {
    const target = event.target as HTMLElement;
    if (target.closest("[data-apply]")) return this.onApply();
    if (target.closest("[data-clear]")) return this.group()?.clear();
    if (target.closest("[data-save-preset]")) return this.onSavePreset();
  };

  // A pick inside the preset picker: load the filter into the tree, then clear
  // the transient selection (a preset pick is a command, not a value — a
  // lingering committed selection would pin a stale row through renderRows'
  // selected-value preservation and pollute the next refetch) and close the
  // dialog. Other search-selects on the page bubble the same event; the
  // [data-preset-picker] guard scopes this to the picker.
  private onPresetPick = (event: Event): void => {
    const detail = (event as CustomEvent<PresetChangeDetail>).detail;
    if (!detail?.last) return;
    const picker = (event.target as HTMLElement | null)?.closest<PresetPickerHost>(
      "[data-preset-picker]",
    );
    if (!picker || !this.contains(picker)) return;
    try {
      const raw = detail.last.data.filter ?? "";
      this.group()?.loadFilter(raw ? (JSON.parse(raw) as Record<string, unknown>) : {});
      // Adopt the preset's stored sort so a subsequent Apply restores it rather
      // than the origin list's sort (#77). Missing/empty clears it → default order.
      this.sort = detail.last.data.sort ?? "";
      // Same for the page size (#337): missing/empty → default rows-per-page.
      this.perPage = detail.last.data.per_page ?? "";
    } catch (error) {
      // Message must keep the "preset load failed" substring — the builder e2e
      // greps the console for it as its crash guard.
      console.error("filter-builder: preset load failed", error);
      window.toast("Preset is not a valid filter.", "error");
    }
    picker.querySelector<PresetWidget>("search-select")?.clearSelection?.();
    picker.close?.();
  };

  private onApply(): void {
    const group = this.group();
    if (!group) return;
    this.navigate(
      applyUrl(this.applyTarget, group.serializeForQuery(), this.sort, this.perPage),
    );
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
    void savePreset(this.presetApiUrl, {
      name,
      mode: this.mode,
      filter: group.serialize(),
      sort: this.sort,
      per_page: this.perPage,
    }).then((response) => {
      // Keep the typed name around when the server rejected the save (its
      // error toast already fired) so the user can correct and retry.
      if (response?.ok) input.value = "";
    });
  }
}

customElements.define("filter-builder", FilterBuilderElement);
