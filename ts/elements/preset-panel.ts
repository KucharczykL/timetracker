import { reportClientError } from "../client-errors.js";
import "./drop-down.js";
import { readPresetPanelProps } from "../generated/props.js";
import {
  isPlainObject,
  PRESET_LOAD_EVENT,
  PRESET_SAVE_EVENT,
  PresetSaveRequest,
  PresetState,
  savePreset,
  wirePresetDelete,
} from "./presets.js";
import type { SearchSelectCreateDetail } from "./search-select.js";

// <preset-panel> — loads and saves presets; hosts answer (presets.ts). Its
// one box filters the list and names a save, through the create row.

const UNANSWERED = "Presets are unavailable here — reload the page.";

interface PresetChangeDetail {
  last: { value: string; label: string; data: Record<string, string> } | null;
}

interface PresetWidget extends HTMLElement {
  clearSelection?: () => void;
  refetchOptions?: () => void;
}

export class PresetPanelElement extends HTMLElement {
  private apiUrl = "";
  private mode = "";
  private disposeDelete: (() => void) | null = null;

  connectedCallback(): void {
    const props = readPresetPanelProps(this);
    this.apiUrl = props.presetApiUrl;
    this.mode = props.mode;
    this.addEventListener("search-select:change", this.onPick);
    this.addEventListener("search-select:create", this.onCreate);
    this.disposeDelete = wirePresetDelete(this, this.apiUrl);
  }

  disconnectedCallback(): void {
    this.removeEventListener("search-select:change", this.onPick);
    this.removeEventListener("search-select:create", this.onCreate);
    this.disposeDelete?.();
    this.disposeDelete = null;
  }

  private widget(): PresetWidget | null {
    return this.querySelector<PresetWidget>("search-select");
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
    this.closest("drop-down")?.close();
  };

  private onCreate = (event: Event): void => {
    event.stopPropagation();
    this.save((event as CustomEvent<SearchSelectCreateDetail>).detail.name);
  };

  private save(name: string): void {
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
      // A rejected save keeps the typed name; a saved one empties the box.
      if (response?.ok) this.widget()?.refetchOptions?.();
    });
  }
}

customElements.define("preset-panel", PresetPanelElement);
