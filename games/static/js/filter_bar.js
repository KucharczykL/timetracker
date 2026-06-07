/**
 * Filter bar — vanilla JavaScript implementation.
 *
 * Handles form submission, preset loading/saving, and preset list rendering.
 * No HTMX — plain fetch() and window.location for all interactions.
 */
(function () {
  "use strict";

  /** Build a criterion object from a value and optional second value. */
  function criterion(value, value2, modifier) {
    var c = { value: value, modifier: modifier };
    if (value2 !== null && value2 !== undefined && value2 !== "") {
      c.value2 = value2;
    }
    return c;
  }

  /** Read a <select> element's value, or "" if not found. */
  function selectValue(form, name) {
    var el = form.querySelector('[name="' + name + '"]');
    return el ? el.value : "";
  }

  /** Read an <input type="number"> value, or "" if not found. */
  function numberValue(form, name) {
    var el = form.querySelector('[name="' + name + '"]');
    if (!el || el.value === "") return "";
    var val = parseFloat(el.value);
    return isNaN(val) ? "" : val;
  }

  /** Read all checked checkboxes with a given name, returning an array of ints. */
  function checkedValues(form, name) {
    var els = form.querySelectorAll('[name="' + name + '"]:checked');
    var ids = [];
    els.forEach(function (el) {
      var v = parseInt(el.value, 10);
      if (!isNaN(v)) ids.push(v);
    });
    return ids;
  }

  /**
   * Build the filter JSON object from form field values.
   * Returns a plain object ready for JSON.stringify.
   */
  function buildFilterJSON(form) {
    var filter = {};
    var yearMin = numberValue(form, "filter-year-min");
    var yearMax = numberValue(form, "filter-year-max");
    var playMin = numberValue(form, "filter-playtime-min");
    var playMax = numberValue(form, "filter-playtime-max");
    var mastered = form.querySelector('[name="filter-mastered"]');

    // ── Search field ──
    var searchInput = form.querySelector('[name="filter-search"]');
    if (searchInput && searchInput.value.trim()) {
        filter.search = { value: searchInput.value.trim(), modifier: "INCLUDES" };
    }

    // ── FilterSelect widgets (data-ss-mode="filter") ──
    // readSearchSelect serialises each into data-included/data-excluded/data-modifier.
    readSearchSelect(form);
    var widgets = form.querySelectorAll('[data-search-select][data-ss-mode="filter"]');
    widgets.forEach(function (widget) {
      var field = widget.getAttribute("data-name");
      var included = parseJSONAttr(widget, "data-included");
      var excluded = parseJSONAttr(widget, "data-excluded");
      var modifier = widget.getAttribute("data-modifier");
      if (modifier === "NOT_NULL" || modifier === "IS_NULL") {
        filter[field] = { modifier: modifier };
      } else if (included.length > 0 || excluded.length > 0) {
        var isIdField =
          field === "platform" ||
          field === "game" ||
          field === "device" ||
          field === "games";
        filter[field] = {
          value: isIdField ? included.map(Number) : included,
          excludes: isIdField ? excluded.map(Number) : excluded,
          modifier: modifier || "INCLUDES",
        };
      }
    });

    // ── Session-specific fields ──
    var pageIsSessions =
      !!form.querySelector('[data-search-select][data-ss-mode="filter"][data-name="game"]');

    // Emulated checkbox (sessions page)
    var emulated = form.querySelector('[name="filter-emulated"]');
    if (emulated && emulated.checked) {
      filter.emulated = criterion(true, null, "EQUALS");
    }

    // Active checkbox (sessions page)
    var active = form.querySelector('[name="filter-active"]');
    if (active && active.checked) {
      filter.is_active = criterion(true, null, "EQUALS");
    }

    if (yearMin !== "" && yearMax !== "") {
      filter.year_released = criterion(yearMin, yearMax, "BETWEEN");
    } else if (yearMin !== "") {
      filter.year_released = criterion(yearMin, null, "GREATER_THAN");
    } else if (yearMax !== "") {
      filter.year_released = criterion(yearMax, null, "LESS_THAN");
    }

    if (playMin !== "" || playMax !== "") {
      var pMin = playMin !== "" ? Math.round(playMin * 60) : 0;
      var pMax = playMax !== "" ? Math.round(playMax * 60) : 0;
      // Skip if both are 0 — means slider is at default (no real filter)
      if (pMin === 0 && pMax === 0) {
        // don't add filter
      } else {
        var durKey = pageIsSessions ? "duration_minutes" : "playtime_minutes";
        if (playMin !== "" && playMax !== "") {
          filter[durKey] = criterion(pMin, pMax, "BETWEEN");
        } else if (playMin !== "") {
          filter[durKey] = criterion(pMin, null, "GREATER_THAN");
        } else if (playMax !== "") {
          filter[durKey] = criterion(pMax, null, "LESS_THAN");
        }
      }
    }

    if (mastered && mastered.checked) {
      filter.mastered = criterion(true, null, "EQUALS");
    }

    return filter;
  }

  /** Extract the current page's base URL (without query string). */
  function baseUrl() {
    return window.location.pathname;
  }

  /** Safely parse a JSON attribute, returning empty array on failure. */
  function parseJSONAttr(el, attr) {
    var raw = el.getAttribute(attr);
    if (!raw) return [];
    try { return JSON.parse(raw); } catch (e) { return []; }
  }

  /**
   * Called on filter bar form submit.
   * Serializes filter fields, navigates to URL with filter param.
   */
  window.applyFilterBar = function (event) {
    event.preventDefault();
    var form = event.target;
    var filter = buildFilterJSON(form);
    var filterStr = JSON.stringify(filter);
    var url = baseUrl();
    if (filterStr && filterStr !== "{}") {
      url += "?filter=" + encodeURIComponent(filterStr);
    }
    window.location.href = url;
    return false;
  };

  /**
   * Clear all filter fields and reload the unfiltered view.
   */
  window.clearFilterBar = function (formId, filterInputId) {
    var form = document.getElementById(formId);
    if (!form) return;
    form.reset();
    window.location.href = baseUrl();
  };

  // ── Presets ─────────────────────────────────────────────────────────────

  /** Fetch and render the preset list. */
  function loadPresets() {
    var dropdown = document.getElementById("preset-dropdown");
    if (!dropdown) return;
    var url = dropdown.getAttribute("data-preset-list-url");
    if (!url) return;

    var mode = "games";
    if (window.location.pathname.indexOf("session") !== -1) mode = "sessions";
    else if (window.location.pathname.indexOf("purchase") !== -1) mode = "purchases";

    fetch(url + "?mode=" + mode, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("Failed to load presets");
        return r.text();
      })
      .then(function (html) {
        dropdown.innerHTML = html;
        // Re-attach delete handlers (list_presets view uses onclick attributes,
        // but we also need to wire up inline handlers if they use data attributes)
        setupPresetDeleteHandlers(dropdown);
      })
      .catch(function (err) {
        dropdown.innerHTML =
          '<span class="text-sm text-body italic">Presets unavailable</span>';
        console.error(err);
      });
  }

  /** Wire up click handlers for preset delete buttons. */
  function setupPresetDeleteHandlers(container) {
    var deleteLinks = container.querySelectorAll('[data-delete-preset]');
    deleteLinks.forEach(function (link) {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        var presetId = link.getAttribute("data-delete-preset");
        var deleteUrl = link.getAttribute("href");
        if (!deleteUrl) return;
        if (!confirm("Delete this preset?")) return;
        fetch(deleteUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRFToken": getCsrfToken() },
        })
          .then(function () {
            // Remove the parent <li>
            var li = link.closest("li");
            if (li) li.remove();
            // If no items left, show empty message
            var ul = container.querySelector("ul");
            if (ul && ul.querySelectorAll("li").length === 0) {
              ul.innerHTML =
                '<li class="px-4 py-2 text-sm text-body italic">No saved presets</li>';
            }
          })
          .catch(function (err) {
            console.error("Delete failed:", err);
          });
      });
    });
  }

  /** Show the preset name input field and the confirm button. */
  window.showPresetNameInput = function () {
    var input = document.getElementById("preset-name-input");
    var saveBtn = document.getElementById("save-preset-btn");
    var confirmBtn = document.getElementById("confirm-save-preset-btn");
    if (input) input.classList.remove("hidden");
    if (saveBtn) saveBtn.classList.add("hidden");
    if (confirmBtn) confirmBtn.classList.remove("hidden");
    if (input) input.focus();
  };

  /** Save the current filter as a named preset. */
  window.savePreset = function (formId, filterInputId, saveUrl) {
    var input = document.getElementById("preset-name-input");
    var name = input ? input.value.trim() : "";
    if (!name) {
      if (input) input.classList.add("border-red-500");
      return;
    }

    var filterInput = document.getElementById(filterInputId);
    var form = document.getElementById(formId);
    var filterObj = form ? buildFilterJSON(form) : {};

    var body = new URLSearchParams();
    body.append("name", name);
    var mode = "games";
    if (window.location.pathname.indexOf("session") !== -1) mode = "sessions";
    else if (window.location.pathname.indexOf("purchase") !== -1) mode = "purchases";
    body.append("mode", mode);
    body.append("filter", JSON.stringify(filterObj));

    fetch(saveUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": getCsrfToken(),
      },
      body: body.toString(),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("Save failed");
        // Reset UI
        if (input) {
          input.value = "";
          input.classList.add("hidden");
          input.classList.remove("border-red-500");
        }
        var saveBtn = document.getElementById("save-preset-btn");
        var confirmBtn = document.getElementById("confirm-save-preset-btn");
        if (saveBtn) saveBtn.classList.remove("hidden");
        if (confirmBtn) confirmBtn.classList.add("hidden");
        // Refresh the preset list
        loadPresets();
      })
      .catch(function (err) {
        console.error("Failed to save preset:", err);
      });
  };

  /** Extract CSRF token from the page. */
  function getCsrfToken() {
    var cookie = document.cookie
      .split("; ")
      .find(function (row) {
        return row.startsWith("csrftoken=");
      });
    if (cookie) return cookie.split("=")[1];
    var el = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return el ? el.value : "";
  }

  // ── Init on page load ───────────────────────────────────────────────────

  // ── Inject search inputs into filter forms ──
  function injectSearchInputs() {
    document.querySelectorAll('[id^="filter-bar-form"]').forEach(function (form) {
      if (form.querySelector('[name="filter-search"]')) return; // already added
      var input = document.createElement("input");
      input.type = "text";
      input.name = "filter-search";
      input.placeholder = "Search\u2026";
      input.className = "block w-full rounded-base border border-default-medium bg-neutral-secondary-medium text-sm text-heading p-2 mb-4 focus:ring-brand focus:border-brand";
      // Pre-fill from existing filter JSON
      var hidden = form.querySelector('[name="filter"]');
      if (hidden && hidden.parentNode) {
        try {
          var existing = JSON.parse(hidden.value || "{}");
          if (existing.search && existing.search.value) {
            input.value = existing.search.value;
          }
        } catch (e) {}
        hidden.parentNode.insertBefore(input, hidden.nextSibling);
      }
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    injectSearchInputs();
    loadPresets();
  });
})();
