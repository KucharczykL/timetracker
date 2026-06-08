/**
 * SearchSelect widget — a search box paired with a dropdown of options.
 * Multi-select renders chosen items as removable pills (inline with the search
 * box), each backed by a hidden <input>. Single-select renders no pill: the
 * committed label lives inside the search box (which doubles as a combobox —
 * focus clears it to search, picking an option fills it), with a lone hidden
 * <input> carrying the value. Both keep hidden inputs so Django validation works.
 *
 * Filter mode (data-search-select-mode="filter", rendered by FilterSelect): value rows
 * carry +/− buttons that add include (✓) / exclude (✗) pills, plus pinned
 * modifier pseudo-options ((Any)/(None)) that are mutually exclusive with value
 * pills. Filter widgets have no hidden inputs; readSearchSelect serialises their
 * state into data-included / data-excluded / data-modifier for the filter bar.
 *
 * initAll() runs on DOMContentLoaded + htmx:afterSwap, each widget guarded with
 * element._searchSelectInit.
 *
 * Dynamically-added rows and pills are cloned from hidden <template> elements
 * the server renders with the same Python components (Pill / SearchSelect /
 * FilterSelect). The JS only fills in the label slot ([data-search-select-label]), value,
 * and data-* attributes — so all markup and Tailwind class strings live in one
 * place (the Python components), never duplicated here.
 */
