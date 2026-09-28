import { reportClientError } from "../client-errors.js";
import { readPresetPanelProps } from "../generated/props.js";
import {
  fetchPresetNames,
  isPlainObject,
  PRESET_LOAD_EVENT,
  PRESET_SAVE_EVENT,
  PresetSaveRequest,
  PresetState,
  savePreset,
  wirePresetDelete,
} from "./presets.js";

// <preset-panel> — loads and saves presets; hosts answer (presets.ts).

// Must match SAVE_PRESET_LABEL in common/components/search_select.py.
const SAVE_LABEL = "Save";
const UNANSWERED = "Presets are unavailable here — reload the page.";
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
  // Empty after a failed fetch: no overwrite hint.
  private presetNames = new Set<string>();
  private disposeDelete: (() => void) | null = null;

  connectedCallback(): void {
    const props = readPresetPanelProps(this);
    this.apiUrl = props.presetApiUrl;
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

  private onPick = (event: Event): void => {
    const detail = (event as CustomEvent<PresetChangeDetail>).detail;
    if (!detail?.last) return;
    try {
      const raw = detail.last.data.filter ?? "";
      const filter: unknown = raw ? JSON.parse(raw) : {};
      if (!isPlainObject(filter)) throw new TypeError(`not an object: ${raw}`);
      const state: PresetState = {
        filter,
        // Missing values restore inherited defaults.
        sort: detail.last.data.sort ?? "",
        perPage: detail.last.data.per_page ?? "",
      };
      // A host cancels the event to say it loaded the preset.
      const unanswered = this.dispatchEvent(
        new CustomEvent<PresetState>(PRESET_LOAD_EVENT, {
          bubbles: true,
          cancelable: true,
          detail: state,
        }),
      );
      if (unanswered) {
        reportClientError("preset-panel[load]", "no host answered", { toast: false });
        window.toast(UNANSWERED, "error");
      }
    } catch (error) {
      reportClientError("preset-panel[load]", String(error), { toast: false });
      // Keep the "preset load failed" console substring (e2e crash guard).
      console.error("preset-panel: preset load failed", error);
      window.toast("Preset is not a valid filter.", "error");
    }
    // A kept selection would pin a stale row.
    this.widget()?.clearSelection?.();
    this.closest<ClosableHost>("drop-down")?.close?.();
  };

  private onClick = (event: Event): void => {
    if ((event.target as HTMLElement).closest("[data-save-preset]")) this.save();
  };

  // Else Enter submits the quick bar's form.
  private onKeydown = (event: KeyboardEvent): void => {
    if (event.key !== "Enter") return;
    if (!(event.target as HTMLElement).closest("[data-preset-name]")) return;
    event.preventDefault();
    this.save();
  };

  private onFocusIn = (event: Event): void => {
    if (!(event.target as HTMLElement).closest("[data-preset-name]")) return;
    void fetchPresetNames(this.apiUrl, this.mode).then((names) => {
      // Merged: a fetch may answer after a save added a name.
      names.forEach((name) => this.presetNames.add(name));
      this.updateOverwriteHint();
    });
  };

  private onInput = (event: Event): void => {
    if (!(event.target as HTMLElement).closest("[data-preset-name]")) return;
    this.updateOverwriteHint();
  };

  // The label carries the collision to the button's name.
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
    const request = new PresetSaveRequest();
    this.dispatchEvent(
      new CustomEvent<PresetSaveRequest>(PRESET_SAVE_EVENT, {
        bubbles: true,
        detail: request,
      }),
    );
    const answer = request.answer;
    if (answer?.kind === "refused") {
      window.toast(answer.sentence, "error");
      return;
    }
    if (!answer) {
      reportClientError("preset-panel[save]", "no host answered", { toast: false });
      window.toast(UNANSWERED, "error");
      return;
    }
    const { state } = answer;
    void savePreset(this.apiUrl, {
      name,
      mode: this.mode,
      filter: state.filter,
      sort: state.sort,
      per_page: state.perPage,
    }).then((response) => {
      // A rejected save keeps the name.
      if (!response?.ok) return;
      this.presetNames.add(name);
      input.value = "";
      this.updateOverwriteHint();
      this.widget()?.refetchOptions?.();
    });
  }
}

customElements.define("preset-panel", PresetPanelElement);
