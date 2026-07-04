/**
 * FilterBar — custom element wrapping the collapsible filter bar.
 *
 * Handles form submission (building filter JSON + URL navigation), preset
 * loading/saving, and string-filter input toggling. Props (apply_url,
 * preset_api_url, preset_mode) are read from the element's typed attributes
 * via codegen. The Load-preset dropdown is the shared combobox picker (#297):
 * a pick bubbles search-select:change and navigates to ?filter=; per-row
 * deletion goes through wirePresetDelete.
 */
import { readFilterBarProps } from "../generated/props.js";
import { applyUrl } from "./filter-url.js";
import { readFieldComparisonSet } from "./field-comparison-set.js";
import {
  fetchPresetNames,
  savePreset as requestSavePreset,
  wirePresetDelete,
} from "./presets.js";
import { readSearchSelect } from "./search-select.js";
import {
  parseJSONAttr,
  readBoolWidget,
  readDateWidget,
  readNumberWidget,
  readSetWidget,
  readStringWidget,
  setupModifierToggles,
} from "./filter-widgets.js";

interface DeselectableRadio extends HTMLInputElement {
  wasChecked?: boolean;
}

// Deep-merge a single leaf criterion into `target` by its JSON path. Branch
// objects are created lazily as the path is walked. setPath writes the leaf
// unconditionally; it is the *caller's* contract to only invoke it with a
// non-null leaf, so an empty sub-filter (which would change query semantics) is
// never pre-created here. For length-1 paths this is just `target[key] = leaf`.
function setPath(
  target: Record<string, unknown>,
  path: string[],
  leaf: unknown,
): void {
  if (path.length === 0) return;
  let node = target;
  for (let index = 0; index < path.length - 1; index++) {
    const key = path[index];
    if (node[key] == null || typeof node[key] !== "object") node[key] = {};
    node = node[key] as Record<string, unknown>;
  }
  node[path[path.length - 1]] = leaf;
}

// Fold a key chain into a fresh nested object terminating in `leaf` —
// nest(["session_filter", "device"], leaf) → {session_filter: {device: leaf}}.
// Unlike setPath this never mutates a shared object: each cross-entity widget
// builds its own standalone sub-filter element so several widgets targeting the
// same relation compose as independent EXISTS (their own AND elements) rather
// than merging into one shared relation node.
function nest(path: string[], leaf: unknown): Record<string, unknown> {
  const root: Record<string, unknown> = {};
  let node = root;
  for (let index = 0; index < path.length - 1; index++) {
    const child: Record<string, unknown> = {};
    node[path[index]] = child;
    node = child;
  }
  node[path[path.length - 1]] = leaf;
  return root;
}

// Append a sub-filter element to the parent filter's n-ary AND list, creating
// the list on first use. Only ever called with a real selection, so an empty AND
// element (which would change query semantics) is never appended.
function appendAnd(
  filter: Record<string, unknown>,
  element: Record<string, unknown>,
): void {
  if (!Array.isArray(filter.AND)) filter.AND = [];
  (filter.AND as unknown[]).push(element);
}

function readWidget(element: HTMLElement, kind: string | null): unknown {
  switch (kind) {
    case "string":
      return readStringWidget(element);
    case "number":
      return readNumberWidget(element);
    case "date":
      return readDateWidget(element);
    case "bool":
      return readBoolWidget(element);
    case "set":
      return readSetWidget(element);
    default:
      console.warn(`filter-bar: no reader for data-kind="${kind}"`, element);
      return null;
  }
}

function buildFilterJSON(form: HTMLElement): Record<string, unknown> {
  const filter: Record<string, unknown> = {};

  const searchInput = form.querySelector<HTMLInputElement>('[name="filter-search"]');
  if (searchInput && searchInput.value.trim()) {
    const excludeChecked = form.querySelector<HTMLInputElement>(
      '[name="filter-search-exclude"]',
    )?.checked;
    setPath(filter, ["search"], {
      value: searchInput.value.trim(),
      modifier: excludeChecked ? "EXCLUDES" : "INCLUDES",
    });
  }

  // Serialise every search-select's state into its data-included/excluded/
  // modifier attributes once, so the generic loop below can read set widgets
  // uniformly with the rest.
  readSearchSelect(form);

  form.querySelectorAll<HTMLElement>("[data-filter-widget]").forEach((widget) => {
    const path = parseJSONAttr<string>(widget, "data-path");
    if (path.length === 0) return;
    const kind = widget.getAttribute("data-kind");

    // Relation-bool: a boolean radio toggling a whole cross-entity sub-filter
    // (ANY vs NONE) over a fixed child criterion. data-path is the relation chain
    // (single segment, no leaf); data-relation-child is the fixed child.
    if (kind === "relation-bool") {
      const element = readRelationBoolWidget(widget, path);
      if (element !== null) appendAnd(filter, element);
      return;
    }

    // Field-to-field comparison set: a list-valued widget, so it cannot use the
    // single-leaf setPath model. AND mode writes the top-level field_comparisons
    // array (each entry AND'd by _apply_operators); OR mode appends one isolated
    // AND wrapper holding an OR of single-comparison nodes, so the OR never leaks
    // onto the other top-level criteria.
    // TODO(nested-builder, #168): the mode toggle + these two shapes are a
    // stepping stone the recursive tree serializer replaces.
    if (kind === "field-comparison") {
      const { mode, comparisons } = readFieldComparisonSet(widget);
      if (comparisons.length > 0) {
        if (mode === "OR") {
          appendAnd(filter, {
            OR: comparisons.map((comparison) => ({ field_comparisons: [comparison] })),
          });
        } else {
          filter.field_comparisons = comparisons;
        }
      }
      return;
    }

    const result = readWidget(widget, kind);
    if (result === null) return;
    // A multi-segment path is a cross-entity leaf: nest the leaf under its
    // relation chain and append it as its own independent EXISTS element of AND,
    // rather than merging it into a shared top-level relation node. A single-
    // segment path is a plain top-level field, written in place.
    if (path.length > 1) {
      appendAnd(filter, nest(path, result));
    } else {
      setPath(filter, path, result);
    }
  });

  return filter;
}

