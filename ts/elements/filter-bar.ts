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

interface RangeField {
  prefix: string;
  key: string;
  ignoreZeroZero?: boolean;
  convert?: (value: number) => number;
}

function criterion(value: unknown, value2: unknown, modifier: string): Criterion {
  const result: Criterion = { value, modifier };
  if (value2 !== null && value2 !== undefined && value2 !== "") {
    result.value2 = value2;
  }
  return result;
}

function numberValue(form: HTMLElement, name: string): number | "" {
  const element = form.querySelector<HTMLInputElement>(`[name="${name}"]`);
  if (!element || element.value === "") return "";
  const value = parseFloat(element.value);
  return isNaN(value) ? "" : value;
}

function stringValue(form: HTMLElement, name: string): string {
  const element = form.querySelector<HTMLInputElement>(`[name="${name}"]`);
  return element ? element.value : "";
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

function buildFilterJSON(form: HTMLElement): Record<string, unknown> {
  const filter: Record<string, unknown> = {};

  const searchInput = form.querySelector<HTMLInputElement>('[name="filter-search"]');
  if (searchInput && searchInput.value.trim()) {
    filter.search = { value: searchInput.value.trim(), modifier: "INCLUDES" };
  }

  readSearchSelect(form);
  const widgets = form.querySelectorAll<HTMLElement>('search-select[filter-mode="true"]');
  widgets.forEach((widget) => {
    const field = widget.getAttribute("name");
    if (!field) return;
    const included = parseJSONAttr<PillEntry>(widget, "data-included");
    const excluded = parseJSONAttr<PillEntry>(widget, "data-excluded");
    const modifier = widget.getAttribute("data-modifier");
    const isPresence = modifier === "NOT_NULL" || modifier === "IS_NULL";
    if (isPresence) {
      filter[field] = { modifier };
    } else if (included.length > 0 || excluded.length > 0) {
      filter[field] = {
        value: included.map((item) => ({ id: item.id, label: item.label })),
        excludes: excluded.map((item) => ({ id: item.id, label: item.label })),
        modifier: modifier || "INCLUDES",
      };
    }
  });

  const textFields = [
    { name: "filter-price_currency", key: "price_currency" },
    { name: "filter-converted_currency", key: "converted_currency" },
    { name: "filter-name", key: "name" },
    { name: "filter-group", key: "group" },
    { name: "filter-playevent_note", key: "playevent_note" },
    { name: "filter-note", key: "note" },
  ];
  textFields.forEach((textField) => {
    const modifierElement = form.querySelector<HTMLInputElement>(
      `[name="${textField.name}-modifier"]:checked`,
    );
    const modifier = modifierElement ? modifierElement.value : "EQUALS";
    const isPresence = modifier === "IS_NULL" || modifier === "NOT_NULL";
    if (isPresence) {
      filter[textField.key] = { modifier };
    } else {
      const element = form.querySelector<HTMLInputElement>(`[name="${textField.name}"]`);
      if (element && element.value.trim()) {
        filter[textField.key] = { value: element.value.trim(), modifier };
      }
    }
  });

  const booleanFields = [
    { name: "filter-mastered", key: "mastered" },
    { name: "filter-emulated", key: "emulated" },
    { name: "filter-active", key: "is_active" },
    { name: "filter-refunded", key: "is_refunded" },
    { name: "filter-infinite", key: "infinite" },
    { name: "filter-needs-price-update", key: "needs_price_update" },
    { name: "filter-purchase-refunded", key: "purchase_refunded" },
    { name: "filter-purchase-infinite", key: "purchase_infinite" },
    { name: "filter-session-emulated", key: "session_emulated" },
  ];
  booleanFields.forEach((booleanField) => {
    const element = form.querySelector<HTMLInputElement>(
      `[name="${booleanField.name}"]:checked`,
    );
    if (element) {
      const value = element.value === "true";
      filter[booleanField.key] = criterion(value, null, "EQUALS");
    }
  });

  const rangeFields: RangeField[] = [
    { prefix: "filter-year", key: "year_released" },
    { prefix: "filter-original-year", key: "original_year_released" },
    { prefix: "filter-session-count", key: "session_count" },
    { prefix: "filter-session-average", key: "session_average" },
    { prefix: "filter-purchase-count", key: "purchase_count" },
    { prefix: "filter-playevent-count", key: "playevent_count" },
    { prefix: "filter-duration-total-hours", key: "duration_total_hours" },
    { prefix: "filter-duration-manual-hours", key: "duration_manual_hours" },
    { prefix: "filter-duration-calculated-hours", key: "duration_calculated_hours" },
    { prefix: "filter-manual-playtime-hours", key: "manual_playtime_hours" },
    { prefix: "filter-calculated-playtime-hours", key: "calculated_playtime_hours" },
    { prefix: "filter-num-purchases", key: "num_purchases" },
    { prefix: "filter-price", key: "price" },
    { prefix: "filter-purchase-price-total", key: "purchase_price_total" },
    { prefix: "filter-purchase-price-any", key: "purchase_price_any" },
    { prefix: "filter-days-to-finish", key: "days_to_finish" },
    { prefix: "filter-playtime-hours", key: "playtime_hours", ignoreZeroZero: true },
  ];

  rangeFields.forEach((rangeField) => {
    let valueMin = numberValue(form, rangeField.prefix + "-min");
    let valueMax = numberValue(form, rangeField.prefix + "-max");
    if (rangeField.convert) {
      if (valueMin !== "") valueMin = rangeField.convert(valueMin);
      if (valueMax !== "") valueMax = rangeField.convert(valueMax);
    }
    if (rangeField.ignoreZeroZero && valueMin === 0 && valueMax === 0) return;
    const result = buildRangeCriterion(valueMin, valueMax);
    if (result !== null) filter[rangeField.key] = result;
  });

  const dateRangeFields = [
    { prefix: "filter-date-purchased", key: "date_purchased" },
    { prefix: "filter-date-refunded", key: "date_refunded" },
  ];
  dateRangeFields.forEach((dateField) => {
    const valueMin = stringValue(form, dateField.prefix + "-min");
    const valueMax = stringValue(form, dateField.prefix + "-max");
    const result = buildRangeCriterion(valueMin, valueMax);
    if (result !== null) filter[dateField.key] = result;
  });

  return filter;
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
  root
    .querySelectorAll<HTMLInputElement>("input[data-string-modifier-radio]")
    .forEach((radio) => {
      radio.addEventListener("change", function (this: HTMLInputElement) {
        toggleStringFilterInput(this);
      });
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
    if (presetListUrl) loadPresets(this, presetListUrl);
  }
}

customElements.define("filter-bar", FilterBarElement);
