/**
 * Shared filter-preset plumbing for <quick-filter-bar> and <filter-builder>.
 *
 * The dropdown lifecycle (fetch-on-open, rendering, keyboard nav) now lives in
 * the shared combobox primitives (search-select + the combobox drop-down
 * behavior); this module owns only the API calls: save (POST), per-row delete
 * (the search-select:action listener → confirm → DELETE → refetch), the
 * collision-check name fetch, and the CSRF token read. All endpoints are the
 * /api/presets/ collection URL; DELETE appends the preset id.
 */

import { getCsrfToken } from "../csrf.js";

export { getCsrfToken };

// The /api/presets/ list item (a SearchSelectOption: value/label/data).
interface PresetOption {
  value: number;
  label: string;
  data: Record<string, string>;
}

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
        const detail = await response
          .json()
          .then((body: { detail?: string }) => body?.detail)
          .catch(() => undefined);
        window.toast(detail || "Failed to save preset.", "error");
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
 * Wire per-row preset deletion for a preset picker inside `root`: listens for
 * the widget's `search-select:action` events (guarded to `action="delete"`
 * from a [data-preset-picker] wrapper), confirms, DELETEs, toasts on failure,
 * and refetches the widget's options either way — a stale-row 404
 * self-corrects into the row vanishing. Returns a dispose function; callers
 * MUST invoke it from disconnectedCallback, or a re-connect stacks a second
 * listener (one click → two confirm()s → two DELETEs).
 */
export function wirePresetDelete(root: HTMLElement, presetApiUrl: string): () => void {
  const onAction = (event: Event): void => {
    const detail = (event as CustomEvent<PresetActionDetail>).detail;
    if (detail?.action !== "delete") return;
    const target = event.target as HTMLElement | null;
    const picker = target?.closest<HTMLElement>("[data-preset-picker]");
    if (!picker) return;
    if (!confirm(`Delete preset "${detail.option.label}"?`)) return;

    const refetch = (): void =>
      picker.querySelector<RefetchableWidget>("search-select")?.refetchOptions?.();
    fetch(presetApiUrl + detail.option.value, {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRFToken": getCsrfToken() },
    })
      .then((response) => {
        if (!response.ok) window.toast("Failed to delete preset.", "error");
        refetch();
      })
      .catch((error: unknown) => {
        console.error("presets: delete preset failed", error);
        window.toast("Failed to delete preset.", "error");
        refetch();
      });
  };
  root.addEventListener("search-select:action", onAction);
  return () => root.removeEventListener("search-select:action", onAction);
}

/**
 * The current user's preset names for `mode`, for the save-overwrite collision
 * warning (#212). Unbounded (`limit=0`) so a large collection can never hide a
 * collision. Resolves to an empty set on failure — the warning silently
 * degrades rather than blocking the save.
 */
export function fetchPresetNames(
  presetApiUrl: string,
  mode: string,
): Promise<Set<string>> {
  const url = new URL(presetApiUrl, window.location.origin);
  url.searchParams.set("mode", mode);
  url.searchParams.set("limit", "0");
  return fetch(url.toString(), { credentials: "same-origin" })
    .then((response) => {
      if (!response.ok) throw new Error(`preset list failed (${response.status})`);
      return response.json();
    })
    .then(
      (options: PresetOption[]) => new Set(options.map((option) => option.label.trim())),
    )
    .catch((error: unknown) => {
      console.error("presets: failed to load preset names", error);
      return new Set<string>();
    });
}
