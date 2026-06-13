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
 * Widgets are initialized via onSwap() (utils.js), which covers the initial
 * page load and every htmx-swapped fragment, once per widget.
 *
 * Dynamically-added rows and pills are cloned from hidden <template> elements
 * the server renders with the same Python components (Pill / SearchSelect /
 * FilterSelect). The JS only fills in the label slot ([data-search-select-label]), value,
 * and data-* attributes — so all markup and Tailwind class strings live in one
 * place (the Python components), never duplicated here.
 */
import { onSwap } from "./utils.js";

(() => {
  "use strict";

  const DEBOUNCE_MS = 100;

  // Must match Python common/components/filters.py:_PRESENCE_MODIFIERS.
  // These modifiers are mutually exclusive with value pills — selecting
  // one clears all value pills.  Non-presence modifiers (INCLUDES_ALL,
  // INCLUDES_ONLY) coexist with value pills.
  const PRESENCE_MODIFIERS = ["NOT_NULL", "IS_NULL"];

  const initWidget = (container) => {
    const search = container.querySelector("[data-search-select-search]");
    const options = container.querySelector("[data-search-select-options]");
    const pills = container.querySelector("[data-search-select-pills]");
    if (!search || !options || !pills) return;

    const name = container.getAttribute("data-name");
    const searchUrl = container.getAttribute("data-search-url");
    const isFilter = container.getAttribute("data-search-select-mode") === "filter";
    const freeText = container.getAttribute("data-search-select-free-text") === "true";
    const multi = container.getAttribute("data-multi") === "true";
    const alwaysVisible = container.getAttribute("data-always-visible") === "true";
    const prefetch = parseInt(container.getAttribute("data-prefetch"), 10) || 0;
    const syncUrl = container.getAttribute("data-sync-url") === "true";

    const noResults = options.querySelector("[data-search-select-no-results]");
    let debounceTimer = null;
    let pendingRequest = null; // in-flight AbortController, so newer queries win
    let hasPrefetched = false;

    const hasVisibleContent = () => {
      const optionRows = options.querySelectorAll("[data-search-select-option]");
      for (let i = 0; i < optionRows.length; i++) {
        if (optionRows[i].style.display !== "none") return true;
      }
      if (noResults && !noResults.classList.contains("hidden")) return true;
      if (options.querySelector("[data-search-select-modifier-option]")) return true;
      return false;
    };

    const showPanel = () => {
      if (alwaysVisible || hasVisibleContent()) {
        options.classList.remove("hidden");
      }
    };
    const hidePanel = () => {
      if (!alwaysVisible) options.classList.add("hidden");
    };

    const setNoResults = (visible) => {
      if (!noResults) return;
      noResults.classList.toggle("hidden", !visible);
      if (visible) showPanel();
    };

    // ── Highlight tracking (filter mode) ──
    let highlightedRow = null;

    const highlightOption = (row) => {
      clearHighlight();
      if (!row) return;
      row.setAttribute("data-search-select-highlighted", "");
      highlightedRow = row;
      row.scrollIntoView({ block: "nearest" });
    };

    const clearHighlight = () => {
      if (highlightedRow) {
        highlightedRow.removeAttribute("data-search-select-highlighted");
        highlightedRow = null;
      }
    };

    const getVisibleOptions = () => {
      const all = options.querySelectorAll("[data-search-select-option]");
      return Array.from(all).filter(row => row.style.display !== "none");
    };

    const autoHighlight = (query) => {
      const visible = getVisibleOptions();
      if (visible.length === 0) {
        clearHighlight();
        return;
      }
      const lower = query.toLowerCase();
      // 1. Starts-with match
      for (let i = 0; i < visible.length; i++) {
        const label = (visible[i].getAttribute("data-label") || "").toLowerCase();
        if (lower && label.startsWith(lower)) {
          highlightOption(visible[i]);
          return;
        }
      }
      // 2. Substring match (fuzzy-lite)
      for (let j = 0; j < visible.length; j++) {
        const subLabel = (visible[j].getAttribute("data-label") || "").toLowerCase();
        if (lower && subLabel.includes(lower)) {
          highlightOption(visible[j]);
          return;
        }
      }
      // 3. Fallback: first visible option
      highlightOption(visible[0]);
    };

    // Get active values in both form and filter modes
    const getSelectedValues = () => {
      const vals = new Set();
      pills.querySelectorAll('input[type="hidden"]').forEach(input => {
        vals.add(input.value);
      });
      pills.querySelectorAll("[data-pill]").forEach(pill => {
        const val = pill.getAttribute("data-value");
        if (val) vals.add(val);
      });
      return vals;
    };

    // ── Render server-fetched rows into the panel ──
    const renderRows = (items) => {
      const selectedVals = getSelectedValues();
      const preservedOptions = [];

      // Extract existing option data for currently selected values before removing
      options.querySelectorAll("[data-search-select-option]").forEach(row => {
        const val = row.getAttribute("data-value");
        if (selectedVals.has(val)) {
          preservedOptions.push(optionFromRow(row));
        }
        row.remove();
      });

      const renderedValues = new Set();

      // Render preserved options first (to keep them at the top)
      preservedOptions.forEach(opt => {
        options.insertBefore(buildRow(opt), noResults || null);
        renderedValues.add(String(opt.value));
      });

      // Render newly fetched items (excluding already rendered preserved ones)
      // Fix DOM-limit vs fetch mismatch: Do not slice the items, render all returned items.
      items.forEach(item => {
        if (!renderedValues.has(String(item.value))) {
          options.insertBefore(buildRow(item), noResults || null);
          renderedValues.add(String(item.value));
        }
      });

      showPanel();
    };

    // ── Clone a server-rendered <template> prototype by name. The server emits
    //    the mode-appropriate prototypes, so the JS never names a class. ──
    const cloneTemplate = (name) => {
      const template = container.querySelector(`template[data-search-select-template="${name}"]`);
      return template
        ? template.content.firstElementChild.cloneNode(true)
        : null;
    };

    const setLabel = (node, label) => {
      const slot = node.querySelector("[data-search-select-label]");
      if (slot) slot.textContent = label;
    };

    const applyData = (node, data = {}) => {
      Object.keys(data).forEach(key => {
        node.setAttribute(`data-${key}`, data[key]);
      });
    };

    // Build an option row by cloning the "row" template (the same prototype the
    // server renders, so fetched and pre-rendered rows are identical).
    const buildRow = (option) => {
      const row = cloneTemplate("row");
      if (!row) return document.createComment("ss-row");
      row.setAttribute("data-value", option.value);
      row.setAttribute("data-label", option.label);
      applyData(row, option.data);
      setLabel(row, option.label);
      row._searchSelectOption = option;
      return row;
    };

    // ── Client-side filter of the currently loaded rows. Returns the number of
    //    visible rows so the caller decides whether to show the no-results node. ──
    const filterRows = (query) => {
      const lower = query.toLowerCase();
      let visibleCount = 0;
      options.querySelectorAll("[data-search-select-option]").forEach(item => {
        const label = (item.getAttribute("data-label") || "").toLowerCase();
        const match = label.includes(lower);
        item.style.display = match ? "" : "none";
        if (match) visibleCount += 1;
      });
      return visibleCount;
    };

    // ── Fetch matching rows from the server. The previous in-flight request is
    //    aborted so a slower earlier response can never overwrite a newer one. ──
    const fetchFromServer = (query) => {
      if (pendingRequest) pendingRequest.abort();
      pendingRequest = new AbortController();
      let url = `${searchUrl}?q=${encodeURIComponent(query)}`;
      if (prefetch && !query) url += `&limit=${prefetch}`;
      fetch(url, { credentials: "same-origin", signal: pendingRequest.signal })
        .then(response => response.json())
        .then(items => {
          pendingRequest = null;
          renderRows(items);
          // Re-apply the live query: the box may hold more text than was sent.
          setNoResults(filterRows(search.value.trim()) === 0);
          autoHighlight(search.value.trim());
        })
        .catch(error => {
          if (error?.name === "AbortError") return; // superseded
          pendingRequest = null;
          setNoResults(true);
        });
    };

    // In free-text mode the typed text is the value itself: there is no
    // backing list, so we rebuild a single ephemeral option row reflecting the
    // current query so the +/− buttons (or Enter) can commit it as a pill.
    const rebuildFreeTextRow = (query) => {
      options.querySelectorAll("[data-search-select-option]").forEach(row => row.remove());
      if (!query) {
        setNoResults(false);
        clearHighlight();
        return;
      }
      const row = buildRow({ value: query, label: query, data: {} });
      options.insertBefore(row, noResults || null);
      setNoResults(false);
      highlightOption(row);
    };

    // Called on every keystroke. With a search_url, filter the loaded window
    // instantly (zero latency) and debounce a server request for the rest;
    // no-results stays hidden until the response decides it, to avoid a flash
    // over an incomplete window. Without a search_url the loaded set is complete,
    // so the client-side filter is authoritative.
    const runSearch = () => {
      const query = search.value.trim();
      if (freeText) {
        rebuildFreeTextRow(query);
        showPanel();
        return;
      }
      if (searchUrl) {
        filterRows(query);
        setNoResults(false);
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          fetchFromServer(query);
        }, DEBOUNCE_MS);
      } else {
        setNoResults(filterRows(query) === 0);
      }
      autoHighlight(query);
      showPanel();
    };

    // ── Single-select combobox: the search box shows the committed label;
    //    focusing clears it to search, blurring restores it (or deselects). ──
    if (!multi) container._searchSelectLabel = search.value;

    search.addEventListener("focus", () => {
      if (!multi) {
        // Hide the committed label so the box becomes a fresh search field.
        search.value = "";
        container._searchSelectDirty = false;
      }
      if (freeText) {
        rebuildFreeTextRow(search.value.trim());
      } else if (searchUrl) {
        if (prefetch && !hasPrefetched) {
          // Seed the window immediately on first open (not debounced).
          hasPrefetched = true;
          fetchFromServer("");
        } else {
          // Show whatever is already loaded; the server decides no-results.
          filterRows(search.value.trim());
          setNoResults(false);
          autoHighlight(search.value.trim());
        }
      } else {
        setNoResults(filterRows(search.value.trim()) === 0);
        autoHighlight(search.value.trim());
      }
      showPanel();
    });

    search.addEventListener("input", () => {
      clearHighlight();
      if (!multi) {
        if (!container._searchSelectDirty) {
          const label = container._searchSelectLabel || "";
          if (search.value.startsWith(label)) {
            search.value = search.value.slice(label.length);
          }
          container._searchSelectDirty = true;
        }
      }
      runSearch();
    });

    if (!multi) {
      search.addEventListener("blur", () => {
        // Defer so an option click (which fires before blur settles) wins.
        setTimeout(() => {
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

    // ── Keyboard navigation (both form and filter modes) ──
    search.addEventListener("keydown", (event) => {
      const { key } = event;

      if (!multi && key === "Backspace" && !container._searchSelectDirty) {
        event.preventDefault();
        search.value = "";
        search.dispatchEvent(new Event("input", { bubbles: true }));
        return;
      }

      if (!["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(key)) return;
      const visible = getVisibleOptions();
      if (visible.length === 0) {
        if (key === "Escape") hidePanel();
        return;
      }

      if (key === "ArrowDown") {
        event.preventDefault();
        showPanel();
        const downIdx = highlightedRow ? visible.indexOf(highlightedRow) : -1;
        highlightOption(visible[(downIdx + 1) % visible.length]);
      } else if (key === "ArrowUp") {
        event.preventDefault();
        showPanel();
        const upIdx = highlightedRow ? visible.indexOf(highlightedRow) : -1;
        highlightOption(visible[(upIdx - 1 + visible.length) % visible.length]);
      } else if (key === "Enter") {
        if (highlightedRow) {
          event.preventDefault();
          const option = optionFromRow(highlightedRow);
          if (isFilter) {
            addFilterPill(option, "include");
            search.value = "";
          } else {
            selectOption(option);
          }
          clearHighlight();
          hidePanel();
        }
      } else if (key === "Escape") {
        clearHighlight();
        hidePanel();
      }
    });

    // Clicking an option must not blur the input before the click selects.
    options.addEventListener("mousedown", (event) => {
      event.preventDefault();
    });

    // ── Option click → select (form mode) or include/exclude (filter mode) ──
    options.addEventListener("click", (event) => {
      if (isFilter) {
        handleFilterOptionClick(event);
        return;
      }
      const row = event.target.closest("[data-search-select-option]");
      if (!row) return;
      selectOption(optionFromRow(row));
    });

    const handleFilterOptionClick = (event) => {
      // Pinned modifier pseudo-option → set the (mutually exclusive) modifier.
      const modifierRow = event.target.closest("[data-search-select-modifier-option]");
      if (modifierRow) {
        setModifier(
          modifierRow.getAttribute("data-search-select-modifier-option"),
          modifierRow.getAttribute("data-label")
        );
        return;
      }
      // Include / exclude button on a value row.
      const button = event.target.closest("[data-search-select-action]");
      if (button) {
        const row = button.closest("[data-search-select-option]");
        if (!row) return;
        addFilterPill(optionFromRow(row), button.getAttribute("data-search-select-action"));
        return;
      }
      // Click on the option row itself → include.
      const optionRow = event.target.closest("[data-search-select-option]");
      if (optionRow) {
        addFilterPill(optionFromRow(optionRow), "include");
      }
    };

    // Add (or re-type) an include/exclude pill for a value. Selecting any value
    // clears a presence modifier — NOT_NULL / IS_NULL are mutually exclusive
    // with value pills.  Non-presence modifiers (INCLUDES_ALL / INCLUDES_ONLY)
    // persist alongside value pills.
    const addFilterPill = (option, kind) => {
      const modPill = pills.querySelector("[data-search-select-modifier]");
      if (modPill) {
        const modVal = modPill.getAttribute("data-search-select-modifier");
        if (PRESENCE_MODIFIERS.includes(modVal)) {
          clearModifier();
        }
      }
      const existing = pills.querySelector(
        `[data-pill][data-value="${cssEscape(option.value)}"]`
      );
      if (existing) existing.remove();
      pills.appendChild(buildFilterValuePill(option, kind));
      search.value = "";
      emitChange(null);
    };

    const buildFilterValuePill = (option, kind) => {
      const pill = cloneTemplate(kind === "include" ? "pill-include" : "pill-exclude");
      pill.setAttribute("data-value", option.value);
      pill.setAttribute("data-label", option.label);
      applyData(pill, option.data);
      setLabel(pill, option.label);
      return pill;
    };

    // Set the modifier pill.  Presence modifiers (NOT_NULL / IS_NULL) clear all
    // value pills — they are mutually exclusive.  Non-presence modifiers
    // (INCLUDES_ALL / INCLUDES_ONLY) are prepended before existing value pills.
    const setModifier = (modifierValue, label) => {
      // Remove any existing modifier pill to avoid duplicates.
      clearModifierPill();
      if (PRESENCE_MODIFIERS.includes(modifierValue)) {
        pills.innerHTML = "";
      }
      const pill = cloneTemplate("pill-modifier");
      pill.setAttribute("data-search-select-modifier", modifierValue);
      setLabel(pill, label);
      pills.insertBefore(pill, pills.firstChild);
      container.setAttribute("data-modifier", modifierValue);
      hidePanel();
      emitChange(null);
    };

    // Remove the modifier pill and its container attribute.  Safe to call when
    // there is no modifier pill (no-op).  Does not touch value pills.
    const clearModifierPill = () => {
      const modifierPill = pills.querySelector("[data-search-select-modifier]");
      if (modifierPill) modifierPill.remove();
      container.removeAttribute("data-modifier");
    };

    const clearModifier = () => {
      clearModifierPill();
    };

    const optionFromRow = (row) => {
      if (row._searchSelectOption) return row._searchSelectOption;
      const data = {};
      Object.keys(row.dataset).forEach(key => {
        if (key !== "value" && key !== "label" && key !== "ssOption") {
          data[key] = row.dataset[key];
        }
      });
      return {
        value: row.getAttribute("data-value"),
        label: row.getAttribute("data-label"),
        data,
      };
    };

    const selectOption = (option) => {
      if (multi) {
        if (!pills.querySelector(`input[value="${cssEscape(option.value)}"]`)) {
          addPill(option);
        }
        search.value = "";
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
    };

    const addPill = (option) => {
      const pill = buildPill(option);
      if (pill) pills.appendChild(pill);
      pills.appendChild(buildHidden(option.value));
    };

    const buildPill = (option) => {
      const pill = cloneTemplate("pill");
      if (!pill) return null;
      pill.setAttribute("data-value", option.value);
      applyData(pill, option.data);
      setLabel(pill, option.label);
      return pill;
    };

    const buildHidden = (value) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      return input;
    };

    // ── Pill × → remove ──
    pills.addEventListener("click", (event) => {
      const removeButton = event.target.closest("[data-pill-remove]");
      if (!removeButton) return;
      const pill = removeButton.closest("[data-pill]");
      if (!pill) return;
      if (isFilter) {
        // Filter pills have no hidden input.
        if (pill.hasAttribute("data-search-select-modifier")) {
          clearModifierPill();
        } else {
          pill.remove();
        }
        emitChange(null);
        return;
      }
      const value = pill.getAttribute("data-value");
      pill.remove();
      const hidden = pills.querySelector(`input[value="${cssEscape(value)}"]`);
      if (hidden) hidden.remove();
      emitChange(null);
    });

    const currentValues = () => {
      return Array.from(pills.querySelectorAll('input[type="hidden"]')).map(input => input.value);
    };

    const emitChange = (last) => {
      const values = currentValues();
      if (syncUrl) syncToUrl(values);
      container.dispatchEvent(
        new CustomEvent("search-select:change", {
          bubbles: true,
          detail: { name, values, last },
        })
      );
    };

    const syncToUrl = (values) => {
      const params = new URLSearchParams(window.location.search);
      params.delete(name);
      values.forEach(v => {
        params.append(name, v);
      });
      const qs = params.toString();
      history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
    };

    // On init, restore from URL params if the server supplied no selected pills.
    if (syncUrl && !pills.querySelector("[data-pill]")) {
      const initial = new URLSearchParams(window.location.search).getAll(name);
      initial.forEach(v => {
        addPill({ value: v, label: v, data: {} });
      });
    }

    // ── Close panel on outside click ──
    document.addEventListener("click", (event) => {
      if (!container.contains(event.target)) hidePanel();
    });
  };

  /** Minimal escape for use inside an attribute-value selector. */
  const cssEscape = (value) => String(value).replace(/["\\]/g, "\\$&");

  // Serialise each widget's current state onto data-* attributes for the caller.
  // Form widgets expose data-values (the submitted hidden-input values); filter
  // widgets expose data-included / data-excluded / data-modifier for the filter
  // bar to read.
  window.readSearchSelect = (form) => {
    form.querySelectorAll("[data-search-select]").forEach(container => {
      const pills = container.querySelector("[data-search-select-pills]");
      if (container.getAttribute("data-search-select-mode") === "filter") {
        const included = [];
        const excluded = [];
        let modifier = "";
        if (pills) {
          pills.querySelectorAll("[data-pill]").forEach(pill => {
            const pillModifier = pill.getAttribute("data-search-select-modifier");
            if (pillModifier) {
              modifier = pillModifier;  // last modifier pill wins
              return;                    // skip value extraction for this pill
            }
            const value = pill.getAttribute("data-value");
            const label = pill.getAttribute("data-label") || "";
            if (pill.getAttribute("data-search-select-type") === "exclude") {
              excluded.push({ id: value, label });
            } else {
              included.push({ id: value, label });
            }
          });
        }
        container.setAttribute("data-included", JSON.stringify(included));
        container.setAttribute("data-excluded", JSON.stringify(excluded));
        if (modifier) container.setAttribute("data-modifier", modifier);
        else container.removeAttribute("data-modifier");
        return;
      }
      const values = pills
        ? Array.from(pills.querySelectorAll('input[type="hidden"]')).map(input => input.value)
        : [];
      container.setAttribute("data-values", JSON.stringify(values));
    });
  };

  onSwap("[data-search-select]", initWidget);
})();
