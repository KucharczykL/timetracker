/**
 * Shared filter-preset plumbing for <filter-bar> and <filter-builder> (#264).
 *
 * Owns the preset dropdown lifecycle — fetching the list_presets fragment,
 * delete handling (confirm → DELETE → refetch), and optional pick
 * interception — plus the save_preset POST and the CSRF token read. The two
 * callers differ only in what a preset click does: the bar lets the anchor
 * navigate natively (no `onPick`), the builder feeds `group.loadFilter()`.
 */

export function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  if (match) return decodeURIComponent(match[1]);
  const element = document.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]');
  if (element) return element.value;
  console.warn("presets: CSRF token not found — preset save/delete will 403");
  return "";
}

export interface PresetDropdownOptions {
  /** Persistent element carrying the delegated click listener. */
  root: HTMLElement;
  /**
   * Resolved against `root` on every use, never captured — the dropdown's
   * contents (and potentially the node itself) are replaced after load/delete.
   */
  dropdownSelector: string;
  listUrl: string;
  mode: string;
  /**
   * When set, clicks on preset anchors are intercepted: the anchor's
   * ?filter= JSON is parsed and passed here. When unset, anchors keep their
   * native navigation. A throw from the callback (valid JSON, bad filter
   * shape) is caught and surfaced as the "not a valid filter" toast.
   */
  onPick?: (filter: Record<string, unknown>) => void;
  /** Runs after each successful list render (e.g. re-check name collisions). */
  onListRendered?: () => void;
}

export interface PresetDropdown {
  /** Refetch and re-render the preset list. Never rejects. */
  refresh(): Promise<void>;
  /** Remove the delegated click listener. */
  dispose(): void;
}

const UNAVAILABLE_HTML = '<span class="text-sm text-body italic">Presets unavailable</span>';

// connectedCallback re-runs when an element is moved or re-appended; without
// this, each re-setup would stack another delegated listener on the same root
// (one click → two confirm()s → two DELETEs).
const controllers = new WeakMap<HTMLElement, PresetDropdown>();

export function setupPresetDropdown(options: PresetDropdownOptions): PresetDropdown {
  const { root, dropdownSelector, listUrl, mode, onPick, onListRendered } = options;

  controllers.get(root)?.dispose();
  const abortController = new AbortController();

  function dropdown(): HTMLElement | null {
    return root.querySelector<HTMLElement>(dropdownSelector);
  }

  async function refresh(): Promise<void> {
    const container = dropdown();
    if (!container || !listUrl) return;
    try {
      const url = new URL(listUrl, window.location.origin);
      if (!url.searchParams.has("mode")) url.searchParams.set("mode", mode);
      const response = await fetch(url.toString(), { credentials: "same-origin" });
      if (!response.ok) throw new Error(`preset list failed (${response.status})`);
      container.innerHTML = await response.text();
      onListRendered?.();
    } catch (error) {
      container.innerHTML = UNAVAILABLE_HTML;
      console.error("presets: failed to load preset list", error);
    }
  }

  function deletePreset(deleteButton: HTMLElement): void {
    const deleteUrl = deleteButton.getAttribute("href");
    if (!deleteUrl || !confirm("Delete this preset?")) return;
    window
      .fetchWithHtmxTriggers(deleteUrl, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRFToken": getCsrfToken() },
      })
      .then((response) => {
        // delete_preset attaches no Django message on 404/405/500, so no
        // HX-Trigger toast fires for a rejection — surface one here.
        if (response && !response.ok) window.toast("Failed to delete preset.", "error");
        // Refetch regardless of the outcome: self-correcting either way (a
        // stale-row 404 makes the row vanish instead of lingering).
        return refresh();
      })
      .catch((error: unknown) => {
        console.error("presets: delete preset failed", error);
        window.toast("Failed to delete preset.", "error");
      });
  }

  function pickPreset(anchor: HTMLAnchorElement): void {
    if (!onPick) return;
    try {
      const raw = new URL(anchor.href, window.location.origin).searchParams.get("filter") ?? "";
      onPick(raw ? (JSON.parse(raw) as Record<string, unknown>) : {});
    } catch (error) {
      // Message must keep the "preset load failed" substring — the builder e2e
      // greps the console for it as its crash guard.
      console.error("presets: preset load failed", error);
      window.toast("Preset is not a valid filter.", "error");
    }
  }

  root.addEventListener(
    "click",
    (event) => {
      const target = event.target as HTMLElement | null;
      const container = target ? dropdown() : null;
      if (!target || !container) return;
      // Delete FIRST: list_presets nests the delete <span data-delete-preset>
      // INSIDE the preset <a href>, so the anchor branch would swallow it.
      const deleteButton = target.closest<HTMLElement>("[data-delete-preset]");
      if (deleteButton && container.contains(deleteButton)) {
        event.preventDefault();
        deletePreset(deleteButton);
        return;
      }
      if (!onPick) return; // no interception — preset anchors navigate natively
      const anchor = target.closest<HTMLAnchorElement>("a[href]");
      if (anchor && container.contains(anchor)) {
        event.preventDefault();
        pickPreset(anchor);
      }
    },
    { signal: abortController.signal },
  );

  const controller: PresetDropdown = {
    refresh,
    dispose(): void {
      abortController.abort();
      if (controllers.get(root) === controller) controllers.delete(root);
    },
  };
  controllers.set(root, controller);
  return controller;
}

export interface SavePresetRequest {
  name: string;
  mode: string;
  filter: Record<string, unknown>;
}

/**
 * POST the filter to save_preset. Resolves to the Response, or null on a
 * transport failure (already toasted here — with no Response there is no
 * HX-Trigger, so no server toast fired). Server-side rejections carry their
 * own Django-message toast via fetchWithHtmxTriggers; callers only need to
 * branch on `response?.ok` for their success UI.
 */
export function savePreset(saveUrl: string, request: SavePresetRequest): Promise<Response | null> {
  const body = new URLSearchParams();
  body.append("name", request.name);
  body.append("mode", request.mode);
  body.append("filter", JSON.stringify(request.filter));
  return window
    .fetchWithHtmxTriggers(saveUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        // Mandatory with a string body: without it the request goes out as
        // text/plain and request.POST parses empty (a misleading 400).
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": getCsrfToken(),
      },
      body: body.toString(),
    })
    .catch((error: unknown) => {
      console.error("presets: failed to save preset", error);
      window.toast("Failed to save preset.", "error");
      return null;
    });
}
