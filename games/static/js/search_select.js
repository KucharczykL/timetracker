/**
 * SearchSelect widget — a search box paired with a dropdown of options.
 * Multi-select renders chosen items as removable pills (inline with the search
 * box), each backed by a hidden <input>. Single-select renders no pill: the
 * committed label lives inside the search box (which doubles as a combobox —
 * focus clears it to search, picking an option fills it), with a lone hidden
 * <input> carrying the value. Both keep hidden inputs so Django validation works.
 *
 * Mirrors selectable_filter.js: initAll() on DOMContentLoaded + htmx:afterSwap,
 * each widget guarded with el._ssInit.
 *
 * The pill / option class strings below are kept byte-identical to the Python
 * Pill / SearchSelect components so Tailwind generates the classes and
 * server-rendered and JS-created pills are indistinguishable.
 */
(function () {
  "use strict";

  var PILL_CLASS =
    "inline-flex items-center gap-1 px-2 py-0.5 text-sm rounded " +
    "bg-brand/15 text-heading";
  var PILL_REMOVE_CLASS =
    "ml-1 text-body hover:text-heading font-bold cursor-pointer";
  var OPTION_ROW_CLASS =
    "px-3 py-2 text-sm text-heading cursor-pointer hover:bg-brand/15";

  var DEBOUNCE_MS = 500;

  function initAll() {
    document.querySelectorAll("[data-search-select]").forEach(function (el) {
      if (el._ssInit) return;
      el._ssInit = true;
      initWidget(el);
    });
  }

  function initWidget(container) {
    var search = container.querySelector("[data-ss-search]");
    var options = container.querySelector("[data-ss-options]");
    var pills = container.querySelector("[data-ss-pills]");
    if (!search || !options || !pills) return;

    var name = container.getAttribute("data-name");
    var searchUrl = container.getAttribute("data-search-url");
    var multi = container.getAttribute("data-multi") === "true";
    var alwaysVisible = container.getAttribute("data-always-visible") === "true";
    var itemsScroll = parseInt(container.getAttribute("data-items-scroll"), 10) || 10;
    var prefetch = parseInt(container.getAttribute("data-prefetch"), 10) || 0;
    var syncUrl = container.getAttribute("data-sync-url") === "true";

    var noResults = options.querySelector("[data-ss-no-results]");
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
      options.querySelectorAll("[data-ss-option]").forEach(function (row) {
        row.remove();
      });
      items.slice(0, itemsScroll).forEach(function (item) {
        options.insertBefore(buildRow(item), noResults || null);
      });
      showPanel();
    }

    function buildRow(option) {
      var row = document.createElement("div");
      row.setAttribute("data-ss-option", "");
      row.setAttribute("data-value", option.value);
      row.setAttribute("data-label", option.label);
      row.className = OPTION_ROW_CLASS;
      var data = option.data || {};
      Object.keys(data).forEach(function (key) {
        row.setAttribute("data-" + key, data[key]);
      });
      row.textContent = option.label;
      row._ssOption = option;
      return row;
    }

    // ── Client-side filter of the currently loaded rows. Returns the number of
    //    visible rows so the caller decides whether to show the no-results node. ──
    function filterRows(query) {
      var lower = query.toLowerCase();
      var visibleCount = 0;
      options.querySelectorAll("[data-ss-option]").forEach(function (item) {
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
    if (!multi) container._ssLabel = search.value;

    search.addEventListener("focus", function () {
      if (!multi) {
        // Hide the committed label so the box becomes a fresh search field.
        search.value = "";
        container._ssDirty = false;
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
      if (!multi) container._ssDirty = true;
      runSearch();
    });
    if (!multi) {
      search.addEventListener("blur", function () {
        // Defer so an option click (which fires before blur settles) wins.
        setTimeout(function () {
          if (container._ssDirty && search.value.trim() === "") {
            // User intentionally cleared the box → deselect.
            pills.innerHTML = "";
            container._ssLabel = "";
            emitChange(null);
          } else {
            // Focused-and-left, or typed a partial query without picking →
            // restore the committed label (no-op right after a selection).
            search.value = container._ssLabel || "";
          }
        }, 120);
      });
    }

    // Clicking an option must not blur the input before the click selects.
    options.addEventListener("mousedown", function (e) {
      e.preventDefault();
    });

    // ── Option click → select ──
    options.addEventListener("click", function (e) {
      var row = e.target.closest("[data-ss-option]");
      if (!row) return;
      var option = optionFromRow(row);
      selectOption(option);
    });

    function optionFromRow(row) {
      if (row._ssOption) return row._ssOption;
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
        // lone hidden input under [data-ss-pills] for submission.
        pills.innerHTML = "";
        pills.appendChild(buildHidden(option.value));
        search.value = option.label;
        container._ssLabel = option.label;
        container._ssDirty = false;
        hidePanel();
      }
      emitChange(option);
    }

    function addPill(option) {
      pills.appendChild(buildPill(option));
      pills.appendChild(buildHidden(option.value));
    }

    function buildPill(option) {
      var pill = document.createElement("span");
      pill.className = PILL_CLASS;
      pill.setAttribute("data-pill", "");
      pill.setAttribute("data-value", option.value);
      var data = option.data || {};
      Object.keys(data).forEach(function (key) {
        pill.setAttribute("data-" + key, data[key]);
      });
      pill.appendChild(document.createTextNode(option.label));
      var remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("data-pill-remove", "");
      remove.className = PILL_REMOVE_CLASS;
      remove.setAttribute("aria-label", "Remove");
      remove.textContent = "×";
      pill.appendChild(remove);
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
    pills.addEventListener("click", function (e) {
      var removeBtn = e.target.closest("[data-pill-remove]");
      if (!removeBtn) return;
      var pill = removeBtn.closest("[data-pill]");
      if (!pill) return;
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
    document.addEventListener("click", function (e) {
      if (!container.contains(e.target)) hidePanel();
    });
  }

  /** Minimal escape for use inside an attribute-value selector. */
  function cssEscape(value) {
    return String(value).replace(/["\\]/g, "\\$&");
  }

  // Forward-looking hook (parallels readSelectableFilters): write each widget's
  // current values to a data-values JSON attribute.
  window.readSearchSelect = function (form) {
    form.querySelectorAll("[data-search-select]").forEach(function (container) {
      var pills = container.querySelector("[data-ss-pills]");
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
