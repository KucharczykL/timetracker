import { readFilterBuilderProps } from "../generated/props.js";
import { FILTER_TREE_CHANGE_EVENT, FilterGroupElement } from "./filter-group.js";

// <filter-builder> — the builder-page toolbar (#196). Owns Load/Save preset,
// Apply, Clear; drives the sibling <filter-group>. Preset load/save/delete is
// duplicated from filter-bar.ts for now (follow-up: extract to presets.ts).

export function applyUrl(listUrl: string, filter: Record<string, unknown>): string {
  if (Object.keys(filter).length === 0) return listUrl;
  return listUrl + "?filter=" + encodeURIComponent(JSON.stringify(filter));
}

// fetchWithHtmxTriggers does NOT add CSRF — it only parses HX-Trigger response
// headers. Django's CSRF middleware rejects unsafe methods (POST/DELETE) without
// the token, so mirror filter-bar.ts (getCsrfToken + X-CSRFToken header) or the
// save/delete requests 403.
function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
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
  private presetListUrl = "";
  private presetSaveUrl = "";
  private incompleteCount = 0;
  private changeListener: ((event: Event) => void) | null = null;

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
    this.presetListUrl = props.presetListUrl;
    this.presetSaveUrl = props.presetSaveUrl;

    this.ensureToolbar();
    this.addEventListener("click", this.onClick);
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

  private onClick = (event: Event): void => {
    const target = event.target as HTMLElement;
    // Delete FIRST: list_presets renders the delete control as a <span
    // data-delete-preset> nested INSIDE the preset <a href>, so the anchor branch
    // would otherwise swallow a delete click and load the preset instead.
    const deleteButton = target.closest<HTMLElement>("[data-delete-preset]");
    if (deleteButton) {
      event.preventDefault();
      return this.onDeletePreset(deleteButton);
    }
    const presetLink = target.closest<HTMLAnchorElement>("[data-preset-dropdown] a[href]");
    if (presetLink) {
      event.preventDefault();
      return this.onPresetPicked(presetLink);
    }
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
    const separator = this.presetListUrl.indexOf("?") === -1 ? "?" : "&";
    fetch(this.presetListUrl + separator + "mode=" + encodeURIComponent(this.mode), {
      credentials: "same-origin",
    })
      .then((response) => {
        if (!response.ok) throw new Error("preset list failed");
        return response.text();
      })
      .then((html) => {
        dropdown.innerHTML = html;
      })
      .catch(() => window.toast("Failed to load presets.", "error"));
  }

  // The list fragment's anchors carry ?filter=<json> in their href (see
  // list_presets). Read it out and feed the group instead of navigating.
  private onPresetPicked(anchor: HTMLAnchorElement): void {
    const raw = new URL(anchor.href, window.location.origin).searchParams.get("filter") ?? "";
    const group = this.group();
    if (!group) return;
    try {
      group.loadFilter(raw ? (JSON.parse(raw) as Record<string, unknown>) : {});
    } catch {
      window.toast("Preset is not a valid filter.", "error");
    }
    this.querySelector("[data-preset-dropdown]")?.classList.add("hidden");
  }

  private onDeletePreset(button: HTMLElement): void {
    const deleteUrl = button.getAttribute("href");
    if (!deleteUrl || !confirm("Delete this preset?")) return;
    window
      .fetchWithHtmxTriggers(deleteUrl, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRFToken": getCsrfToken() },
      })
      .then(() => this.onLoadPresets())
      .catch(() => window.toast("Failed to delete preset.", "error"));
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
    const body = new FormData();
    body.append("name", name);
    body.append("mode", this.mode);
    body.append("filter", JSON.stringify(group.serialize()));
    window
      .fetchWithHtmxTriggers(this.presetSaveUrl, {
        method: "POST",
        body,
        credentials: "same-origin",
        headers: { "X-CSRFToken": getCsrfToken() },
      })
      .then(() => {
        input.value = "";
      })
      .catch(() => window.toast("Failed to save preset.", "error"));
  }
}

customElements.define("filter-builder", FilterBuilderElement);