(function () {
  "use strict";

  var DEBOUNCE_MS = 500;

  function initAll() {
    document.querySelectorAll("[data-search-select]").forEach(function (element) {
      if (element._searchSelectInit) return;
      element._searchSelectInit = true;
      initWidget(element);
    });
  }

  function initWidget(container) {
    var search = container.querySelector("[data-search-select-search]");
    var options = container.querySelector("[data-search-select-options]");
    var pills = container.querySelector("[data-search-select-pills]");
    if (!search || !options || !pills) return;

    var name = container.getAttribute("data-name");
    var searchUrl = container.getAttribute("data-search-url");
    var isFilter = container.getAttribute("data-search-select-mode") === "filter";
    var multi = container.getAttribute("data-multi") === "true";
    var alwaysVisible = container.getAttribute("data-always-visible") === "true";
    var itemsScroll = parseInt(container.getAttribute("data-items-scroll"), 10) || 10;
    var prefetch = parseInt(container.getAttribute("data-prefetch"), 10) || 0;
    var syncUrl = container.getAttribute("data-sync-url") === "true";

    var noResults = options.querySelector("[data-search-select-no-results]");
    var debounceTimer = null;
    var pendingRequest = null; // in-flight AbortController, so newer queries win
    var hasPrefetched = false;

    function showPanel() {
      options.classList.remove("hidden");
    }
    function hidePanel() {
      if (!alwaysVisible) options.classList.add("hidden");
    }

    function setNoResults(visible) {
      if (noResults) noResults.classList.toggle("hidden", !visible);
    }

    // ── Render server-fetched rows into the panel ──
    function renderRows(items) {
      options.querySelectorAll("[data-search-select-option]").forEach(function (row) {
        row.remove();
      });
      items.slice(0, itemsScroll).forEach(function (item) {
        options.insertBefore(buildRow(item), noResults || null);
      });
      showPanel();
    }

    // ── Clone a server-rendered <template> prototype by name. The server emits
    //    the mode-appropriate prototypes, so the JS never names a class. ──
    function cloneTemplate(name) {
      var template = container.querySelector('template[data-search-select-template="' + name + '"]');
      return template
        ? template.content.firstElementChild.cloneNode(true)
        : null;
    }

    function setLabel(node, label) {
      var slot = node.querySelector("[data-search-select-label]");
      if (slot) slot.textContent = label;
    }

    function applyData(node, data) {
      data = data || {};
      Object.keys(data).forEach(function (key) {
        node.setAttribute("data-" + key, data[key]);
      });
    }

    // Build an option row by cloning the "row" template (the same prototype the
    // server renders, so fetched and pre-rendered rows are identical).
    function buildRow(option) {
      var row = cloneTemplate("row");
      if (!row) return document.createComment("ss-row");
      row.setAttribute("data-value", option.value);
      row.setAttribute("data-label", option.label);
      applyData(row, option.data);
      setLabel(row, option.label);
      row._searchSelectOption = option;
      return row;
    }

    // ── Client-side filter of the currently loaded rows. Returns the number of
    //    visible rows so the caller decides whether to show the no-results node. ──
    function filterRows(query) {
      var lower = query.toLowerCase();
      var visibleCount = 0;
      options.querySelectorAll("[data-search-select-option]").forEach(function (item) {
        var label = (item.getAttribute("data-label") || "").toLowerCase();
        var match = label.indexOf(lower) !== -1;
        item.style.display = match ? "" : "none";
        if (match) visibleCount += 1;
      });
      return visibleCount;
    }

    // ── Fetch matching rows from the server. The previous in-flight request is
    //    aborted so a slower earlier response can never overwrite a newer one. ──
    function fetchFromServer(query) {
      if (pendingRequest) pendingRequest.abort();
      pendingRequest = new AbortController();
      var url = searchUrl + "?q=" + encodeURIComponent(query);
      if (prefetch && !query) url += "&limit=" + prefetch;
      fetch(url, { credentials: "same-origin", signal: pendingRequest.signal })
        .then(function (response) {
          return response.json();
        })
        .then(function (items) {
          pendingRequest = null;
          renderRows(items);
          // Re-apply the live query: the box may hold more text than was sent.
          setNoResults(filterRows(search.value.trim()) === 0);
        })
        .catch(function (error) {
          if (error && error.name === "AbortError") return; // superseded
          pendingRequest = null;
          setNoResults(true);
        });
    }

    // Called on every keystroke. With a search_url, filter the loaded window
    // instantly (zero latency) and debounce a server request for the rest;
    // no-results stays hidden until the response decides it, to avoid a flash
    // over an incomplete window. Without a search_url the loaded set is complete,
    // so the client-side filter is authoritative.
    function runSearch() {
      var query = search.value.trim();
      showPanel();
      if (searchUrl) {
        filterRows(query);
        setNoResults(false);
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function () {
          fetchFromServer(query);
        }, DEBOUNCE_MS);
      } else {
        setNoResults(filterRows(query) === 0);
      }
    }

    // ── Single-select combobox: the search box shows the committed label;
    //    focusing clears it to search, blurring restores it (or deselects). ──
    if (!multi) container._searchSelectLabel = search.value;

    search.addEventListener("focus", function () {
      if (!multi) {
        // Hide the committed label so the box becomes a fresh search field.
        search.value = "";
        container._searchSelectDirty = false;
      }
      showPanel();
      if (searchUrl) {
        if (prefetch && !hasPrefetched) {
          // Seed the window immediately on first open (not debounced).
          hasPrefetched = true;
          fetchFromServer("");
        } else {
          // Show whatever is already loaded; the server decides no-results.
          filterRows(search.value.trim());
          setNoResults(false);
        }
      } else {
        setNoResults(filterRows(search.value.trim()) === 0);
      }
    });
    search.addEventListener("input", function () {
      if (!multi) container._searchSelectDirty = true;
      runSearch();
    });
    if (!multi) {
      search.addEventListener("blur", function () {
        // Defer so an option click (which fires before blur settles) wins.
        setTimeout(function () {
          if (container._searchSelectDirty && search.value.trim() === "") {
            // User intentionally cleared the box → deselect.
            pills.innerHTML = "";
            container._searchSelectLabel = "";
            emitChange(null);
          } else {
            // Focused-and-left, or typed a partial query without picking →
            // restore the committed label (no-op right after a selection).
            search.value = container._searchSelectLabel || "";
          }
        }, 120);
      });
    }

    // Clicking an option must not blur the input before the click selects.
    options.addEventListener("mousedown", function (event) {
      event.preventDefault();
    });

    // ── Option click → select (form mode) or include/exclude (filter mode) ──
    options.addEventListener("click", function (event) {
      if (isFilter) {
        handleFilterOptionClick(e);
        return;
      }
      var row = event.target.closest("[data-search-select-option]");
      if (!row) return;
      selectOption(optionFromRow(row));
    });

    function handleFilterOptionClick(e) {
      // Pinned modifier pseudo-option → set the (mutually exclusive) modifier.
      var modifierRow = event.target.closest("[data-search-select-modifier-option]");
      if (modifierRow) {
        setModifier(
          modifierRow.getAttribute("data-search-select-modifier-option"),
          modifierRow.getAttribute("data-label")
        );
        return;
      }
      // Include / exclude button on a value row.
      var button = event.target.closest("[data-search-select-action]");
      if (!button) return;
      var row = button.closest("[data-search-select-option]");
      if (!row) return;
      addFilterPill(optionFromRow(row), button.getAttribute("data-search-select-action"));
    }

    // Add (or re-type) an include/exclude pill for a value. Selecting any value
    // clears an active modifier — the two are mutually exclusive.
    function addFilterPill(option, kind) {
      clearModifier();
      var existing = pills.querySelector(
        '[data-pill][data-value="' + cssEscape(option.value) + '"]'
      );
      if (existing) existing.remove();
      pills.appendChild(buildFilterValuePill(option, kind));
      emitChange(null);
    }

    function buildFilterValuePill(option, kind) {
      var pill = cloneTemplate(kind === "include" ? "pill-include" : "pill-exclude");
      pill.setAttribute("data-value", option.value);
      pill.setAttribute("data-label", option.label);
      applyData(pill, option.data);
      setLabel(pill, option.label);
      return pill;
    }

    // Set the lone modifier pill, clearing all value pills (mutual exclusivity).
    function setModifier(modifierValue, label) {
      pills.innerHTML = "";
      var pill = cloneTemplate("pill-modifier");
      pill.setAttribute("data-search-select-modifier", modifierValue);
      setLabel(pill, label);
      pills.appendChild(pill);
      container.setAttribute("data-modifier", modifierValue);
      hidePanel();
      emitChange(null);
    }

    function clearModifier() {
      var modifierPill = pills.querySelector("[data-search-select-modifier]");
      if (modifierPill) modifierPill.remove();
      container.removeAttribute("data-modifier");
    }

    function optionFromRow(row) {
      if (row._searchSelectOption) return row._searchSelectOption;
      var data = {};
      Object.keys(row.dataset).forEach(function (key) {
        if (key !== "value" && key !== "label" && key !== "ssOption") {
          data[key] = row.dataset[key];
        }
      });
      return {
        value: row.getAttribute("data-value"),
        label: row.getAttribute("data-label"),
        data: data,
      };
    }

    function selectOption(option) {
      if (multi) {
        if (!pills.querySelector('input[value="' + cssEscape(option.value) + '"]')) {
          addPill(option);
        }
      } else {
        // Single-select: no pill — show the label in the search box and keep a
        // lone hidden input under [data-search-select-pills] for submission.
        pills.innerHTML = "";
        pills.appendChild(buildHidden(option.value));
        search.value = option.label;
        container._searchSelectLabel = option.label;
        container._searchSelectDirty = false;
        hidePanel();
      }
      emitChange(option);
    }

    function addPill(option) {
      var pill = buildPill(option);
      if (pill) pills.appendChild(pill);
      pills.appendChild(buildHidden(option.value));
    }

    function buildPill(option) {
      var pill = cloneTemplate("pill");
      if (!pill) return null;
      pill.setAttribute("data-value", option.value);
      applyData(pill, option.data);
      setLabel(pill, option.label);
      return pill;
    }

    function buildHidden(value) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      return input;
    }

    // ── Pill × → remove ──
    pills.addEventListener("click", function (event) {
      var removeButton = event.target.closest("[data-pill-remove]");
      if (!removeButton) return;
      var pill = removeButton.closest("[data-pill]");
      if (!pill) return;
      if (isFilter) {
        // Filter pills have no hidden input; a modifier pill also clears the
        // container flag.
        if (pill.hasAttribute("data-search-select-modifier")) {
          container.removeAttribute("data-modifier");
        }
        pill.remove();
        emitChange(null);
        return;
      }
      var value = pill.getAttribute("data-value");
      pill.remove();
      var hidden = pills.querySelector('input[value="' + cssEscape(value) + '"]');
      if (hidden) hidden.remove();
      emitChange(null);
    });

    function currentValues() {
      return Array.prototype.map.call(
        pills.querySelectorAll('input[type="hidden"]'),
        function (input) {
          return input.value;
        }
      );
    }

    function emitChange(last) {
      var values = currentValues();
      if (syncUrl) syncToUrl(values);
      container.dispatchEvent(
        new CustomEvent("search-select:change", {
          bubbles: true,
          detail: { name: name, values: values, last: last },
        })
      );
    }

    function syncToUrl(values) {
      var params = new URLSearchParams(window.location.search);
      params.delete(name);
      values.forEach(function (v) {
        params.append(name, v);
      });
      var qs = params.toString();
      history.replaceState(null, "", qs ? "?" + qs : window.location.pathname);
    }

    // On init, restore from URL params if the server supplied no selected pills.
    if (syncUrl && !pills.querySelector("[data-pill]")) {
      var initial = new URLSearchParams(window.location.search).getAll(name);
      initial.forEach(function (v) {
        addPill({ value: v, label: v, data: {} });
      });
    }

    // ── Close panel on outside click ──
    document.addEventListener("click", function (event) {
      if (!container.contains(event.target)) hidePanel();
    });
  }

  /** Minimal escape for use inside an attribute-value selector. */
  function cssEscape(value) {
    return String(value).replace(/["\\]/g, "\\$&");
  }

  // Serialise each widget's current state onto data-* attributes for the caller.
  // Form widgets expose data-values (the submitted hidden-input values); filter
  // widgets expose data-included / data-excluded / data-modifier for the filter
  // bar to read.
  window.readSearchSelect = function (form) {
    form.querySelectorAll("[data-search-select]").forEach(function (container) {
      var pills = container.querySelector("[data-search-select-pills]");
      if (container.getAttribute("data-search-select-mode") === "filter") {
        var included = [];
        var excluded = [];
        var modifier = "";
        if (pills) {
          pills.querySelectorAll("[data-pill]").forEach(function (pill) {
            var pillModifier = pill.getAttribute("data-search-select-modifier");
            if (pillModifier) {
              modifier = pillModifier;
              return;
            }
            var value = pill.getAttribute("data-value");
            if (pill.getAttribute("data-search-select-type") === "exclude") {
              excluded.push(value);
            } else {
              included.push(value);
            }
          });
        }
        container.setAttribute("data-included", JSON.stringify(included));
        container.setAttribute("data-excluded", JSON.stringify(excluded));
        if (modifier) container.setAttribute("data-modifier", modifier);
        else container.removeAttribute("data-modifier");
        return;
      }
      var values = pills
        ? Array.prototype.map.call(
            pills.querySelectorAll('input[type="hidden"]'),
            function (input) {
              return input.value;
            }
          )
        : [];
      container.setAttribute("data-values", JSON.stringify(values));
    });
  };

  document.addEventListener("DOMContentLoaded", initAll);
  document.addEventListener("htmx:afterSwap", initAll);
})();
