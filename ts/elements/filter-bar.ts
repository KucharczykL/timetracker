/**
 * FilterBar — custom element wrapping the collapsible filter bar.
 *
 * Handles form submission (building filter JSON + URL navigation), preset
 * loading/saving, and string-filter input toggling. Props (preset_list_url,
 * preset_save_url) are read from the element's typed attributes via codegen.
 */
import { readFilterBarProps } from "../generated/props.js";
import { readSearchSelect } from "./search-select.js";

interface Criterion {
  value: unknown;
  modifier: string;
  value2?: unknown;
}

interface PillEntry {
  id: string;
  label: string;
}

interface DeselectableRadio extends HTMLInputElement {
  wasChecked?: boolean;
}

function criterion(value: unknown, value2: unknown, modifier: string): Criterion {
  const result: Criterion = { value, modifier };
  if (value2 !== null && value2 !== undefined && value2 !== "") {
    result.value2 = value2;
  }
  return result;
}

function parseNumberInputValue(element: HTMLInputElement | null): number | "" {
  if (!element || element.value === "") return "";
  const value = parseFloat(element.value);
  return isNaN(value) ? "" : value;
}

function buildRangeCriterion(
  valueMin: number | string,
  valueMax: number | string,
): Criterion | null {
  if (valueMin !== "" && valueMax !== "") return criterion(valueMin, valueMax, "BETWEEN");
  if (valueMin !== "") return criterion(valueMin, null, "GREATER_THAN");
  if (valueMax !== "") return criterion(valueMax, null, "LESS_THAN");
  return null;
}

function parseJSONAttr<T>(element: Element, attr: string): T[] {
  const raw = element.getAttribute(attr);
  if (!raw) return [];
  try {
    return JSON.parse(raw);
  } catch {
    console.warn("filter-bar: malformed JSON attribute", attr, raw);
    return [];
  }
}

function baseUrl(): string {
  return window.location.pathname;
}

function presetMode(): string {
  const path = window.location.pathname;
  if (path.indexOf("session") !== -1) return "sessions";
  if (path.indexOf("purchase") !== -1) return "purchases";
  if (path.indexOf("device") !== -1) return "devices";
  if (path.indexOf("platform") !== -1) return "platforms";
  if (path.indexOf("playevent") !== -1) return "playevents";
  return "games";
}

function getCsrfToken(): string {
  const cookie = document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrftoken="));
  if (cookie) return cookie.split("=")[1];
  const element = document.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]');
  return element ? element.value : "";
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

// Per-kind readers: each is scoped to a single widget element and returns a
// criterion object, or null to omit the field entirely. The value/modifier
// logic is a verbatim port of the former hardcoded field loops; only the
// element lookup changed (within the widget element instead of global [name=…]).

function readStringWidget(element: HTMLElement): Record<string, unknown> | null {
  const modifier =
    element.querySelector<HTMLInputElement>('input[data-string-modifier-radio]:checked')
      ?.value ?? "EQUALS";
  if (modifier === "IS_NULL" || modifier === "NOT_NULL") {
    return { modifier };
  }
  const textInput = element.querySelector<HTMLInputElement>('input[type="text"]');
  if (textInput && textInput.value.trim()) {
    return { value: textInput.value.trim(), modifier };
  }
  return null;
}

function readNumberWidget(element: HTMLElement): Criterion | Record<string, unknown> | null {
  const modifier =
    element.querySelector<HTMLInputElement>('input[data-number-modifier-radio]:checked')
      ?.value ?? "EQUALS";
  if (modifier === "IS_NULL" || modifier === "NOT_NULL") {
    return { modifier };
  }
  const value = parseNumberInputValue(
    element.querySelector<HTMLInputElement>('input[type="number"]:not([data-number-value2])'),
  );
  if (modifier === "BETWEEN" || modifier === "NOT_BETWEEN") {
    const value2Marker = element.querySelector('[data-number-value2]');
    const value2Input =
      value2Marker instanceof HTMLInputElement
        ? value2Marker
        : (value2Marker?.querySelector<HTMLInputElement>("input") ?? null);
    const value2 = parseNumberInputValue(value2Input);
    if (value !== "") return criterion(value, value2, modifier);
    return null;
  }
  if (value !== "") return criterion(value, null, modifier);
  return null;
}

function readDateWidget(element: HTMLElement): Criterion | null {
  const valueMin =
    element.querySelector<HTMLInputElement>("[data-range-min]")?.value ?? "";
  const valueMax =
    element.querySelector<HTMLInputElement>("[data-range-max]")?.value ?? "";
  return buildRangeCriterion(valueMin, valueMax);
}

