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

  /** Read a raw <input> value as string, or "" if not found. */
  function stringValue(form, name) {
    var el = form.querySelector('[name="' + name + '"]');
    return el ? el.value : "";
  }

  /**
   * Derive a range criterion ({value, value2?, modifier}) from a (min, max)
   * pair, or null if both bounds are empty. Shared by the numeric-range and
   * date-range serializers.
   */
  function buildRangeCriterion(vMin, vMax) {
    if (vMin !== "" && vMax !== "") return criterion(vMin, vMax, "BETWEEN");
    if (vMin !== "") return criterion(vMin, null, "GREATER_THAN");
    if (vMax !== "") return criterion(vMax, null, "LESS_THAN");
    return null;
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

    // ── Search field ──
    var searchInput = form.querySelector('[name="filter-search"]');
    if (searchInput && searchInput.value.trim()) {
        filter.search = { value: searchInput.value.trim(), modifier: "INCLUDES" };
    }

    // ── FilterSelect widgets (data-search-select-mode="filter") ──
    // readSearchSelect serialises each into data-included/data-excluded/data-modifier.
    readSearchSelect(form);
    var widgets = form.querySelectorAll('[data-search-select][data-search-select-mode="filter"]');
    widgets.forEach(function (widget) {
      var field = widget.getAttribute("data-name");
      var included = parseJSONAttr(widget, "data-included");
      var excluded = parseJSONAttr(widget, "data-excluded");
      // Two orthogonal axes: a presence modifier (NOT_NULL/IS_NULL) from the
      // pinned (Any)/(None) pseudo-options clears the value set and has no
      // values; the non-presence modifier (INCLUDES_ALL/INCLUDES_ONLY) governs
      // how the include set matches.  When neither is set the implicit default
      // is INCLUDES ("any").  Must match Python _PRESENCE_MODIFIERS.
      var modifier = widget.getAttribute("data-modifier");
      var IS_PRESENCE = modifier === "NOT_NULL" || modifier === "IS_NULL";
      if (IS_PRESENCE) {
        filter[field] = { modifier: modifier };
      } else if (included.length > 0 || excluded.length > 0) {
        // All filter pills carry {id, label}; store them as-is so the filter
        // URL and saved presets are self-describing (Stash-style).
        filter[field] = {
          value: included.map(function (item) { return {id: item.id, label: item.label}; }),
          excludes: excluded.map(function (item) { return {id: item.id, label: item.label}; }),
          modifier: modifier || "INCLUDES",
        };
      }
    });

    // 1. Text Fields
    var textFields = [
      { name: "filter-price_currency", key: "price_currency" },
      { name: "filter-converted_currency", key: "converted_currency" },
      { name: "filter-name", key: "name" },
      { name: "filter-group", key: "group" },
      { name: "filter-playevent_note", key: "playevent_note" },
      { name: "filter-note", key: "note" }
    ];
    textFields.forEach(function (tf) {
      var modifierEl = form.querySelector('[name="' + tf.name + '-modifier"]:checked');
      var modifier = modifierEl ? modifierEl.value : "EQUALS";
      
      var isPresence = modifier === "IS_NULL" || modifier === "NOT_NULL";
      if (isPresence) {
        filter[tf.key] = { modifier: modifier };
      } else {
        var el = form.querySelector('[name="' + tf.name + '"]');
        if (el && el.value.trim()) {
          filter[tf.key] = { value: el.value.trim(), modifier: modifier };
        }
      }
    });

    // 2. Boolean Fields (Radio Button Groups)
    var booleanFields = [
      { name: "filter-mastered", key: "mastered" },
      { name: "filter-emulated", key: "emulated" },
      { name: "filter-active", key: "is_active" },
      { name: "filter-refunded", key: "is_refunded" },
      { name: "filter-infinite", key: "infinite" },
      { name: "filter-needs-price-update", key: "needs_price_update" },
      { name: "filter-purchase-refunded", key: "purchase_refunded" },
      { name: "filter-purchase-infinite", key: "purchase_infinite" },
      { name: "filter-session-emulated", key: "session_emulated" }
    ];
    booleanFields.forEach(function (bf) {
      var el = form.querySelector('[name="' + bf.name + '"]:checked');
      if (el) {
        var val = el.value === "true";
        filter[bf.key] = criterion(val, null, "EQUALS");
      }
    });

    // 3. Range Fields
    var rangeFields = [
      { prefix: "filter-year", key: "year_released" },
      { prefix: "filter-original-year", key: "original_year_released" },
      { prefix: "filter-session-count", key: "session_count" },
      { prefix: "filter-session-average", key: "session_average" },
      { prefix: "filter-purchase-count", key: "purchase_count" },
      { prefix: "filter-playevent-count", key: "playevent_count" },
      { prefix: "filter-duration-total-minutes", key: "duration_total_minutes" },
      { prefix: "filter-duration-manual-minutes", key: "duration_manual_minutes" },
      { prefix: "filter-duration-calculated-minutes", key: "duration_calculated_minutes" },
      { prefix: "filter-manual-playtime-minutes", key: "manual_playtime_minutes" },
      { prefix: "filter-calculated-playtime-minutes", key: "calculated_playtime_minutes" },
      { prefix: "filter-num-purchases", key: "num_purchases" },
      { prefix: "filter-price", key: "price" },
      { prefix: "filter-purchase-price-total", key: "purchase_price_total" },
      { prefix: "filter-purchase-price-any", key: "purchase_price_any" },
      { prefix: "filter-days-to-finish", key: "days_to_finish" },
      { prefix: "filter-playtime", key: "playtime_minutes", convert: function(v) { return Math.round(v * 60); }, ignoreZeroZero: true }
    ];

    rangeFields.forEach(function (rf) {
      var vMin = numberValue(form, rf.prefix + "-min");
      var vMax = numberValue(form, rf.prefix + "-max");

      if (rf.convert) {
        if (vMin !== "") vMin = rf.convert(vMin);
        if (vMax !== "") vMax = rf.convert(vMax);
      }

      if (rf.ignoreZeroZero && vMin === 0 && vMax === 0) {
        return; // both 0 means slider at default
      }

      var c = buildRangeCriterion(vMin, vMax);
      if (c !== null) filter[rf.key] = c;
    });

    // 4. Date Range Fields — ISO date strings from <input type="date">; no
    // numeric coercion. Same modifier derivation as numeric ranges.
    var dateRangeFields = [
      { prefix: "filter-date-purchased", key: "date_purchased" },
      { prefix: "filter-date-refunded", key: "date_refunded" },
    ];
    dateRangeFields.forEach(function (df) {
      var vMin = stringValue(form, df.prefix + "-min");
      var vMax = stringValue(form, df.prefix + "-max");
      var c = buildRangeCriterion(vMin, vMax);
      if (c !== null) filter[df.key] = c;
    });

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
    var path = window.location.pathname;
    if (path.indexOf("session") !== -1) mode = "sessions";
    else if (path.indexOf("purchase") !== -1) mode = "purchases";
    else if (path.indexOf("device") !== -1) mode = "devices";
    else if (path.indexOf("platform") !== -1) mode = "platforms";
    else if (path.indexOf("playevent") !== -1) mode = "playevents";

    var query = "";
    if (url.indexOf("mode=") === -1) {
      query = (url.indexOf("?") !== -1 ? "&" : "?") + "mode=" + mode;
    }

    fetch(url + query, { credentials: "same-origin" })
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

  /** Enable/disable the input text box depending on selected string modifier. */
  window.toggleStringFilterInput = function (radio) {
    var container = radio.closest(".flex-col");
    if (!container) return;
    var textInput = container.querySelector('input[type="text"]');
    if (!textInput) return;
    
    // Find the currently checked radio in the container
    var checkedRadio = container.querySelector('input[type="radio"]:checked');
    var val = checkedRadio ? checkedRadio.value : "";
    
    if (val === "IS_NULL" || val === "NOT_NULL") {
      textInput.disabled = true;
      textInput.value = "";
      textInput.classList.add("opacity-50", "cursor-not-allowed");
    } else {
      textInput.disabled = false;
      textInput.classList.remove("opacity-50", "cursor-not-allowed");
    }
  };

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
    var path = window.location.pathname;
    if (path.indexOf("session") !== -1) mode = "sessions";
    else if (path.indexOf("purchase") !== -1) mode = "purchases";
    else if (path.indexOf("device") !== -1) mode = "devices";
    else if (path.indexOf("platform") !== -1) mode = "platforms";
    else if (path.indexOf("playevent") !== -1) mode = "playevents";
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

  /**
   * Enable deselect-on-click behavior for filter radio buttons.
   */
  function setupDeselectableRadios() {
    document.querySelectorAll('input[type="radio"]').forEach(function (radio) {
      radio.addEventListener('click', function (e) {
        if (this.wasChecked) {
          this.checked = false;
          this.wasChecked = false;
          this.dispatchEvent(new Event('change', { bubbles: true }));
        } else {
          var name = this.getAttribute('name');
          if (name) {
            document.querySelectorAll('input[type="radio"][name="' + name + '"]').forEach(function (r) {
              r.wasChecked = false;
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
  function setupStringFilters() {
    document.querySelectorAll('input[data-string-modifier-radio]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        window.toggleStringFilterInput(this);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    injectSearchInputs();
    setupDeselectableRadios();
    setupStringFilters();
    loadPresets();
  });
})();
