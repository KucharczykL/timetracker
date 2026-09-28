/**
 * Filter-preset plumbing for <preset-panel>, and the contract its hosts
 * (<quick-filter-bar>, <filter-builder>) answer.
 *
 * The dropdown lifecycle (fetch-on-open, rendering, keyboard nav) lives in
 * the shared combobox primitives (search-select + the combobox drop-down
 * behavior); this module owns the API calls: save (POST), per-row removal
 * (the search-select:action listener → confirm → DELETE → refetch), and
 * the CSRF token read. All endpoints are the
 * /api/presets/ collection URL; DELETE appends the preset id.
 */

import { reportClientError } from "../client-errors.js";
import { getCsrfToken } from "../csrf.js";
import type { SearchSelectOption } from "./search-select.js";

export { getCsrfToken };

/** A picked preset; the host loads it and calls preventDefault. */
export const PRESET_LOAD_EVENT = "preset-panel:load";
/** Asks the nearest host for the state to save, during dispatch. */
export const PRESET_SAVE_EVENT = "preset-panel:save";

/** What a preset states beside its name. Empty sort or per-page inherits. */
export interface PresetState {
  readonly filter: Record<string, unknown>;
  readonly sort: string;
  readonly perPage: string;
}

/** A host's answer: the state to save, or why not. */
export type PresetSaveAnswer =
  | { readonly kind: "state"; readonly state: PresetState }
  | { readonly kind: "refused"; readonly sentence: string };

/** A host's refusal when its own filter cannot be read. */
export const UNREADABLE_FILTER_REFUSAL = "The filter could not be read — reload the page.";

/** A filter JSON value: an object, never an array or null. */
export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The save event's detail; the host answers once, then stops propagation. */
export class PresetSaveRequest {
  #answer: PresetSaveAnswer | null = null;

  get answer(): PresetSaveAnswer | null {
    return this.#answer;
  }

  answerWith(answer: PresetSaveAnswer): void {
    if (this.#answer) throw new Error("preset save answered twice");
    this.#answer = answer;
  }
}

// The /api/presets/ list item (value/label/data, including a UUID string value).
type PresetOption = SearchSelectOption;

interface PresetActionDetail {
  name: string;
  action: string;
  option: { value: string; label: string; data: Record<string, string> };
}

interface RefetchableWidget extends HTMLElement {
  refetchOptions?: () => void;
}

export interface SavePresetRequest {
  name: string;
  mode: string;
  filter: Record<string, unknown>;
  // Empty means no sort; unsupported modes ignore it.
  sort?: string;
  // Empty means inherit; any valid value is pinned.
  per_page?: string;
}

/**
 * POST the filter to /api/presets/. Resolves to the Response, or null on a
 * transport failure. Toasts every outcome itself (the API fires no Django
 * messages): "saved" on 201, "updated" on 200, the server's detail (or a
 * generic message) on a rejection. Callers branch on `response?.ok` for their
 * success UI only.
 */
export function savePreset(
  presetApiUrl: string,
  request: SavePresetRequest,
): Promise<Response | null> {
  return fetch(presetApiUrl, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: JSON.stringify(request),
  })
    .then(async (response) => {
      if (response.ok) {
        const verb = response.status === 201 ? "saved" : "updated";
        window.toast(`Filter preset "${request.name}" ${verb}.`, "success");
      } else {
        const detail: unknown = await response
          .json()
          .then((body: { detail?: unknown }) => body?.detail)
          .catch(() => undefined);
        // A 422 answers a list of errors, which no toast can print.
        const sentence = typeof detail === "string" && detail ? detail : "Failed to save preset.";
        window.toast(sentence, "error");
      }
      return response;
    })
    .catch((error: unknown) => {
      console.error("presets: failed to save preset", error);
      window.toast("Failed to save preset.", "error");
      return null;
    });
}

/**
 * Wire per-row preset removal for a preset picker inside `root`: listens for
 * the widget's `search-select:action` events (guarded to `action="delete"`
 * from a [data-preset-picker] wrapper), confirms, DELETEs, toasts either way
 * (Undo on success, the failure otherwise), and refetches the widget's
 * options either way — a stale-row 404 self-corrects into the row vanishing. Returns a dispose function; callers
 * MUST invoke it from disconnectedCallback, or a re-connect stacks a second
 * listener (one click → two confirm()s → two DELETEs).
 */
interface RemovedPresetAnswer {
  restore_url: string;
}

/** The answer's restore route, or null for a body that names none. */
async function restoreUrlOf(response: Response): Promise<string | null> {
  try {
    const answer = (await response.json()) as Partial<RemovedPresetAnswer>;
    if (typeof answer.restore_url === "string" && answer.restore_url.startsWith("/")) {
      return answer.restore_url;
    }
    reportClientError("presets[restore_url]", JSON.stringify(answer), { toast: false });
  } catch (error) {
    reportClientError("presets[restore_url]", String((error as Error)?.message ?? error), {
      toast: false,
    });
  }
  return null;
}

export function wirePresetDelete(root: HTMLElement, presetApiUrl: string): () => void {
  const onAction = (event: Event): void => {
    const detail = (event as CustomEvent<PresetActionDetail>).detail;
    if (detail?.action !== "delete") return;
    const target = event.target as HTMLElement | null;
    const picker = target?.closest<HTMLElement>("[data-preset-picker]");
    if (!picker) return;
    if (!confirm(`Remove preset "${detail.option.label}"?`)) return;

    const refetch = (): void =>
      picker.querySelector<RefetchableWidget>("search-select")?.refetchOptions?.();
    fetch(presetApiUrl + detail.option.value, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRFToken": getCsrfToken() },
    })
      .then(async (response) => {
        if (!response.ok) {
          window.toast("Failed to remove preset.", "error");
          refetch();
          return;
        }
        // Removed either way; the action only with a route the answer names.
        const restoreUrl = await restoreUrlOf(response);
        window.toast(
          "Preset removed.",
          "success",
          restoreUrl ? { action: { label: "Undo", url: restoreUrl } } : {},
        );
        refetch();
      })
      .catch((error: unknown) => {
        console.error("presets: remove preset failed", error);
        window.toast("Failed to remove preset.", "error");
        refetch();
      });
  };
  root.addEventListener("search-select:action", onAction);
  return () => root.removeEventListener("search-select:action", onAction);
}
