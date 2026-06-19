/**
 * Filter bar — vanilla TypeScript implementation.
 *
 * Handles form submission, preset loading/saving, and preset list rendering.
 * No HTMX — plain fetch() and window.location for all interactions. The
 * applyFilterBar / clearFilterBar / toggleStringFilterInput / showPresetNameInput
 * / savePreset entry points are assigned to window so the server-rendered inline
 * on* handlers (see common/components/filters.py) can reach them.
 */
import { onSwap } from "./utils.js";

interface Criterion {
  value: unknown;
  modifier: string;
  value2?: unknown;
}

// A filter pill as serialised by readSearchSelect onto data-included/excluded.
interface PillEntry {
  id: string;
  label: string;
}

// Deselect-on-click radios stash their last-checked state on the element.
interface DeselectableRadio extends HTMLInputElement {
  wasChecked?: boolean;
}

interface RangeField {
  prefix: string;
  key: string;
  ignoreZeroZero?: boolean;
  convert?: (value: number) => number;
}

(() => {
  "use strict";

  /** Build a criterion object from a value and optional second value. */
  function criterion(value: unknown, value2: unknown, modifier: string): Criterion {
    const result: Criterion = { value, modifier };
    if (value2 !== null && value2 !== undefined && value2 !== "") {
      result.value2 = value2;
    }
    return result;
  }

  /** Read an <input type="number"> value, or "" if not found. */
  function numberValue(form: HTMLElement, name: string): number | "" {
    const element = form.querySelector<HTMLInputElement>(`[name="${name}"]`);
    if (!element || element.value === "") return "";
    const value = parseFloat(element.value);
    return isNaN(value) ? "" : value;
  }

  /** Read a raw <input> value as string, or "" if not found. */
  function stringValue(form: HTMLElement, name: string): string {
    const element = form.querySelector<HTMLInputElement>(`[name="${name}"]`);
    return element ? element.value : "";
  }

  /**
   * Derive a range criterion ({value, value2?, modifier}) from a (min, max)
   * pair, or null if both bounds are empty. Shared by the numeric-range and
   * date-range serializers.
   */
  function buildRangeCriterion(
    valueMin: number | string,
    valueMax: number | string
  ): Criterion | null {
    if (valueMin !== "" && valueMax !== "") return criterion(valueMin, valueMax, "BETWEEN");
    if (valueMin !== "") return criterion(valueMin, null, "GREATER_THAN");
    if (valueMax !== "") return criterion(valueMax, null, "LESS_THAN");
    return null;
  }

  /**
   * Build the filter JSON object from form field values.
   * Returns a plain object ready for JSON.stringify.
   */
  function buildFilterJSON(form: HTMLElement): Record<string, unknown> {
    const filter: Record<string, unknown> = {};

    // ── Search field ──
    const searchInput = form.querySelector<HTMLInputElement>('[name="filter-search"]');
    if (searchInput && searchInput.value.trim()) {
      filter.search = { value: searchInput.value.trim(), modifier: "INCLUDES" };
    }

    // ── FilterSelect widgets (data-search-select-mode="filter") ──
    // readSearchSelect serialises each into data-included/data-excluded/data-modifier.
    window.readSearchSelect(form);
    const widgets = form.querySelectorAll<HTMLElement>(
      '[data-search-select][data-search-select-mode="filter"]'
    );
    widgets.forEach((widget) => {
      const field = widget.getAttribute("data-name");
      if (!field) return;
      const included = parseJSONAttr<PillEntry>(widget, "data-included");
      const excluded = parseJSONAttr<PillEntry>(widget, "data-excluded");
      // Two orthogonal axes: a presence modifier (NOT_NULL/IS_NULL) from the
      // pinned (Any)/(None) pseudo-options clears the value set and has no
      // values; the non-presence modifier (INCLUDES_ALL/INCLUDES_ONLY) governs
      // how the include set matches.  When neither is set the implicit default
      // is INCLUDES ("any").  Must match Python _PRESENCE_MODIFIERS.
      const modifier = widget.getAttribute("data-modifier");
      const isPresence = modifier === "NOT_NULL" || modifier === "IS_NULL";
      if (isPresence) {
        filter[field] = { modifier };
      } else if (included.length > 0 || excluded.length > 0) {
        // All filter pills carry {id, label}; store them as-is so the filter
        // URL and saved presets are self-describing (Stash-style).
        filter[field] = {
          value: included.map((item) => ({ id: item.id, label: item.label })),
          excludes: excluded.map((item) => ({ id: item.id, label: item.label })),
          modifier: modifier || "INCLUDES",
        };
      }
    });

    // 1. Text Fields
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
        `[name="${textField.name}-modifier"]:checked`
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

    // 2. Boolean Fields (Radio Button Groups)
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
        `[name="${booleanField.name}"]:checked`
      );
      if (element) {
        const value = element.value === "true";
        filter[booleanField.key] = criterion(value, null, "EQUALS");
      }
    });

    // 3. Range Fields
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

      if (rangeField.ignoreZeroZero && valueMin === 0 && valueMax === 0) {
        return; // both 0 means slider at default
      }

      const result = buildRangeCriterion(valueMin, valueMax);
      if (result !== null) filter[rangeField.key] = result;
    });

    // 4. Date Range Fields — ISO date strings from <input type="date">; no
    // numeric coercion. Same modifier derivation as numeric ranges.
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

  /** Extract the current page's base URL (without query string). */
  function baseUrl(): string {
    return window.location.pathname;
  }

  /** Safely parse a JSON attribute, returning empty array on failure. */
  function parseJSONAttr<T>(element: Element, attr: string): T[] {
    const raw = element.getAttribute(attr);
    if (!raw) return [];
    try {
      return JSON.parse(raw);
    } catch {
      return [];
    }
  }

  /** Map the current path to a preset mode. */
  function presetMode(): string {
    const path = window.location.pathname;
    if (path.indexOf("session") !== -1) return "sessions";
    if (path.indexOf("purchase") !== -1) return "purchases";
    if (path.indexOf("device") !== -1) return "devices";
    if (path.indexOf("platform") !== -1) return "platforms";
    if (path.indexOf("playevent") !== -1) return "playevents";
    return "games";
  }

  /**
   * Called on filter bar form submit.
   * Serializes filter fields, navigates to URL with filter param.
   */
  window.applyFilterBar = (event: Event): boolean => {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    const filter = buildFilterJSON(form);
    const filterString = JSON.stringify(filter);
    let url = baseUrl();
    if (filterString && filterString !== "{}") {
      url += "?filter=" + encodeURIComponent(filterString);
    }
    window.location.href = url;
    return false;
  };

  /**
   * Clear all filter fields and reload the unfiltered view.
   */
  window.clearFilterBar = (formId: string, _filterInputId: string): void => {
    const form = document.getElementById(formId) as HTMLFormElement | null;
    if (!form) return;
    form.reset();
    window.location.href = baseUrl();
  };

  // ── Presets ─────────────────────────────────────────────────────────────

  /** Fetch and render the preset list. */
  function loadPresets(): void {
    const dropdown = document.getElementById("preset-dropdown");
    if (!dropdown) return;
    const url = dropdown.getAttribute("data-preset-list-url");
    if (!url) return;

    const mode = presetMode();
    let query = "";
    if (url.indexOf("mode=") === -1) {
      query = (url.indexOf("?") !== -1 ? "&" : "?") + "mode=" + mode;
    }

    fetch(url + query, { credentials: "same-origin" })
      .then((response) => {
        if (!response.ok) throw new Error("Failed to load presets");
        return response.text();
      })
      .then((html) => {
        dropdown.innerHTML = html;
        // Re-attach delete handlers (list_presets view uses onclick attributes,
        // but we also need to wire up inline handlers if they use data attributes)
        setupPresetDeleteHandlers(dropdown);
      })
      .catch((error) => {
        dropdown.innerHTML =
          '<span class="text-sm text-body italic">Presets unavailable</span>';
        console.error(error);
      });
  }

  /** Wire up click handlers for preset delete buttons. */
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
            // Remove the parent <li>
            const listItem = link.closest("li");
            if (listItem) listItem.remove();
            // If no items left, show empty message
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

  /** Enable/disable the input text box depending on selected string modifier. */
  window.toggleStringFilterInput = (radio: HTMLInputElement): void => {
    const container = radio.closest(".flex-col");
    if (!container) return;
    const textInput = container.querySelector<HTMLInputElement>('input[type="text"]');
    if (!textInput) return;

    // Find the currently checked radio in the container
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
  };

  /** Show the preset name input field and the confirm button. */
  window.showPresetNameInput = (): void => {
    const input = document.getElementById("preset-name-input");
    const saveButton = document.getElementById("save-preset-btn");
    const confirmButton = document.getElementById("confirm-save-preset-btn");
    if (input) input.classList.remove("hidden");
    if (saveButton) saveButton.classList.add("hidden");
    if (confirmButton) confirmButton.classList.remove("hidden");
    if (input) input.focus();
  };

  /** Save the current filter as a named preset. */
  window.savePreset = (formId: string, _filterInputId: string, saveUrl: string): void => {
    const input = document.getElementById("preset-name-input") as HTMLInputElement | null;
    const name = input ? input.value.trim() : "";
    if (!name) {
      if (input) input.classList.add("border-red-500");
      return;
    }

    const form = document.getElementById(formId);
    const filterObject = form ? buildFilterJSON(form) : {};

    const body = new URLSearchParams();
    body.append("name", name);
    body.append("mode", presetMode());
    body.append("filter", JSON.stringify(filterObject));

    fetch(saveUrl, {
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
        // Reset UI
        if (input) {
          input.value = "";
          input.classList.add("hidden");
          input.classList.remove("border-red-500");
        }
        const saveButton = document.getElementById("save-preset-btn");
        const confirmButton = document.getElementById("confirm-save-preset-btn");
        if (saveButton) saveButton.classList.remove("hidden");
        if (confirmButton) confirmButton.classList.add("hidden");
        // Refresh the preset list
        loadPresets();
      })
      .catch((error) => {
        console.error("Failed to save preset:", error);
      });
  };

  /** Extract CSRF token from the page. */
  function getCsrfToken(): string {
    const cookie = document.cookie
      .split("; ")
      .find((row) => row.startsWith("csrftoken="));
    if (cookie) return cookie.split("=")[1];
    const element = document.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]');
    return element ? element.value : "";
  }

  // ── Init on page load ───────────────────────────────────────────────────

  // ── Inject the search input into a filter form ──
  function injectSearchInput(form: HTMLElement): void {
    if (form.querySelector('[name="filter-search"]')) return; // already added
    const input = document.createElement("input");
    input.type = "text";
    input.name = "filter-search";
    input.placeholder = "Search…";
    input.className =
      "block w-full rounded-base border border-default-medium bg-neutral-secondary-medium text-sm text-heading p-2 mb-4 focus:ring-brand focus:border-brand";
    // Pre-fill from existing filter JSON
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

  /**
   * Enable deselect-on-click behavior for filter radio buttons.
   */
  function setupDeselectableRadios(): void {
    document.querySelectorAll<DeselectableRadio>('input[type="radio"]').forEach((radio) => {
      radio.addEventListener("click", function (this: DeselectableRadio) {
        if (this.wasChecked) {
          this.checked = false;
          this.wasChecked = false;
          this.dispatchEvent(new Event("change", { bubbles: true }));
        } else {
          const name = this.getAttribute("name");
          if (name) {
            document
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

  /**
   * Set up event listeners for string modifier radio buttons.
   */
  function setupStringFilters(): void {
    document
      .querySelectorAll<HTMLInputElement>("input[data-string-modifier-radio]")
      .forEach((radio) => {
        radio.addEventListener("change", function (this: HTMLInputElement) {
          window.toggleStringFilterInput(this);
        });
      });
  }

  onSwap('[id^="filter-bar-form"]', (form) => {
    injectSearchInput(form as HTMLElement);
    setupDeselectableRadios();
    setupStringFilters();
    loadPresets();
  });
})();