function readBoolWidget(element: HTMLElement): Criterion | null {
  const checked = element.querySelector<HTMLInputElement>('input[type="radio"]:checked');
  if (!checked) return null;
  return criterion(checked.value === "true", null, "EQUALS");
}

function readSetWidget(element: HTMLElement): Record<string, unknown> | null {
  const included = parseJSONAttr<PillEntry>(element, "data-included");
  const excluded = parseJSONAttr<PillEntry>(element, "data-excluded");
  const modifier = element.getAttribute("data-modifier");
  const isPresence = modifier === "NOT_NULL" || modifier === "IS_NULL";
  if (isPresence) {
    return { modifier };
  }
  if (included.length > 0 || excluded.length > 0) {
    return {
      value: included.map((item) => ({ id: item.id, label: item.label })),
      excludes: excluded.map((item) => ({ id: item.id, label: item.label })),
      modifier: modifier || "INCLUDES",
    };
  }
  return null;
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
    setPath(filter, ["search"], { value: searchInput.value.trim(), modifier: "INCLUDES" });
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

function injectSearchInput(form: HTMLElement): void {
  if (form.querySelector('[name="filter-search"]')) return;
  const input = document.createElement("input");
  input.type = "text";
  input.name = "filter-search";
  input.placeholder = "Search…";
  input.className =
    "block w-full rounded-base border border-default-medium bg-neutral-secondary-medium text-sm text-heading p-2 mb-4 focus:ring-brand focus:border-brand";
  const hidden = form.querySelector<HTMLInputElement>('[name="filter"]');
  if (hidden && hidden.parentNode) {
    try {
      const existing = JSON.parse(hidden.value || "{}");
      if (existing.search && existing.search.value) {
        input.value = existing.search.value;
      }
    } catch {
      // ignore malformed existing filter JSON
    }
    hidden.parentNode.insertBefore(input, hidden.nextSibling);
  }
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

function toggleStringFilterInput(radio: HTMLInputElement): void {
  const container = radio.closest(".flex-col");
  if (!container) return;
  const textInput = container.querySelector<HTMLInputElement>('input[type="text"]');
  if (!textInput) return;
  const checkedRadio = container.querySelector<HTMLInputElement>('input[type="radio"]:checked');
  const value = checkedRadio ? checkedRadio.value : "";
  if (value === "IS_NULL" || value === "NOT_NULL") {
    textInput.disabled = true;
    textInput.value = "";
    textInput.classList.add("opacity-50", "cursor-not-allowed");
  } else {
    textInput.disabled = false;
    textInput.classList.remove("opacity-50", "cursor-not-allowed");
  }
}

function setupStringFilters(root: HTMLElement): void {
  // Delegated on the persistent custom element (see setupNumberFilters) so the
  // modifier radios keep working after an htmx swap of the inner #filter-bar.
  root.addEventListener("change", (event) => {
    const target = event.target as Element;
    if (target.matches("input[data-string-modifier-radio]")) {
      toggleStringFilterInput(target as HTMLInputElement);
    }
  });
}

function toggleNumberFilterInput(radio: HTMLInputElement): void {
  const container = radio.closest(".flex-col");
  if (!container) return;
  const inputs = container.querySelectorAll<HTMLInputElement>('input[type="number"]');
  const value2 = container.querySelector<HTMLInputElement>("[data-number-value2]");
  const checkedRadio = container.querySelector<HTMLInputElement>('input[type="radio"]:checked');
  const modifier = checkedRadio ? checkedRadio.value : "";
  const isPresence = modifier === "IS_NULL" || modifier === "NOT_NULL";
  const isBetween = modifier === "BETWEEN" || modifier === "NOT_BETWEEN";
  inputs.forEach((input) => {
    if (isPresence) {
      input.disabled = true;
      input.value = "";
      input.classList.add("opacity-50", "cursor-not-allowed");
    } else {
      input.disabled = false;
      input.classList.remove("opacity-50", "cursor-not-allowed");
    }
  });
  if (value2) value2.classList.toggle("hidden", isPresence || !isBetween);
}

function setupNumberFilters(root: HTMLElement): void {
  // Delegated on the persistent custom element so the modifier radios keep
  // working after the inner #filter-bar body is htmx-swapped (connectedCallback
  // does not re-run for inner swaps — a direct per-radio listener would be lost).
  root.addEventListener("change", (event) => {
    const target = event.target as Element;
    if (target.matches("input[data-number-modifier-radio]")) {
      toggleNumberFilterInput(target as HTMLInputElement);
    }
  });
}

function setupPresetDeleteHandlers(container: HTMLElement): void {
  const deleteLinks = container.querySelectorAll<HTMLAnchorElement>("[data-delete-preset]");
  deleteLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const deleteUrl = link.getAttribute("href");
      if (!deleteUrl) return;
      if (!confirm("Delete this preset?")) return;
      fetch(deleteUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": getCsrfToken() },
      })
        .then(() => {
          const listItem = link.closest("li");
          if (listItem) listItem.remove();
          const list = container.querySelector("ul");
          if (list && list.querySelectorAll("li").length === 0) {
            list.innerHTML =
              '<li class="px-4 py-2 text-sm text-body italic">No saved presets</li>';
          }
        })
        .catch((error) => {
          console.error("Delete failed:", error);
        });
    });
  });
}