function readRelationBoolWidget(
  widget: HTMLElement,
  path: string[],
): Record<string, unknown> | null {
  const checked = widget.querySelector<HTMLInputElement>(
    'input[type="radio"]:checked',
  );
  if (!checked) return null;
  // The child criterion is mandatory: an empty relation sub-filter would change
  // to_q semantics to "has ANY related row" (or, for the False radio, "has NO
  // related row"), not the intended "has a row matching the child". Bail rather
  // than emit a meaning-altering empty relation.
  const childRaw = widget.getAttribute("data-relation-child");
  if (!childRaw) {
    console.warn("filter-bar: relation-bool widget missing data-relation-child", widget);
    return null;
  }
  let child: Record<string, unknown>;
  try {
    child = JSON.parse(childRaw);
  } catch {
    console.warn("filter-bar: malformed data-relation-child", childRaw);
    return null;
  }
  if (!child || typeof child !== "object" || Object.keys(child).length === 0) {
    console.warn("filter-bar: empty data-relation-child", childRaw);
    return null;
  }
  const relationField = path[0];
  // true → match ANY (omit `match`); false → match NONE.
  const relationNode: Record<string, unknown> =
    checked.value === "false" ? { match: "NONE", ...child } : { ...child };
  return { [relationField]: relationNode };
}


function setupDeselectableRadios(root: HTMLElement): void {
  root.querySelectorAll<DeselectableRadio>('input[type="radio"]').forEach((radio) => {
    radio.addEventListener("click", function (this: DeselectableRadio) {
      if (this.wasChecked) {
        this.checked = false;
        this.wasChecked = false;
        this.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        const name = this.getAttribute("name");
        if (name) {
          root
            .querySelectorAll<DeselectableRadio>(`input[type="radio"][name="${name}"]`)
            .forEach((other) => {
              other.wasChecked = false;
            });
        }
        this.wasChecked = true;
      }
    });
    if (radio.checked) {
      radio.wasChecked = true;
    }
  });
}

// Show the red inline warning and relabel the confirm button to "Overwrite" only
// when the typed name collides with a known preset name; otherwise restore
// "Save". The match is case-sensitive to mirror the (user, mode, name) unique
// constraint, which uses SQLite's default BINARY collation ("Backlog" and
// "backlog" are distinct rows).
function updateOverwriteWarning(root: HTMLElement, knownNames: Set<string>): void {
  const input = root.querySelector<HTMLInputElement>("[data-filter-bar-preset-name]");
  const warning = root.querySelector<HTMLElement>("[data-filter-bar-overwrite-warning]");
  const confirmButton = root.querySelector<HTMLElement>("[data-filter-bar-confirm-save]");
  const name = input ? input.value.trim() : "";
  const collides = name !== "" && knownNames.has(name);
  if (warning) warning.classList.toggle("hidden", !collides);
  if (confirmButton) confirmButton.textContent = collides ? "Overwrite" : "Save";
}

interface PresetChangeDetail {
  name: string;
  values: string[];
  last: { value: string; label: string; data: Record<string, string> } | null;
}

class FilterBarElement extends HTMLElement {
  private presetApiUrl = "";
  private presetMode = "";
  // Server-provided list URL for Apply/Clear/preset-pick navigation (#304) —
  // never derived from window.location.pathname.
  private applyTarget = "";
  // The user's preset names for this mode, fetched on demand when the save
  // input is revealed (no fetch on page load) — the collision-warning source
  // (#212). Refetched on every save-click so in-panel deletes can't leave it
  // stale; updated in place after a successful save.
  private knownPresetNames = new Set<string>();
  private disposePresetDelete: (() => void) | null = null;

