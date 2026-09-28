import { reportClientError } from "../client-errors.js";
import { readPresetPanelProps } from "../generated/props.js";
import {
  fetchPresetNames,
  PRESET_LOAD_EVENT,
  PRESET_SAVE_EVENT,
  PresetSaveRequest,
  PresetState,
  savePreset,
  wirePresetDelete,
} from "./presets.js";

// <preset-panel> — the saved presets above a name box and Save. It owns
// every preset API call and knows no page: a pick is announced as
// preset-panel:load, and a save asks the nearest host for its state through
// preset-panel:save (see presets.ts).

// Must match SAVE_PRESET_LABEL in common/components/search_select.py.
const SAVE_LABEL = "Save";
const OVERWRITE_LABEL = "Overwrite";

interface PresetChangeDetail {
  last: { value: string; label: string; data: Record<string, string> } | null;
}

interface PresetWidget extends HTMLElement {
  clearSelection?: () => void;
  refetchOptions?: () => void;
}

interface ClosableHost extends HTMLElement {
  close?: () => void;
}

export class PresetPanelElement extends HTMLElement {
  private apiUrl = "";
  private mode = "";
  // Every preset name for the mode, fetched when the name box gains focus.
  // A failed fetch leaves it empty, so the overwrite hint stays off.
  private presetNames = new Set<string>();
  private disposeDelete: (() => void) | null = null;

  connectedCallback(): void {
    const props = readPresetPanelProps(this);
    this.apiUrl = props.apiUrl;
    this.mode = props.mode;
    this.addEventListener("search-select:change", this.onPick);
    this.addEventListener("click", this.onClick);
    this.addEventListener("keydown", this.onKeydown);
    this.addEventListener("focusin", this.onFocusIn);
    this.addEventListener("input", this.onInput);
    this.disposeDelete = wirePresetDelete(this, this.apiUrl);
  }

  disconnectedCallback(): void {
    this.removeEventListener("search-select:change", this.onPick);
    this.removeEventListener("click", this.onClick);
    this.removeEventListener("keydown", this.onKeydown);
    this.removeEventListener("focusin", this.onFocusIn);
    this.removeEventListener("input", this.onInput);
    this.disposeDelete?.();
    this.disposeDelete = null;
  }

  private widget(): PresetWidget | null {
    return this.querySelector<PresetWidget>("search-select");
  }

  private nameInput(): HTMLInputElement | null {
    return this.querySelector<HTMLInputElement>("[data-preset-name]");
  }

  // A pick is a command, not a value: announce it, then clear the transient
  // selection so it cannot pin a stale row, and close the panel.
  private onPick = (event: Event): void => {
    const detail = (event as CustomEvent<PresetChangeDetail>).detail;
    if (!detail?.last) return;
    try {
      const raw = detail.last.data.filter ?? "";
      const state: PresetState = {
        filter: raw ? (JSON.parse(raw) as Record<string, unknown>) : {},
        // Missing values restore inherited defaults.
        sort: detail.last.data.sort ?? "",
        perPage: detail.last.data.per_page ?? "",
      };
      this.dispatchEvent(
        new CustomEvent<PresetState>(PRESET_LOAD_EVENT, { bubbles: true, detail: state }),
      );
    } catch (error) {
      reportClientError("preset-panel[load]", String(error), { toast: false });
      // Keep the "preset load failed" console substring (e2e crash guard).
      console.error("preset-panel: preset load failed", error);
      window.toast("Preset is not a valid filter.", "error");
    }
    this.widget()?.clearSelection?.();
    this.closest<ClosableHost>("drop-down")?.close?.();
  };

  private onClick = (event: Event): void => {
    if ((event.target as HTMLElement).closest("[data-save-preset]")) this.save();
  };

  // Enter in the name box saves. Without preventDefault it would submit the
  // quick bar's form and navigate as Apply.
  private onKeydown = (event: KeyboardEvent): void => {
    if (event.key !== "Enter") return;
    if (!(event.target as HTMLElement).closest("[data-preset-name]")) return;
    event.preventDefault();
    this.save();
  };

  private onFocusIn = (event: Event): void => {
    if (!(event.target as HTMLElement).closest("[data-preset-name]")) return;
    void fetchPresetNames(this.apiUrl, this.mode).then((names) => {
      this.presetNames = names;
      this.updateOverwriteHint();
    });
  };

  private onInput = (event: Event): void => {
    if (!(event.target as HTMLElement).closest("[data-preset-name]")) return;
    this.updateOverwriteHint();
  };

  // The hint and the button's label both carry the collision, so the state
  // reaches the button's accessible name too. Compared as the server's
  // (user, mode, name) uniqueness compares: fetchPresetNames trims.
  private updateOverwriteHint(): void {
    const input = this.nameInput();
    const hint = this.querySelector<HTMLElement>("[data-preset-name-warning]");
    const saveButton = this.querySelector<HTMLButtonElement>("[data-save-preset]");
    if (!input || !hint) return;
    const name = input.value.trim();
    const collides = name !== "" && this.presetNames.has(name);
    hint.hidden = !collides;
    hint.textContent = collides
      ? `A preset named "${name}" already exists — saving overwrites it.`
      : "";
    if (saveButton) saveButton.textContent = collides ? OVERWRITE_LABEL : SAVE_LABEL;
  }

  private save(): void {
    const input = this.nameInput();
    if (!input) return;
    const name = input.value.trim();
    if (!name) {
      window.toast("Preset name is required.", "error");
      return;
    }
    const request: PresetSaveRequest = { state: null, refusal: null };
    this.dispatchEvent(
      new CustomEvent<PresetSaveRequest>(PRESET_SAVE_EVENT, {
        bubbles: true,
        detail: request,
      }),
    );
    if (request.refusal) {
      window.toast(request.refusal, "error");
      return;
    }
    const state = request.state;
    if (!state) {
      reportClientError("preset-panel[save]", "no host answered the save");
      return;
    }
    void savePreset(this.apiUrl, {
      name,
      mode: this.mode,
      filter: state.filter,
      sort: state.sort,
      per_page: state.perPage,
    }).then((response) => {
      // A rejected save keeps the typed name so it can be corrected.
      if (!response?.ok) return;
      this.presetNames.add(name);
      input.value = "";
      this.updateOverwriteHint();
      this.widget()?.refetchOptions?.();
    });
  }
}

customElements.define("preset-panel", PresetPanelElement);