function loadPresets(root: HTMLElement, presetListUrl: string): void {
  const dropdown = root.querySelector<HTMLElement>("#preset-dropdown");
  if (!dropdown) return;

  const mode = presetMode();
  let query = "";
  if (presetListUrl.indexOf("mode=") === -1) {
    query = (presetListUrl.indexOf("?") !== -1 ? "&" : "?") + "mode=" + mode;
  }

  fetch(presetListUrl + query, { credentials: "same-origin" })
    .then((response) => {
      if (!response.ok) throw new Error("Failed to load presets");
      return response.text();
    })
    .then((html) => {
      dropdown.innerHTML = html;
      setupPresetDeleteHandlers(dropdown);
    })
    .catch((error) => {
      dropdown.innerHTML =
        '<span class="text-sm text-body italic">Presets unavailable</span>';
      console.error(error);
    });
}

function showPresetNameInput(root: HTMLElement): void {
  const input = root.querySelector<HTMLElement>("[data-filter-bar-preset-name]");
  const saveButton = root.querySelector<HTMLElement>("[data-filter-bar-save]");
  const confirmButton = root.querySelector<HTMLElement>("[data-filter-bar-confirm-save]");
  if (input) input.classList.remove("hidden");
  if (saveButton) saveButton.classList.add("hidden");
  if (confirmButton) confirmButton.classList.remove("hidden");
  if (input instanceof HTMLElement) input.focus();
}

function savePreset(
  form: HTMLElement,
  presetSaveUrl: string,
  presetListUrl: string,
  root: HTMLElement,
): void {
  const input = root.querySelector<HTMLInputElement>("[data-filter-bar-preset-name]");
  const name = input ? input.value.trim() : "";
  if (!name) {
    if (input) input.classList.add("border-red-500");
    return;
  }

  const filterObject = buildFilterJSON(form);
  const body = new URLSearchParams();
  body.append("name", name);
  body.append("mode", presetMode());
  body.append("filter", JSON.stringify(filterObject));

  fetch(presetSaveUrl, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "X-CSRFToken": getCsrfToken(),
    },
    body: body.toString(),
  })
    .then((response) => {
      if (!response.ok) throw new Error("Save failed");
      if (input) {
        input.value = "";
        input.classList.add("hidden");
        input.classList.remove("border-red-500");
      }
      const saveButton = root.querySelector<HTMLElement>("[data-filter-bar-save]");
      const confirmButton = root.querySelector<HTMLElement>("[data-filter-bar-confirm-save]");
      if (saveButton) saveButton.classList.remove("hidden");
      if (confirmButton) confirmButton.classList.add("hidden");
      loadPresets(root, presetListUrl);
    })
    .catch((error) => {
      console.error("Failed to save preset:", error);
    });
}

class FilterBarElement extends HTMLElement {
  connectedCallback(): void {
    const { presetListUrl, presetSaveUrl } = readFilterBarProps(this);
    const form = this.querySelector<HTMLFormElement>("form");
    if (!form) return;

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
      const filter = buildFilterJSON(form);
      const filterString = JSON.stringify(filter);
      let url = baseUrl();
      if (filterString && filterString !== "{}") {
        url += "?filter=" + encodeURIComponent(filterString);
      }
      window.location.href = url;
    });

    this.querySelector("[data-filter-bar-clear]")?.addEventListener("click", () => {
      form.reset();
      window.location.href = baseUrl();
    });

    this.querySelector("[data-filter-bar-save]")?.addEventListener("click", () => {
      showPresetNameInput(this);
    });

    this.querySelector("[data-filter-bar-confirm-save]")?.addEventListener("click", () => {
      savePreset(form, presetSaveUrl, presetListUrl, this);
    });

    injectSearchInput(form);
    setupDeselectableRadios(this);
    setupStringFilters(this);
    setupNumberFilters(this);
    if (presetListUrl) loadPresets(this, presetListUrl);
  }
}

customElements.define("filter-bar", FilterBarElement);
