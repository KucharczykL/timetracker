/**
 * SearchSelect — custom element wrapping the search-select widget.
 *
 * A search box paired with a dropdown of options. Multi-select renders chosen
 * items as removable pills (inline with the search box), each backed by a
 * hidden <input>. Single-select renders no pill: the committed label lives
 * inside the search box (which doubles as a combobox — focus clears it to
 * search, picking an option fills it), with a lone hidden <input> carrying the
 * value. Both keep hidden inputs so Django validation works.
 *
 * Filter mode (filter-mode="true", rendered by FilterSelect): value rows carry
 * +/− buttons that add include (✓) / exclude (✗) pills, plus pinned modifier
 * pseudo-options ((Any)/(None)) that are mutually exclusive with value pills.
 * Filter widgets have no hidden inputs; readSearchSelect serialises their state
 * into data-included / data-excluded / data-modifier for the filter bar.
 *
 * Dynamically-added rows and pills are cloned from hidden <template> elements
 * the server renders with the same Python components (Pill / SearchSelect /
 * FilterSelect). The JS only fills in the label slot ([data-search-select-label]),
 * value, and data-* attributes — so all markup and Tailwind class strings live
 * in one place (the Python components), never duplicated here.
 */

import { isPresenceModifier } from "./filter-tokens.js";

// The contract for the "search-select:change" CustomEvent this widget emits.
// Consumers (e.g. add_purchase.ts) import these types — never redefine them.
export interface SearchSelectOption {
  value: string;
  label: string;
  data: Record<string, string>;
}

export interface SearchSelectChangeDetail {
  name: string;
  values: string[];
  last: SearchSelectOption | null;
}

// The widget stashes per-instance state directly on its DOM elements.
interface SearchSelectContainer extends HTMLElement {
  _searchSelectLabel?: string;
  _searchSelectDirty?: boolean;
  _searchSelectSetSelected?: (value: string, label?: string) => void;
}

interface OptionRow extends HTMLElement {
  _searchSelectOption?: SearchSelectOption;
}

interface FilterPillEntry {
  id: string;
  label: string;
}

const DEBOUNCE_MS = 100;

// Presence modifiers (IS_NULL / NOT_NULL) are mutually exclusive with value
// pills — selecting one clears all value pills. Non-presence modifiers
// (INCLUDES_ALL, INCLUDES_ONLY) coexist with value pills. The token set lives in
// ./filter-tokens (contract-guarded against common.criteria.Modifier, #152).

