/**
 * SearchSelect — custom element wrapping the search-select widget.
 *
 * A search box paired with a dropdown of options. Multi-select renders chosen
 * items as removable pills (inline with the search box), each backed by a
 * hidden <input>. Single-select renders no pill: the committed label lives
 * inside the search box (which doubles as a combobox — a value is committed
 * only by an explicit pick, which fills in the option's label; the first edit
 * of a committed field clears its value), with a lone hidden <input> carrying
 * the value. Both keep hidden inputs so Django validation works.
 *
 * Filter mode (filter-mode="true", rendered by FilterSelect): value rows carry
 * +/− buttons that add include (✓) / exclude (✗) pills, plus pinned modifier
 * pseudo-options ((Any)/(None)) that are mutually exclusive with value pills.
 * Filter widgets have no hidden inputs; readSearchSelect serialises their state
 * into data-included / data-excluded / data-modifier for the filter bar.
 *
 * ARIA (issue #154): the server marks the search input role="combobox" and the
 * panel role="listbox" with role="option" rows; this module assigns the unique
 * listbox/option ids, points aria-controls at the panel, keeps aria-expanded in
 * sync with the panel's visibility, and mirrors the keyboard highlight
 * (data-search-select-highlighted) into aria-activedescendant so screen readers
 * announce the active option without moving DOM focus. aria-selected follows the
 * highlight only in single-select (the APG list-autocomplete convention); in
 * multi/filter mode the listbox is aria-multiselectable, so aria-selected
 * conveys membership instead — synced from the pills by syncSelectedStates.
 *
 * Dynamically-added rows and pills are cloned from hidden <template> elements
 * the server renders with the same Python components (Pill / SearchSelect /
 * FilterSelect). The JS only fills in the label slot ([data-search-select-label]),
 * value, and data-* attributes — so all markup and Tailwind class strings live
 * in one place (the Python components), never duplicated here.
 */

import { isPresenceModifier } from "./filter-tokens.js";
import { bindPopupDismiss } from "../utils.js";

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

// The "search-select:action" CustomEvent: a click on a
// [data-search-select-action] button in a form-mode row (the preset delete ×),
// for an external consumer. Filter +/− are the widget's own state, handled
// inline — they don't ride this event.
export interface SearchSelectActionDetail {
  name: string;
  action: string;
  option: SearchSelectOption;
}

// The widget stashes per-instance state directly on its DOM elements.
interface SearchSelectContainer extends HTMLElement {
  _searchSelectLabel?: string;
  _searchSelectDirty?: boolean;
  _searchSelectSetSelected?: (value: string, label?: string) => void;
  _searchSelectRefetch?: () => void;
  _searchSelectClear?: () => void;
  _searchSelectSetOptions?: (options: SearchSelectOption[]) => void;
}

interface OptionRow extends HTMLElement {
  _searchSelectOption?: SearchSelectOption;
}

interface FilterPillEntry {
  id: string;
  label: string;
}

// A filter value pill is exactly one of two kinds, so a non-pill action name
// (e.g. "delete") can never reach the pill builder.
type FilterPillKind = "include" | "exclude";

const DEBOUNCE_MS = 100;