  connectedCallback(): void {
    const props = readFilterBarProps(this);
    this.presetApiUrl = props.presetApiUrl;
    this.presetMode = props.presetMode;
    this.applyTarget = props.applyUrl;
    const form = this.querySelector<HTMLFormElement>("form");
    if (!form) return;

    // A pick in the preset picker navigates to the preset's filtered list view
    // (the picker bubbles search-select:change; the guard scopes this listener
    // to it — the bar's own filter widgets bubble the same event).
    this.addEventListener("search-select:change", this.onPresetPick);
    this.disposePresetDelete = wirePresetDelete(this, this.presetApiUrl);

    // Delegated on the persistent custom element so the toggle keeps working
    // after the inner #filter-bar body is htmx-swapped — connectedCallback does
    // not re-run for inner swaps, so a direct listener on the button would be
    // lost (this is why the toggle was previously an inline onclick).
    this.addEventListener("click", (event) => {
      if ((event.target as Element).closest("[data-filter-bar-toggle]")) {
        this.querySelector("#filter-bar-body")?.classList.toggle("hidden");
      }
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      window.location.href = applyUrl(this.applyTarget, buildFilterJSON(form));
    });

    this.querySelector("[data-filter-bar-clear]")?.addEventListener("click", () => {
      form.reset();
      window.location.href = this.applyTarget;
    });

    this.querySelector("[data-filter-bar-save]")?.addEventListener("click", () => {
      this.showPresetNameInput();
    });

    this.querySelector("[data-filter-bar-confirm-save]")?.addEventListener("click", () => {
      this.savePreset(form);
    });

    this.querySelector("[data-filter-bar-preset-name]")?.addEventListener("input", () => {
      updateOverwriteWarning(this, this.knownPresetNames);
    });

    setupDeselectableRadios(this);
    setupModifierToggles(this);
  }

  disconnectedCallback(): void {
    this.removeEventListener("search-select:change", this.onPresetPick);
    this.disposePresetDelete?.();
    this.disposePresetDelete = null;
  }

  private onPresetPick = (event: Event): void => {
    const detail = (event as CustomEvent<PresetChangeDetail>).detail;
    if (!detail?.last) return;
    const picker = (event.target as HTMLElement | null)?.closest<HTMLElement>(
      "[data-preset-picker]",
    );
    if (!picker || !this.contains(picker)) return;
    try {
      const raw = detail.last.data.filter ?? "";
      const filter = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
      // An empty preset means "show everything": applyUrl returns the bare list.
      window.location.href = applyUrl(this.applyTarget, filter);
    } catch (error) {
      // Keep the "preset load failed" console substring (e2e crash guard).
      console.error("filter-bar: preset load failed", error);
      window.toast("Preset is not a valid filter.", "error");
    }
  };

  private showPresetNameInput(): void {
    const input = this.querySelector<HTMLElement>("[data-filter-bar-preset-name]");
    const saveButton = this.querySelector<HTMLElement>("[data-filter-bar-save]");
    const confirmButton = this.querySelector<HTMLElement>("[data-filter-bar-confirm-save]");
    if (input) input.classList.remove("hidden");
    if (saveButton) saveButton.classList.add("hidden");
    if (confirmButton) confirmButton.classList.remove("hidden");
    if (input instanceof HTMLElement) input.focus();
    // A name may already be typed (e.g. reopening the input); reflect what we
    // know now, then re-check when the fresh names land — a pre-typed colliding
    // name must warn without another keystroke.
    updateOverwriteWarning(this, this.knownPresetNames);
    void fetchPresetNames(this.presetApiUrl, this.presetMode).then((names) => {
      this.knownPresetNames = names;
      updateOverwriteWarning(this, this.knownPresetNames);
    });
  }

  private savePreset(form: HTMLElement): void {
    const input = this.querySelector<HTMLInputElement>("[data-filter-bar-preset-name]");
    const name = input ? input.value.trim() : "";
    if (!name) {
      if (input) input.classList.add("border-red-500");
      return;
    }

    void requestSavePreset(this.presetApiUrl, {
      name,
      mode: this.presetMode,
      filter: buildFilterJSON(form),
    }).then((response) => {
      // A rejection already fired its error toast inside the helper; leave the
      // confirm-save UI in place so the user can correct and retry.
      if (!response?.ok) return;
      this.knownPresetNames.add(name);
      if (input) {
        input.value = "";
        input.classList.add("hidden");
        input.classList.remove("border-red-500");
      }
      const saveButton = this.querySelector<HTMLElement>("[data-filter-bar-save]");
      const confirmButton = this.querySelector<HTMLElement>("[data-filter-bar-confirm-save]");
      if (saveButton) saveButton.classList.remove("hidden");
      if (confirmButton) {
        confirmButton.classList.add("hidden");
        confirmButton.textContent = "Save";
      }
      const warning = this.querySelector<HTMLElement>("[data-filter-bar-overwrite-warning]");
      if (warning) warning.classList.add("hidden");
    });
  }
}

customElements.define("filter-bar", FilterBarElement);