const initWidget = (containerElement: Element) => {
  const container = containerElement as SearchSelectContainer;
  const search = container.querySelector<HTMLInputElement>("[data-search-select-search]");
  const options = container.querySelector<HTMLElement>("[data-search-select-options]");
  const pills = container.querySelector<HTMLElement>("[data-search-select-pills]");
  if (!search || !options || !pills) return;

  const name = container.getAttribute("name") ?? "";
  const searchUrl = container.getAttribute("search-url");
  const isFilter = container.getAttribute("filter-mode") === "true";
  const freeText = container.getAttribute("free-text") === "true";
  const multi = container.getAttribute("multi") === "true";
  const alwaysVisible = container.getAttribute("always-visible") === "true";
  const prefetch = parseInt(container.getAttribute("prefetch") ?? "", 10) || 0;
  const syncUrl = container.getAttribute("sync-url") === "true";

  const noResults = options.querySelector<HTMLElement>("[data-search-select-no-results]");
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let pendingRequest: AbortController | null = null; // in-flight, so newer queries win
  let hasPrefetched = false;

  const hasVisibleContent = () => {
    const optionRows = options.querySelectorAll<HTMLElement>("[data-search-select-option]");
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

  const setNoResults = (visible: boolean) => {
    if (!noResults) return;
    noResults.classList.toggle("hidden", !visible);
    if (visible) showPanel();
  };

  // ── Highlight tracking (filter mode) ──
  let highlightedRow: HTMLElement | null = null;

  const highlightOption = (row: HTMLElement | null) => {
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

  const getVisibleOptions = (): HTMLElement[] => {
    const all = options.querySelectorAll<HTMLElement>("[data-search-select-option]");
    return Array.from(all).filter(row => row.style.display !== "none");
  };

  const autoHighlight = (query: string) => {
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
  const getSelectedValues = (): Set<string> => {
    const values = new Set<string>();
    pills.querySelectorAll<HTMLInputElement>('input[type="hidden"]').forEach(input => {
      values.add(input.value);
    });
    pills.querySelectorAll<HTMLElement>("[data-pill]").forEach(pill => {
      const value = pill.getAttribute("data-value");
      if (value) values.add(value);
    });
    return values;
  };

  // ── Render server-fetched rows into the panel ──
  const renderRows = (items: SearchSelectOption[]) => {
    const selectedValues = getSelectedValues();
    const preservedOptions: SearchSelectOption[] = [];

    // Extract existing option data for currently selected values before removing
    options.querySelectorAll<HTMLElement>("[data-search-select-option]").forEach(row => {
      const value = row.getAttribute("data-value");
      if (value && selectedValues.has(value)) {
        preservedOptions.push(optionFromRow(row));
      }
      row.remove();
    });

    const renderedValues = new Set<string>();

    // Render preserved options first (to keep them at the top)
    preservedOptions.forEach(option => {
      options.insertBefore(buildRow(option), noResults || null);
      renderedValues.add(String(option.value));
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
  const cloneTemplate = (templateName: string): HTMLElement | null =>
    cloneTemplateFrom(container, templateName);

  const setLabel = setLabelSlot;

  const applyData = (node: Element, data: Record<string, string> = {}) => {
    Object.keys(data).forEach(key => {
      node.setAttribute(`data-${key}`, data[key]);
    });
  };

  // Build an option row by cloning the "row" template (the same prototype the
  // server renders, so fetched and pre-rendered rows are identical).
  const buildRow = (option: SearchSelectOption): HTMLElement | Comment => {
    const row = cloneTemplate("row") as OptionRow | null;
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
  const filterRows = (query: string): number => {
    const lower = query.toLowerCase();
    let visibleCount = 0;
    options.querySelectorAll<HTMLElement>("[data-search-select-option]").forEach(item => {
      const label = (item.getAttribute("data-label") || "").toLowerCase();
      const match = label.includes(lower);
      item.style.display = match ? "" : "none";
      if (match) visibleCount += 1;
    });
    syncGroupHeaders();
    return visibleCount;
  };

  // In a grouped panel, hide each group header whose run of following option rows
  // (up to the next header) has no visible option, so an empty group leaves no
  // dangling label. A no-op when the panel has no headers (the common case).
  const syncGroupHeaders = () => {
    const headers = options.querySelectorAll<HTMLElement>("[data-search-select-group-header]");
    headers.forEach(header => {
      let anyVisible = false;
      let sibling = header.nextElementSibling as HTMLElement | null;
      while (sibling && !sibling.hasAttribute("data-search-select-group-header")) {
        if (sibling.hasAttribute("data-search-select-option") && sibling.style.display !== "none") {
          anyVisible = true;
          break;
        }
        sibling = sibling.nextElementSibling as HTMLElement | null;
      }
      header.style.display = anyVisible ? "" : "none";
    });
  };

  // ── Fetch matching rows from the server. The previous in-flight request is
  //    aborted so a slower earlier response can never overwrite a newer one. ──
  const fetchFromServer = (query: string) => {
    if (pendingRequest) pendingRequest.abort();
    pendingRequest = new AbortController();
    let url = `${searchUrl}?q=${encodeURIComponent(query)}`;
    if (prefetch && !query) url += `&limit=${prefetch}`;
    fetch(url, { credentials: "same-origin", signal: pendingRequest.signal })
      .then(response => response.json())
      .then((items: SearchSelectOption[]) => {
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
  const rebuildFreeTextRow = (query: string) => {
    options.querySelectorAll("[data-search-select-option]").forEach(row => row.remove());
    if (!query) {
      setNoResults(false);
      clearHighlight();
      return;
    }
    const row = buildRow({ value: query, label: query, data: {} });
    options.insertBefore(row, noResults || null);
    setNoResults(false);
    highlightOption(row as HTMLElement);
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
      if (debounceTimer) clearTimeout(debounceTimer);
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
      const downIndex = highlightedRow ? visible.indexOf(highlightedRow) : -1;
      highlightOption(visible[(downIndex + 1) % visible.length]);
    } else if (key === "ArrowUp") {
      event.preventDefault();
      showPanel();
      const upIndex = highlightedRow ? visible.indexOf(highlightedRow) : -1;
      highlightOption(visible[(upIndex - 1 + visible.length) % visible.length]);
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

  // Same guard for the pills region: clicking a pill's remove (×) button must
  // not move focus out of the widget. Without this, browsers that don't focus a
  // <button> on click (Firefox, Safari) fire focusout with relatedTarget=null,
  // which would close the panel even though focus stayed in the widget.
  pills.addEventListener("mousedown", (event) => {
    event.preventDefault();
  });

  // ── Option click → select (form mode) or include/exclude (filter mode) ──
  options.addEventListener("click", (event) => {
    if (isFilter) {
      handleFilterOptionClick(event);
      return;
    }
    const row = (event.target as Element).closest<HTMLElement>("[data-search-select-option]");
    if (!row) return;
    selectOption(optionFromRow(row));
  });

  const handleFilterOptionClick = (event: MouseEvent) => {
    const target = event.target as Element;
    // Pinned modifier pseudo-option → set the (mutually exclusive) modifier.
    const modifierRow = target.closest<HTMLElement>("[data-search-select-modifier-option]");
    if (modifierRow) {
      setModifier(
        modifierRow.getAttribute("data-search-select-modifier-option") ?? "",
        modifierRow.getAttribute("data-label") ?? ""
      );
      return;
    }
    // Include / exclude button on a value row.
    const button = target.closest<HTMLElement>("[data-search-select-action]");
    if (button) {
      const row = button.closest<HTMLElement>("[data-search-select-option]");
      if (!row) return;
      addFilterPill(optionFromRow(row), button.getAttribute("data-search-select-action") ?? "include");
      return;
    }
    // Click on the option row itself → include.
    const optionRow = target.closest<HTMLElement>("[data-search-select-option]");
    if (optionRow) {
      addFilterPill(optionFromRow(optionRow), "include");
    }
  };

  // Add (or re-type) an include/exclude pill for a value. Selecting any value
  // clears a presence modifier — NOT_NULL / IS_NULL are mutually exclusive
  // with value pills.  Non-presence modifiers (INCLUDES_ALL / INCLUDES_ONLY)
  // persist alongside value pills.
  const addFilterPill = (option: SearchSelectOption, kind: string) => {
    const modifierPill = pills.querySelector("[data-search-select-modifier]");
    if (modifierPill) {
      const modifierValue = modifierPill.getAttribute("data-search-select-modifier") ?? "";
      if (isPresenceModifier(modifierValue)) {
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

  const buildFilterValuePill = (option: SearchSelectOption, kind: string): HTMLElement => {
    const pill = cloneTemplate(kind === "include" ? "pill-include" : "pill-exclude")!;
    pill.setAttribute("data-value", option.value);
    pill.setAttribute("data-label", option.label);
    applyData(pill, option.data);
    setLabel(pill, option.label);
    return pill;
  };

  // Set the modifier pill.  Presence modifiers (NOT_NULL / IS_NULL) clear all
  // value pills — they are mutually exclusive.  Non-presence modifiers
  // (INCLUDES_ALL / INCLUDES_ONLY) are prepended before existing value pills.
  const setModifier = (modifierValue: string, label: string) => {
    // Remove any existing modifier pill to avoid duplicates.
    clearModifierPill();
    if (isPresenceModifier(modifierValue)) {
      pills.innerHTML = "";
    }
    const pill = cloneTemplate("pill-modifier")!;
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

  const optionFromRow = (row: HTMLElement): SearchSelectOption => {
    const optionRow = row as OptionRow;
    if (optionRow._searchSelectOption) return optionRow._searchSelectOption;
    const data: Record<string, string> = {};
    Object.keys(row.dataset).forEach(key => {
      if (key !== "value" && key !== "label" && key !== "ssOption") {
        data[key] = row.dataset[key] ?? "";
      }
    });
    return {
      value: row.getAttribute("data-value") ?? "",
      label: row.getAttribute("data-label") ?? "",
      data,
    };
  };

  // `emit` lets a programmatic restore (setSelected) seed the selection WITHOUT
  // firing search-select:change — otherwise restoring a value after a re-render
  // would re-trigger the consumer's on-change logic (e.g. the leaf row's field
  // reset), looping. User-driven picks pass emit=true (the default).
  const selectOption = (option: SearchSelectOption, emit = true) => {
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
    if (emit) emitChange(option);
  };

  // Public programmatic setter (issue #192): restore/seed a selection from code
  // without a round-trip through the option list or a change event. Used by the
  // nested filter builder to show a leaf's already-chosen field after a re-render.
  container._searchSelectSetSelected = (value: string, label?: string) => {
    selectOption({ value, label: label ?? value, data: {} }, false);
  };

  const addPill = (option: SearchSelectOption) => {
    const pill = buildPill(option);
    if (pill) pills.appendChild(pill);
    pills.appendChild(buildHidden(option.value));
  };

  const buildPill = (option: SearchSelectOption): HTMLElement | null => {
    const pill = cloneTemplate("pill");
    if (!pill) return null;
    pill.setAttribute("data-value", option.value);
    applyData(pill, option.data);
    setLabel(pill, option.label);
    return pill;
  };

  const buildHidden = (value: string): HTMLInputElement => {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    return input;
  };

  // ── Pill × → remove ──
  pills.addEventListener("click", (event) => {
    const removeButton = (event.target as Element).closest("[data-pill-remove]");
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

  const currentValues = (): string[] => {
    return Array.from(
      pills.querySelectorAll<HTMLInputElement>('input[type="hidden"]')
    ).map(input => input.value);
  };

  const emitChange = (last: SearchSelectOption | null) => {
    const values = currentValues();
    if (syncUrl) syncToUrl(values);
    container.dispatchEvent(
      new CustomEvent<SearchSelectChangeDetail>("search-select:change", {
        bubbles: true,
        detail: { name, values, last },
      })
    );
  };

  const syncToUrl = (values: string[]) => {
    const params = new URLSearchParams(window.location.search);
    params.delete(name);
    values.forEach(value => {
      params.append(name, value);
    });
    const queryString = params.toString();
    history.replaceState(null, "", queryString ? `?${queryString}` : window.location.pathname);
  };

  // On init, restore from URL params if the server supplied no selected pills.
  if (syncUrl && !pills.querySelector("[data-pill]")) {
    const initial = new URLSearchParams(window.location.search).getAll(name);
    initial.forEach(value => {
      addPill({ value, label: value, data: {} });
    });
  }

  // ── Close panel when focus leaves the widget (e.g. Tab away) ──
  // focusout bubbles, so the container catches the input losing focus in every
  // mode. Option mousedown preventDefault keeps the input focused during a
  // click, so this only fires on a genuine exit.
  container.addEventListener("focusout", (event) => {
    if (!container.contains(event.relatedTarget as Node)) {
      hidePanel();
      clearHighlight();
      // The search box is a transient query buffer; pills hold the committed
      // values. Drop any uncommitted query on exit so it matches single-select
      // (whose blur handler already clears/restores the box). Reset row
      // visibility without reopening the panel — never call runSearch() here.
      if (multi && search.value !== "") {
        search.value = "";
        if (freeText) {
          rebuildFreeTextRow("");
        } else {
          filterRows("");
          setNoResults(false);
        }
      }
    }
  });

  // ── Close panel on outside click ──
  const onDocumentClick = (event: MouseEvent) => {
    if (!container.contains(event.target as Node)) hidePanel();
  };
  document.addEventListener("click", onDocumentClick);
  return onDocumentClick;
};

/** Minimal escape for use inside an attribute-value selector. */
const cssEscape = (value: string | null): string => String(value).replace(/["\\]/g, "\\$&");

// ── Detached-safe pill construction (shared by the click handlers above and the
//    silent writer below). Parametrized on the container so they work on a
//    template clone that is not yet connected/upgraded. ──

function cloneTemplateFrom(container: HTMLElement, templateName: string): HTMLElement | null {
  const template = container.querySelector<HTMLTemplateElement>(
    `template[data-search-select-template="${templateName}"]`
  );
  const clone = template?.content.firstElementChild?.cloneNode(true);
  return (clone as HTMLElement) ?? null;
}

function setLabelSlot(node: Element, label: string): void {
  const slot = node.querySelector("[data-search-select-label]");
  if (slot) slot.textContent = label;
}

// The current include/exclude/modifier state of one filter-mode <search-select>,
// read straight from its pills. Self-contained per element (no flat form) so the
// nested filter builder's leaf row can serialize a single widget on its
// search-select:change — issue #192. `modifier` is "" when no modifier pill is set.
export interface FilterSelectValue {
  included: FilterPillEntry[];
  excluded: FilterPillEntry[];
  modifier: string;
}

export function readFilterSelect(container: HTMLElement): FilterSelectValue {
  const pills = container.querySelector<HTMLElement>("[data-search-select-pills]");
  const included: FilterPillEntry[] = [];
  const excluded: FilterPillEntry[] = [];
  let modifier = "";
  if (pills) {
    pills.querySelectorAll<HTMLElement>("[data-pill]").forEach(pill => {
      const pillModifier = pill.getAttribute("data-search-select-modifier");
      if (pillModifier) {
        modifier = pillModifier;  // last modifier pill wins
        return;                    // skip value extraction for this pill
      }
      const value = pill.getAttribute("data-value") ?? "";
      const label = pill.getAttribute("data-label") || "";
      if (pill.getAttribute("data-search-select-type") === "exclude") {
        excluded.push({ id: value, label });
      } else {
        included.push({ id: value, label });
      }
    });
  }
  return { included, excluded, modifier };
}

/** Silent write mirror of readFilterSelect (#263 prefill hydration): render an
 * include/exclude/modifier state into a filter-mode widget's pills by cloning
 * the widget's own pill templates, so hydrated pills are identical to
 * click-added ones (readFilterSelect and the delegated ×-remove treat them the
 * same). Works on a detached, not-yet-upgraded clone and dispatches no events.
 * `modifierLabel` is the pinned modifier row's display label; the modifier pill
 * is only rendered when it is non-empty (INCLUDES/EXCLUDES have no pill).
 * Presence modifiers are mutually exclusive with value pills, mirroring
 * setModifier/addFilterPill above. */
export function writeFilterSelect(
  container: HTMLElement,
  value: FilterSelectValue,
  modifierLabel = "",
): void {
  const pills = container.querySelector<HTMLElement>("[data-search-select-pills]");
  if (!pills) return;
  const { included, excluded, modifier } = value;
  if (modifier && modifierLabel) {
    const pill = cloneTemplateFrom(container, "pill-modifier");
    if (pill) {
      pill.setAttribute("data-search-select-modifier", modifier);
      setLabelSlot(pill, modifierLabel);
      pills.insertBefore(pill, pills.firstChild);
      container.setAttribute("data-modifier", modifier);
    }
  }
  if (modifier && isPresenceModifier(modifier)) return;
  const appendValuePill = (entry: FilterPillEntry, templateName: string): void => {
    const pill = cloneTemplateFrom(container, templateName);
    if (!pill) return;
    pill.setAttribute("data-value", entry.id);
    pill.setAttribute("data-label", entry.label);
    setLabelSlot(pill, entry.label);
    pills.appendChild(pill);
  };
  for (const entry of included) appendValuePill(entry, "pill-include");
  for (const entry of excluded) appendValuePill(entry, "pill-exclude");
}

// Serialise each widget's current state onto data-* attributes for the caller.
// Form widgets expose data-values (the submitted hidden-input values); filter
// widgets expose data-included / data-excluded / data-modifier for the filter
// bar to read. (The legacy flat filter bar's whole-form pass; the nested builder
// uses readFilterSelect per widget instead.)
export function readSearchSelect(form: HTMLElement): void {
  form.querySelectorAll<HTMLElement>("search-select").forEach(container => {
    if (container.getAttribute("filter-mode") === "true") {
      const { included, excluded, modifier } = readFilterSelect(container);
      container.setAttribute("data-included", JSON.stringify(included));
      container.setAttribute("data-excluded", JSON.stringify(excluded));
      if (modifier) container.setAttribute("data-modifier", modifier);
      else container.removeAttribute("data-modifier");
      return;
    }
    const pills = container.querySelector<HTMLElement>("[data-search-select-pills]");
    const values = pills
      ? Array.from(pills.querySelectorAll<HTMLInputElement>('input[type="hidden"]')).map(input => input.value)
      : [];
    container.setAttribute("data-values", JSON.stringify(values));
  });
}

export class SearchSelectElement extends HTMLElement {
  private onDocumentClick: ((event: MouseEvent) => void) | null = null;
  private initialized = false;

  connectedCallback(): void {
    // Idempotent across DOM moves (the nested filter builder reconciles rows by
    // re-appending them, which reconnects this element). The inner element
    // listeners persist with the moved subtree, so re-running initWidget would
    // double-bind them — instead just re-attach the outside-click listener that
    // disconnectedCallback removed.
    if (this.initialized) {
      if (this.onDocumentClick) document.addEventListener("click", this.onDocumentClick);
      return;
    }
    this.initialized = true;
    this.onDocumentClick = initWidget(this) as ((event: MouseEvent) => void) | null;
  }

  /** Programmatically set a single-select value without firing a change event
   *  (issue #192). No-op until the widget has initialised. */
  setSelected(value: string, label?: string): void {
    (this as SearchSelectContainer)._searchSelectSetSelected?.(value, label);
  }

  disconnectedCallback(): void {
    // Keep the handler reference so a reconnection can re-attach it (see above).
    if (this.onDocumentClick) document.removeEventListener("click", this.onDocumentClick);
  }
}

customElements.define("search-select", SearchSelectElement);