// Monotonic source for per-widget listbox ids (issue #154). The ids backing
// aria-controls / aria-activedescendant are assigned here at init — never
// server-side — because the nested filter builder clones whole <search-select>
// prototypes, and a server-rendered id would be duplicated across clones.
let listboxIdCounter = 0;

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

  // Issue #348: form comboboxes and filter-builder field-layout rows are hosted in
  // <drop-down behavior="inline-combobox">, which owns the panel's open/close/
  // positioning/dismiss through attachMenu. When hosted, this widget delegates
  // showPanel/hidePanel to the host and reads panel visibility from the `hidden`
  // attribute attachMenu toggles (not the `.hidden` class it uses standalone). No
  // host (the bare field picker, bare test mounts) → the widget keeps owning
  // visibility on its own panel via `.hidden`.
  const dropdownHost = container.closest<HTMLElement & { open(): void; close(): void }>(
    "drop-down"
  );
  const delegated = dropdownHost !== null;

  const noResults = options.querySelector<HTMLElement>("[data-search-select-no-results]");
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let pendingRequest: AbortController | null = null; // in-flight, so newer queries win
  let hasPrefetched = false;

  // Untouched committed single-select: box shows the label but the query is
  // empty (show the full list). Once edited (dirty), the box text is the query.
  // Multi-select box is always the query.
  const currentQuery = (): string =>
    !multi && !container._searchSelectDirty ? "" : search.value.trim();

  // ── ARIA combobox wiring (issue #154). Roles/aria-selected come from the
  //    server markup (and template clones inherit them); the id plumbing and
  //    the expanded/activedescendant state live here. ──
  listboxIdCounter += 1;
  const listboxId = `search-select-listbox-${listboxIdCounter}`;
  options.id = listboxId;
  search.setAttribute("aria-controls", listboxId);
  let optionIdCounter = 0;

  // Option rows only need an id once aria-activedescendant points at them, so
  // ids are assigned lazily on first highlight and stay stable for the row's
  // lifetime (fetched replacements are new elements and get fresh ids).
  const ensureOptionId = (row: HTMLElement): string => {
    if (!row.id) {
      optionIdCounter += 1;
      row.id = `${listboxId}-option-${optionIdCounter}`;
    }
    return row.id;
  };

  // Panel-open source of truth: the `hidden` attribute when delegated (attachMenu
  // toggles menu.hidden), the `.hidden` class in the standalone/legacy path.
  const isPanelOpen = () =>
    delegated ? !options.hasAttribute("hidden") : !options.classList.contains("hidden");

  const syncExpanded = () => {
    search.setAttribute("aria-expanded", isPanelOpen() ? "true" : "false");
  };

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
      // The hasVisibleContent gate stays the empty-panel guard: when delegated
      // it decides whether to open the host at all, so an empty panel never opens.
      if (delegated) dropdownHost!.open();
      else options.classList.remove("hidden");
    }
    syncExpanded();
  };
  const hidePanel = () => {
    // Every close/commit path drops the highlight here, so no caller can leave
    // a collapsed listbox with a stale active or highlight-selected row (and
    // always-visible panels, which stay open, still lose their phantom active
    // option after a commit). clearHighlight also removes aria-activedescendant.
    clearHighlight();
    if (!alwaysVisible) {
      if (delegated) dropdownHost!.close();
      else options.classList.add("hidden");
    }
    syncExpanded();
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
    // Screen readers follow the highlight without moving DOM focus:
    // aria-activedescendant names the active option. aria-selected mirrors the
    // highlight only in single-select (the APG list-autocomplete convention) —
    // in multi mode the listbox is aria-multiselectable and aria-selected
    // conveys pill membership (syncSelectedStates), not the highlight.
    if (!multi) row.setAttribute("aria-selected", "true");
    search.setAttribute("aria-activedescendant", ensureOptionId(row));
    highlightedRow = row;
    row.scrollIntoView({ block: "nearest" });
  };

  const clearHighlight = () => {
    if (highlightedRow) {
      highlightedRow.removeAttribute("data-search-select-highlighted");
      if (!multi) highlightedRow.setAttribute("aria-selected", "false");
      highlightedRow = null;
    }
    search.removeAttribute("aria-activedescendant");
  };

  // Keyboard-navigable rows: value rows plus the pinned modifier
  // pseudo-options — every row advertised as role="option" must be reachable
  // by ArrowUp/ArrowDown, and modifier rows sit first in document order.
  const getVisibleOptions = (): HTMLElement[] => {
    const all = options.querySelectorAll<HTMLElement>(
      "[data-search-select-option], [data-search-select-modifier-option]"
    );
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
    // 3. Fallback: the first VALUE row. A modifier row is auto-highlighted
    //    only when the panel has no value rows and no query — never for a
    //    non-matching query, where Enter would silently set a modifier.
    const firstValueRow = visible.find(row =>
      row.hasAttribute("data-search-select-option")
    );
    if (firstValueRow) {
      highlightOption(firstValueRow);
    } else if (!lower) {
      highlightOption(visible[0]);
    } else {
      clearHighlight();
    }
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

  // In multi mode the listbox is aria-multiselectable, so aria-selected conveys
  // membership: true for value rows whose value has a pill (include or exclude)
  // and for the active modifier row. Runs on init, after rows render, and on
  // every change; single-select keeps highlight-driven aria-selected instead.
  const syncSelectedStates = () => {
    if (!multi) return;
    const selectedValues = getSelectedValues();
    options.querySelectorAll<HTMLElement>("[data-search-select-option]").forEach(row => {
      row.setAttribute(
        "aria-selected",
        selectedValues.has(row.getAttribute("data-value") ?? "") ? "true" : "false"
      );
    });
    const activeModifier = container.getAttribute("data-modifier") ?? "";
    options.querySelectorAll<HTMLElement>("[data-search-select-modifier-option]").forEach(row => {
      row.setAttribute(
        "aria-selected",
        row.getAttribute("data-search-select-modifier-option") === activeModifier
          ? "true"
          : "false"
      );
    });
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

    syncSelectedStates();
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
    // Built via URL so a search-url that already carries a query string (e.g.
    // the preset picker's ?mode=games) composes instead of double-`?`ing.
    const url = new URL(searchUrl ?? "", window.location.origin);
    url.searchParams.set("q", query);
    if (prefetch && !query) url.searchParams.set("limit", String(prefetch));
    fetch(url.toString(), { credentials: "same-origin", signal: pendingRequest.signal })
      .then(response => response.json())
      .then((items: SearchSelectOption[]) => {
        pendingRequest = null;
        renderRows(items);
        // Re-apply the live query: the box may hold more text than was sent.
        setNoResults(filterRows(currentQuery()) === 0);
        autoHighlight(currentQuery());
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
    syncSelectedStates();
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

  // ── Single-select combobox: the search box shows the committed label. A
  //    value is committed only by an explicit pick; the first edit of a
  //    committed field clears it. The box text is never rewritten except by a
  //    pick filling in its label — blur touches neither value nor text. ──
  if (!multi) container._searchSelectLabel = search.value;

  const runFocus = () => {
    if (!multi) {
      const committedLabel = container._searchSelectLabel ?? "";
      if (search.value === committedLabel) {
        // Committed label (or both empty): select it so a keystroke replaces it; full list.
        search.select();
        container._searchSelectDirty = false;
      } else {
        // Retained query from an earlier unpicked edit: caret at end, keep filtering by it.
        container._searchSelectDirty = true;
        search.setSelectionRange(search.value.length, search.value.length);
      }
    }
    if (freeText) {
      rebuildFreeTextRow(currentQuery());
    } else if (searchUrl) {
      if (prefetch && !hasPrefetched) {
        // Seed the window immediately on first open (not debounced).
        hasPrefetched = true;
        fetchFromServer("");
      } else {
        // Show whatever is already loaded; the server decides no-results.
        filterRows(currentQuery());
        setNoResults(false);
        autoHighlight(currentQuery());
      }
    } else {
      setNoResults(filterRows(currentQuery()) === 0);
      autoHighlight(currentQuery());
    }
    showPanel();
  };
  search.addEventListener("focus", runFocus);

  // Focus via mouse click: Chromium collapses runFocus's search.select() to a
  // caret on the following mouseup, so click-then-type would append to the label
  // instead of replacing it. preventDefault that one mouseup so the selection
  // survives. Don't prevent mousedown (it delivers focus/caret). Armed only when
  // focus will actually select-all — the box holds the committed label; a click
  // into a retained query places the caret normally.
  let selectLabelOnMouseUp = false;
  search.addEventListener("mousedown", () => {
    if (
      !multi &&
      document.activeElement !== search &&
      search.value === (container._searchSelectLabel ?? "")
    ) {
      selectLabelOnMouseUp = true;
    }
  });
  search.addEventListener("mouseup", (event) => {
    if (selectLabelOnMouseUp) {
      event.preventDefault();
      selectLabelOnMouseUp = false;
    }
  });

  search.addEventListener("input", () => {
    clearHighlight();
    // First edit: the box text becomes the live query. If a pick was committed,
    // editing abandons it — clear the value now, so only an explicit pick can
    // commit one. With nothing committed there is no value to clear and no
    // event fires.
    if (!multi && !container._searchSelectDirty) {
      container._searchSelectDirty = true;
      if (container._searchSelectLabel) {
        pills.innerHTML = "";
        container._searchSelectLabel = "";
        emitChange(null);
      }
    }
    runSearch();
  });

  // ── Keyboard navigation (both form and filter modes) ──
  search.addEventListener("keydown", (event) => {
    const { key } = event;

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
        const modifierValue = highlightedRow.getAttribute(
          "data-search-select-modifier-option"
        );
        if (modifierValue !== null) {
          // A highlighted pinned modifier pseudo-option: commit it exactly
          // like a click on its row would (setModifier hides the panel).
          setModifier(modifierValue, highlightedRow.getAttribute("data-label") ?? "");
          return;
        }
        const option = optionFromRow(highlightedRow);
        if (isFilter) {
          addFilterPill(option, "include");
          search.value = "";
        } else {
          selectOption(option);
        }
        hidePanel(); // also clears the highlight
      }
    } else if (key === "Escape") {
      hidePanel(); // also clears the highlight
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

  // Fire the external row-action seam (form mode only: the preset delete ×).
  const dispatchAction = (action: string, option: SearchSelectOption) => {
    container.dispatchEvent(
      new CustomEvent<SearchSelectActionDetail>("search-select:action", {
        bubbles: true,
        detail: { name, action, option },
      })
    );
  };

  // ── Option click. One action-button lookup: filter +/− add a pill inline; a
  //    form-mode action button goes out on the event seam. ──
  options.addEventListener("click", (event) => {
    const target = event.target as Element;

    // Filter: a pinned modifier pseudo-option sets the (exclusive) modifier.
    if (isFilter) {
      const modifierRow = target.closest<HTMLElement>("[data-search-select-modifier-option]");
      if (modifierRow) {
        setModifier(
          modifierRow.getAttribute("data-search-select-modifier-option") ?? "",
          modifierRow.getAttribute("data-label") ?? ""
        );
        return;
      }
    }

    // A row action button — resolved before the plain-row pick so it never falls through.
    const actionButton = target.closest<HTMLElement>("[data-search-select-action]");
    if (actionButton) {
      const actionRow = actionButton.closest<HTMLElement>("[data-search-select-option]");
      if (!actionRow) return;
      const action = actionButton.getAttribute("data-search-select-action") ?? "";
      if (isFilter) {
        // Only +/− make a pill; any other action is ignored so it can't be miscast as exclude.
        if (action === "include" || action === "exclude") {
          addFilterPill(optionFromRow(actionRow), action);
        }
      } else {
        dispatchAction(action, optionFromRow(actionRow));
      }
      return;
    }

    // A bare row click → include (filter) / select (form).
    const row = target.closest<HTMLElement>("[data-search-select-option]");
    if (!row) return;
    if (isFilter) {
      addFilterPill(optionFromRow(row), "include");
    } else {
      selectOption(optionFromRow(row));
    }
  });

  // Add (or re-type) an include/exclude pill for a value. Selecting any value
  // clears a presence modifier — NOT_NULL / IS_NULL are mutually exclusive
  // with value pills.  Non-presence modifiers (INCLUDES_ALL / INCLUDES_ONLY)
  // persist alongside value pills.
  const addFilterPill = (option: SearchSelectOption, kind: FilterPillKind) => {
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

  const buildFilterValuePill = (option: SearchSelectOption, kind: FilterPillKind): HTMLElement => {
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

  // Public programmatic setter: commit a selection from code without a
  // round-trip through the option list and without firing search-select:change,
  // so a consumer's on-change logic cannot loop (origin: #192; also used by the
  // add-purchase platform auto-fill, #259).
  container._searchSelectSetSelected = (value: string, label?: string) => {
    selectOption({ value, label: label ?? value, data: {} }, false);
  };

  // Public refetch: reset to a blank query and re-request the prefetch window.
  // The query reset matters — a committed single-select pick leaves its label in
  // the search box, and refetching with that as `q` would return only the
  // matching subset and present it as the full list. Marks hasPrefetched so a
  // following focus doesn't double-fetch (the combobox dropdown behavior calls
  // this on dropdown:show, then focuses the input — issues #297/#94).
  container._searchSelectRefetch = () => {
    if (!searchUrl) return;
    hasPrefetched = true;
    search.value = "";
    if (!multi) container._searchSelectDirty = false;
    fetchFromServer("");
  };

  // Public silent clear: drop the committed selection (hidden inputs, label,
  // query text) without firing search-select:change. Consumers whose pick is a
  // command rather than a persistent value (the preset picker) call this right
  // after handling the pick, so no lingering selection can pin a stale row
  // through renderRows' selected-value preservation (issue #297).
  container._searchSelectClear = () => {
    pills.innerHTML = "";
    container._searchSelectLabel = "";
    container._searchSelectDirty = false;
    search.value = "";
    syncSelectedStates();
  };

  // Public option swap: replace the pre-rendered (inline, no search-url) option
  // set without a fetch — the comparison widget re-filters a right-operand list
  // client-side as the left column / operator changes (#282). A committed
  // single-select value that is no longer offered is dropped so it cannot
  // serialize a stale operand; a still-offered value is preserved. Panel
  // visibility is left untouched (no forced open).
  container._searchSelectSetOptions = (items: SearchSelectOption[]) => {
    options
      .querySelectorAll<HTMLElement>(
        "[data-search-select-option], [data-search-select-group-header]"
      )
      .forEach(node => node.remove());
    const before = noResults ?? null;
    items.forEach(item => options.insertBefore(buildRow(item), before));
    const selected = getSelectedValues();
    const stillOffered = items.some(item => selected.has(String(item.value)));
    if (selected.size && !stillOffered) container._searchSelectClear?.();
    filterRows("");
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
    syncSelectedStates();
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

  // Seed the membership aria-selected state from whatever pills exist at init
  // (server-rendered, URL-restored, or writeFilterSelect-hydrated).
  syncSelectedStates();

  // ── Close panel when focus leaves the widget (e.g. Tab away) ──
  // focusout bubbles, so the container catches the input losing focus in every
  // mode. Option mousedown preventDefault keeps the input focused during a
  // click, so this only fires on a genuine exit.
  container.addEventListener("focusout", (event) => {
    if (!container.contains(event.relatedTarget as Node)) {
      hidePanel(); // also clears the highlight
      // Both modes keep their box text across tab-out/refocus: single-select
      // commits only on an explicit pick, so blur touches neither value nor text.
    }
  });

  // ── Dismiss ──
  // When delegated (issue #348), the host <drop-down>'s attachMenu owns dismiss
  // (outside-click + Escape/Tab), so bind nothing here — a second document
  // listener would double-close. Standalone/legacy widgets keep the shared
  // bindPopupDismiss. Deferred + re-callable so a reconnection (the nested filter
  // builder moves rows) re-binds the document listeners without re-running
  // initWidget, whose element-local listeners persist with the moved subtree. An
  // `always-visible` panel reports open permanently — hidePanel only drops its
  // highlight there.
  // Native `autofocus` on the search input fires its focus event during HTML
  // parse — before connectedCallback binds the listener above — so the panel and
  // prefetch never open. Re-run the focus flow once wired so an autofocused
  // combobox seeds and opens on load like a real focus does. rAF lets a delegated
  // <drop-down> host finish upgrading first.
  if (search.hasAttribute("autofocus")) {
    // Only a fresh, empty add form should steal focus and drive the panel open;
    // a pre-committed single-select keeps its label and whatever native focus it
    // got. Snapshot emptiness now — before any focus() runs the flow below.
    const startedEmpty = !search.value;
    requestAnimationFrame(() => {
      if (!search.isConnected || !startedEmpty) return;
      if (document.activeElement === search) {
        // Native autofocus landed but fired before this listener bound: open the
        // panel explicitly. Otherwise focus the field and let the listener open
        // it — either way runFocus runs exactly once.
        runFocus();
      } else {
        search.focus();
      }
    });
  }

  if (delegated) return null;
  return (): (() => void) =>
    bindPopupDismiss({
      host: container,
      isOpen: isPanelOpen,
      close: hidePanel,
    });
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
  private initialized = false;
  private bindDismiss: (() => () => void) | null = null;
  private cleanup: (() => void) | null = null;

  connectedCallback(): void {
    // Idempotent across DOM moves (the nested filter builder reconciles rows by
    // re-appending them, which reconnects this element). The inner element
    // listeners persist with the moved subtree, so re-running initWidget would
    // double-bind them — instead just re-bind the document dismiss listeners
    // that disconnectedCallback removed. initWidget returns a binder (standalone),
    // null (delegated to a <drop-down> host, which owns dismiss — issue #348), or
    // undefined when the inner markup isn't present yet (retry on next connect);
    // only the first two count as initialised.
    if (!this.initialized) {
      const bindDismiss = initWidget(this);
      if (bindDismiss !== undefined) {
        this.bindDismiss = bindDismiss;
        this.initialized = true;
      }
    }
    this.cleanup = this.bindDismiss?.() ?? null;
  }

  /** Programmatically commit a selection without firing a change event.
   *  Intended for single-selects (on a multi-select it appends a pill).
   *  No-op until the widget has initialised. */
  setSelected(value: string, label?: string): void {
    (this as SearchSelectContainer)._searchSelectSetSelected?.(value, label);
  }

  /** Reset to a blank query and re-request the prefetch window from search-url.
   *  No-op without a search-url or until the widget has initialised. */
  refetchOptions(): void {
    (this as SearchSelectContainer)._searchSelectRefetch?.();
  }

  /** Silently drop the committed selection (hidden inputs, label, query text)
   *  without firing a change event. No-op until the widget has initialised. */
  clearSelection(): void {
    (this as SearchSelectContainer)._searchSelectClear?.();
  }

  /** Replace the inline option set client-side (no fetch). A committed value no
   *  longer offered is dropped; a still-offered one is kept. For inline
   *  (no search-url) single-selects whose options are recomputed on the client
   *  — e.g. the field-comparison right operand (#282). No change event fires. */
  setOptions(options: SearchSelectOption[]): void {
    (this as SearchSelectContainer)._searchSelectSetOptions?.(options);
  }

  disconnectedCallback(): void {
    // Drop the document dismiss listeners; the bindDismiss binder is kept so a
    // reconnection can re-attach them (see above).
    this.cleanup?.();
    this.cleanup = null;
  }
}

customElements.define("search-select", SearchSelectElement);
