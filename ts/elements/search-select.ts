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
import { reportClientError } from "../client-errors.js";
import { readSearchSelectProps } from "../generated/props.js";
import { SHEET_ATTRIBUTES, SHEET_HOST_VALUE } from "../generated/sheet-attributes.js";
import { followPointer } from "../pointer-follow.js";
import { ownChild } from "./own-child.js";
// Defines the host a delegated widget opens.
import "./drop-down.js";
import { FORM_DIALOG_CREATED, type FormDialogCreatedDetail } from "./form-dialog/events.js";

//: Every row a person can highlight and pick.
const NAVIGABLE_ROWS =
  "[data-search-select-none-option], [data-search-select-option], " +
  "[data-search-select-modifier-option], [data-search-select-create]";

//: Hidden inputs that carry a value.
const HELD_VALUE_INPUTS = 'input[type="hidden"]:not([data-search-select-none])';

//: As the face renders them server-side.
const FACE_EXCLUDED_PREFIX = "not ";
const FACE_SEPARATOR = ", ";

// The contract for the "search-select:change" CustomEvent this widget emits.
// Consumers import these types — never redefine them.
export interface SearchSelectOption {
  value: string;
  label: string;
  data: Record<string, string>;
  //: Muted after the label; never searched.
  hint?: string;
}

//: Rows under one header; blank heads none.
export interface SearchSelectOptionGroup {
  label: string;
  options: SearchSelectOption[];
}

//: `none: true` is a committed none, never a mid-edit drop.
export type SearchSelectChangeDetail =
  | { name: string; values: string[]; last: SearchSelectOption | null; none: false }
  | { name: string; values: []; last: null; none: true };

declare global {
  interface HTMLElementEventMap {
    "search-select:change": CustomEvent<SearchSelectChangeDetail>;
  }
}

/** The value a picker posts; "" for none. */
export function heldValue(picker: Element): string | null {
  return (
    picker.querySelector<HTMLInputElement>(
      '[data-search-select-pills] input[type="hidden"]'
    )?.value ?? null
  );
}

// Every × press; follows any change event.
export interface SearchSelectClearDetail {
  name: string;
}

// The "search-select:create" CustomEvent of a row its consumer commits.
export interface SearchSelectCreateDetail {
  name: string;
  //: A row holds this name exactly; the row read the replace verb.
  replaces: boolean;
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
  _searchSelectHoldValue?: (value: string) => boolean;
  _searchSelectHoldNone?: () => void;
  _searchSelectOffers?: (value: string) => boolean;
  _searchSelectHeldLabel?: () => string | null;
  _searchSelectSetOptionGroups?: (groups: SearchSelectOptionGroup[]) => void;
  _searchSelectRewriteDialogCreate?: () => void;
}

//: Held values and none.
interface HeldState {
  values: string[];
  none: boolean;
}

//: A single-select's held value, or none.
type DroppedHeld = { none: true } | { none: false; value: string; label: string };

//: Container parts the public hold methods call.
type HeldPart =
  | "_searchSelectHoldValue"
  | "_searchSelectHoldNone"
  | "_searchSelectOffers"
  | "_searchSelectHeldLabel";

//: A label change alone is no change.
const sameHeld = (left: HeldState, right: HeldState): boolean =>
  left.none === right.none &&
  left.values.length === right.values.length &&
  left.values.every((value, index) => value === right.values[index]);

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

//: The panel's sentence when a search fails.
const LOAD_FAILED = "Could not load results";

//: A search's request and its query.
interface PendingSearch {
  controller: AbortController;
  query: string;
}

// Monotonic source for per-widget listbox ids (issue #154). The ids backing
// aria-controls / aria-activedescendant are assigned here at init — never
// server-side — because the nested filter builder clones whole <search-select>
// prototypes, and a server-rendered id would be duplicated across clones.
let listboxIdCounter = 0;

// Presence modifiers (IS_NULL / NOT_NULL) are mutually exclusive with value
// pills — selecting one clears all value pills. Non-presence modifiers
// (INCLUDES_ALL, INCLUDES_ONLY) coexist with value pills. The token set lives in
// ./filter-tokens (contract-guarded against common.criteria.Modifier, #152).


/** A request parameter's source: a value the server stated, or a form field. */
interface LiteralParam {
  value: string;
}

export interface FieldParam {
  field: string;
}

type ParamSource = LiteralParam | FieldParam;
type ParamSources = Record<string, ParamSource>;

/** The params attribute, which is JSON text: props are attributes. */
const parseParams = (raw: string | null, context = "search-select[params]"): ParamSources => {
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      reportClientError(context, `not an object: ${raw}`, {
        toast: false,
      });
      return {};
    }
    //: One source each, checked rather than cast: the Python side
    //: spells these keys, and a rename there is silent here — the
    //: request would go out without the key the route requires.
    const sources: ParamSources = {};
    Object.entries(parsed as Record<string, unknown>).forEach(([key, source]) => {
      const states = (name: string): boolean =>
        typeof source === "object" &&
        source !== null &&
        typeof (source as Record<string, unknown>)[name] === "string";
      if (states("field") !== states("value")) {
        sources[key] = source as ParamSource;
        return;
      }
      reportClientError(
        context,
        `${key} states no one source: ${JSON.stringify(source)}`,
        { toast: false }
      );
    });
    return sources;
  } catch (error) {
    // The widget searches without them rather than not at all.
    reportClientError(
      context,
      String((error as Error)?.message ?? error),
      { toast: false }
    );
    return {};
  }
};

/** One form field's current value, read at the moment it is used. */
const fieldValue = (container: Element, field: string): string => {
  const form = container.closest("form");
  if (!form) return "";
  const value = new FormData(form).get(field);
  return typeof value === "string" ? value : "";
};

/** Every param, resolved now. A blank field value states no parameter. */
const resolveParams = (container: Element, params: ParamSources): Record<string, string> => {
  const resolved: Record<string, string> = {};
  Object.entries(params).forEach(([key, source]) => {
    const value = "field" in source ? fieldValue(container, source.field) : source.value;
    if (value) resolved[key] = value;
  });
  return resolved;
};

/** A field a param names and the form does not hold a value for. */
const unfilledFields = (container: Element, params: ParamSources): string[] =>
  Object.values(params)
    .filter((source): source is FieldParam => "field" in source)
    .map(source => source.field)
    .filter(field => !fieldValue(container, field));

/** What a person calls that field: its own label, or its name. */
const fieldLabel = (container: Element, field: string): string => {
  const form = container.closest("form");
  const control = form?.elements.namedItem(field);
  const id = control instanceof HTMLElement ? control.id : "";
  const label = id ? form?.querySelector(`label[for="${cssEscape(id)}"]`) : null;
  return (label?.textContent ?? "").trim().toLowerCase() || field;
};

/** The fields a set of sources names. */
const sourceFields = (params: ParamSources): string[] =>
  Object.values(params)
    .filter((source): source is FieldParam => "field" in source)
    .map(source => source.field);

const DIALOG_CREATE_CONTEXT = "search-select[dialog-create-params]";

/** Set the + link's query from sources. */
const rewriteDialogCreate = (container: Element, params: ParamSources): void => {
  if (!container.isConnected) return;
  //: The face's + sits beside it.
  const scope = container.hasAttribute("data-toggle")
    ? (container.closest("drop-down") ?? container)
    : container;
  const links = Array.from(scope.querySelectorAll("a[data-search-select-dialog-create]"));
  if (!links.length) {
    reportClientError(DIALOG_CREATE_CONTEXT, "params set, no + link", { toast: false });
    return;
  }
  links.forEach(link => rewriteDialogCreateLink(container, link, params));
};

const rewriteDialogCreateLink = (container: Element, link: Element, params: ParamSources): void => {
  const href = link.getAttribute("href");
  if (!href) {
    reportClientError(DIALOG_CREATE_CONTEXT, "a + link has no href", { toast: false });
    return;
  }
  let url: URL;
  try {
    url = new URL(href, location.href);
  } catch (error) {
    //: A bad href leaves the picker working.
    reportClientError(DIALOG_CREATE_CONTEXT, String(error), { toast: false });
    return;
  }
  Object.keys(params).forEach(key => url.searchParams.delete(key));
  Object.entries(resolveParams(container, params)).forEach(([key, value]) =>
    url.searchParams.set(key, value),
  );
  //: A dialog's content holds absolute URLs.
  const relative = href.startsWith("/");
  link.setAttribute("href", relative ? `${url.pathname}${url.search}${url.hash}` : url.href);
};

/** What the dependencies hold, as one comparable string. */
const dependencySignature = (container: Element, fields: string[]): string =>
  fields.map(field => `${field}=${fieldValue(container, field)}`).join("&");

/** False until the inner markup is present. */
const initWidget = (containerElement: Element): boolean => {
  const container = containerElement as SearchSelectContainer;
  const search = container.querySelector<HTMLInputElement>("[data-search-select-search]");
  const options = container.querySelector<HTMLElement>("[data-search-select-options]");
  const pills = container.querySelector<HTMLElement>("[data-search-select-pills]");
  if (!search || !options || !pills) {
    console.error("<search-select> lacks its parts; left unwired", containerElement);
    return false;
  }

  const name = container.getAttribute("name") ?? "";
  const searchUrl = container.getAttribute("search-url");
  const isFilter = container.getAttribute("filter-mode") === "true";
  const freeText = container.getAttribute("free-text") === "true";
  const multi = container.getAttribute("multi") === "true";
  const alwaysVisible = container.getAttribute("always-visible") === "true";
  const prefetch = parseInt(container.getAttribute("prefetch") ?? "", 10) || 0;
  const syncUrl = container.getAttribute("sync-url") === "true";
  //: Through the codegen's reader, so renaming one of these props in
  //: `SearchSelectProps` fails `tsc` rather than the create row.
  const props = readSearchSelectProps(container);
  const params = parseParams(props.params || null);
  //: A filter panel states a criterion and a free-text panel is the
  //: typed text itself; neither holds a row to create.
  const createUrl = props.createUrl;
  const create = isFilter || freeText ? "" : props.create;
  if (create === "post" && !createUrl) {
    //: A post with no endpoint would post to this page.
    throw new Error(`search-select[${props.name}]: create="post" names no create-url`);
  }
  const createVerb = props.createVerb || "Create";
  const replaceVerb = props.replaceVerb;
  //: A required field whose list usually holds one row commits it, so
  //: a submit with no pick still posts one.
  const commitSoleOption = props.commitSoleOption;
  //: Blank, or multi-select, offers no none.
  const noneLabel = multi ? "" : props.noneLabel;
  //: The hosting form renders a token, so a consumer states no prop.
  //: The prop is for a create row that stands outside a form.
  const csrfToken = (): string =>
    props.csrf ||
    container
      .closest("form")
      ?.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')?.value ||
    "";
  //: Every field a param names: a change to one searches again.
  const dependencyFields = sourceFields(params);
  //: What each dependency held when the loaded window was fetched.
  let dependencyValues = "";

  // Hosted only as the host's own toggle.
  const dropdownHost = container.hasAttribute("data-toggle")
    ? container.closest("drop-down")
    : null;
  const delegated = dropdownHost !== null;
  //: Below sm it stands in for the box.
  const face = dropdownHost ? ownChild(dropdownHost, "[data-search-select-face]") : null;
  const facePart = <Part extends HTMLElement>(hook: string): Part | null =>
    face?.querySelector<Part>(`[data-search-select-face-${hook}]`) ?? null;
  const faceOpen = facePart<HTMLButtonElement>("open");
  const faceName = facePart<HTMLElement>("name");
  const faceValue = facePart<HTMLElement>("value");
  const faceClear = facePart<HTMLButtonElement>("clear");
  //: In the sheet, the sheet owns leaving.
  const lent = (): boolean => container.getAttribute(SHEET_ATTRIBUTES.host) === SHEET_HOST_VALUE;
  if (!delegated && !alwaysVisible) {
    reportClientError("search-select", `${name}: no <drop-down> host; the list never opens`, {
      toast: false,
    });
  }

  const noResults = options.querySelector<HTMLElement>("[data-search-select-no-results]");
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  //: In flight; a newer query aborts it.
  let pendingRequest: PendingSearch | null = null;
  //: Query the shown rows answer; null: none.
  let loadedQuery: string | null = null;

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

  // ── Uncommitted-value cue (issue #450, committed_marker widgets only). ──
  // The server renders the sr-only role="status" span solely when the Python
  // component gets committed_marker=True — its presence is the opt-in signal.
  // That guard is load-bearing: the filter builder's field picker, the
  // comparison operands, and the preset picker are all multi="false"
  // filter-mode="false", so a mode check alone would light them up too.
  // Like the listbox id, the describedby id is assigned here, never
  // server-side (the filter builder clones whole <search-select> prototypes).
  const statusEl = container.querySelector<HTMLElement>("[data-search-select-status]");
  //: Present only on clearable widgets.
  const clearButton = container.querySelector<HTMLButtonElement>(
    "[data-search-select-clear]"
  );
  //: No sole commit until pick or dependency.
  //: Not _searchSelectDirty: runFocus resets that on an empty box.
  let soleDeclined = false;
  //: Counts × presses; a create outlived by one selects nothing.
  let clears = 0;

  //: What a first keystroke dropped.
  let heldBeforeDrop: DroppedHeld | null = null;
  const heldNow = (): HeldState => ({
    values: Array.from(pills.querySelectorAll<HTMLInputElement>(HELD_VALUE_INPUTS)).map(
      input => input.value
    ),
    none: pills.querySelector("input[data-search-select-none]") !== null,
  });
  const droppable = (): DroppedHeld | null => {
    const { values, none } = heldNow();
    if (none) return { none: true };
    if (values.length !== 1) return null;
    return { none: false, value: values[0], label: container._searchSelectLabel ?? "" };
  };

  //: None held, and not yet edited.
  const holdsNone = (): boolean =>
    pills.querySelector("input[data-search-select-none]") !== null &&
    !container._searchSelectDirty;

  const pillLabel = (pill: Element): string => {
    const label =
      pill.querySelector("[data-search-select-label]")?.textContent ??
      pill.getAttribute("data-label") ??
      "";
    return pill.getAttribute("data-search-select-type") === "exclude"
      ? `${FACE_EXCLUDED_PREFIX}${label}`
      : label;
  };
  const faceText = (): string => {
    if (multi || isFilter) {
      return Array.from(pills.querySelectorAll("[data-pill]"), pillLabel)
        .filter(Boolean)
        .join(FACE_SEPARATOR);
    }
    if (pills.querySelector("input[data-search-select-none]")) return noneLabel;
    return pills.querySelector(HELD_VALUE_INPUTS) ? (container._searchSelectLabel ?? "") : "";
  };
  const syncFace = () => {
    if (faceValue) {
      const text = faceText();
      faceValue.textContent = text || search.placeholder;
      faceValue.toggleAttribute("data-placeholder", !text);
    }
    if (faceClear && clearButton) faceClear.hidden = clearButton.hidden;
  };

  //: Also syncs the face.
  const syncClearButton = () => {
    if (clearButton) {
      clearButton.hidden =
        holdsNone() ||
        !(pills.querySelector(HELD_VALUE_INPUTS + ", [data-pill]") || search.value.trim());
    }
    syncFace();
  };
  if (statusEl) {
    statusEl.id = `${listboxId}-status`;
    const described = (search.getAttribute("aria-describedby") ?? "").split(/\s+/);
    const ids = described.filter(id => id && id !== statusEl.id);
    search.setAttribute("aria-describedby", [...ids, statusEl.id].join(" "));
  }

  // Box text present with no committed hidden input = uncommitted: toggle the
  // container attribute (the CSS draft cue) and fill the status span so the
  // drop is announced as it happens. Idempotent — the status text is written
  // exactly once per transition; rewriting it on every keystroke would re-fire
  // the live region each time. Browser form-state restore (session restore /
  // back-navigation autofill) can repopulate the box without an input event —
  // that pre-existing hazard is not covered here.
  //: Also syncs the ×, every mode.
  const syncUncommitted = () => {
    syncClearButton();
    if (!statusEl || multi || isFilter) return;
    const uncommitted =
      search.value.trim() !== "" && !pills.querySelector('input[type="hidden"]');
    if (uncommitted === container.hasAttribute("data-uncommitted")) return;
    container.toggleAttribute("data-uncommitted", uncommitted);
    statusEl.textContent = uncommitted ? "No option selected" : "";
  };

  // Visibility is the panel's `hidden` attribute.
  const panel = options.closest<HTMLElement>("[data-search-select-panel]") ?? options;
  const isPanelOpen = () => !panel.hidden;

  const syncExpanded = () => {
    search.setAttribute("aria-expanded", isPanelOpen() ? "true" : "false");
    faceOpen?.setAttribute("aria-expanded", String(lent() && isPanelOpen()));
  };

  const hasVisibleContent = () => {
    const optionRows = options.querySelectorAll<HTMLElement>("[data-search-select-option]");
    for (let i = 0; i < optionRows.length; i++) {
      if (optionRows[i].style.display !== "none") return true;
    }
    if (noResults && !noResults.classList.contains("hidden")) return true;
    if (
      options.querySelector(
        "[data-search-select-modifier-option], [data-search-select-none-option]"
      )
    ) {
      return true;
    }
    const createRowNode = options.querySelector<HTMLElement>(
      "[data-search-select-create]"
    );
    if (createRowNode && !createRowNode.hidden) return true;
    return false;
  };

  //: An answer nobody awaits renders without opening.
  let unprompted = false;
  const answering = (render: () => void) => {
    unprompted = !container.contains(document.activeElement);
    try {
      render();
    } finally {
      unprompted = false;
    }
  };

  const showPanel = () => {
    // An empty panel never opens its host.
    if (!unprompted && (alwaysVisible || hasVisibleContent())) dropdownHost?.open();
    syncExpanded();
  };
  const hidePanel = () => {
    // Every close/commit path drops the highlight here, so no caller can leave
    // a collapsed listbox with a stale active or highlight-selected row (and
    // always-visible panels, which stay open, still lose their phantom active
    // option after a commit). clearHighlight also removes aria-activedescendant.
    clearHighlight();
    //: A lent widget closes on a person's pick.
    if (!alwaysVisible && !lent()) dropdownHost?.close();
    syncExpanded();
  };

  //: A person's pick ends a single-select sheet.
  const closeAfterPick = () => {
    if (lent() && !multi && !isFilter) dropdownHost?.close();
  };

  //: One node says both "nothing matched" and "fill that in first",
  //: so the stated message is put back when the search can run.
  const emptyMessage = noResults?.textContent ?? "";
  const setEmptyMessage = (message: string | null) => {
    if (noResults) noResults.textContent = message ?? emptyMessage;
  };

  const setNoResults = (visible: boolean) => {
    if (!noResults) return;
    const offered = createRow !== null && !createRow.hidden;
    noResults.classList.toggle("hidden", !visible || offered);
    if (visible) showPanel();
  };

  // ── Highlight tracking (filter mode) ──
  let highlightedRow: HTMLElement | null = null;

  //: Lent since the last hide.
  let wasLent = false;
  dropdownHost?.addEventListener("dropdown:show", (event) => {
    if (event.target === dropdownHost && lent()) wasLent = true;
  });

  // A host close resets the ARIA state.
  dropdownHost?.addEventListener("dropdown:hide", (event) => {
    if (event.target !== dropdownHost) return;
    clearHighlight();
    syncExpanded();
    if (!wasLent) return;
    //: The leave focusout skipped.
    wasLent = false;
    cancelPendingSearch();
    revertDrop();
  });

  // Hover never scrolls; keyboard steps do.
  const highlightOption = (row: HTMLElement | null, { scroll = true } = {}) => {
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
    if (scroll) row.scrollIntoView({ block: "nearest" });
  };

  const clearHighlight = () => {
    if (highlightedRow) {
      highlightedRow.removeAttribute("data-search-select-highlighted");
      if (!multi) highlightedRow.setAttribute("aria-selected", "false");
      highlightedRow = null;
    }
    search.removeAttribute("aria-activedescendant");
  };

  //: The mouse moves the one highlight.
  followPointer(options, NAVIGABLE_ROWS, row => {
    if (row !== highlightedRow) highlightOption(row, { scroll: false });
  });

  // Keyboard-navigable rows: value rows plus the pinned modifier
  // pseudo-options — every row advertised as role="option" must be reachable
  // by ArrowUp/ArrowDown, and modifier rows sit first in document order.
  const getVisibleOptions = (): HTMLElement[] => {
    const all = options.querySelectorAll<HTMLElement>(NAVIGABLE_ROWS);
    return Array.from(all).filter(
      row => row.style.display !== "none" && !row.hidden
    );
  };

  const autoHighlight = (query: string) => {
    const lower = query.toLowerCase();
    //: A query highlights none on exact label.
    const visible = getVisibleOptions().filter(
      row =>
        !lower ||
        !row.hasAttribute("data-search-select-none-option") ||
        (row.getAttribute("data-label") || "").toLowerCase() === lower
    );
    if (visible.length === 0) {
      clearHighlight();
      return;
    }
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
      return;
    }
    //: Before the modifier fallback: a create row is the one thing a
    //: non-matching query can commit, which is why it was offered.
    const createRowNode = visible.find(row =>
      row.hasAttribute("data-search-select-create")
    );
    if (createRowNode) {
      highlightOption(createRowNode);
    } else if (!lower) {
      //: Enter on an empty panel submits, never picks none.
      const firstRow = visible.find(
        row => !row.hasAttribute("data-search-select-none-option")
      );
      if (firstRow) highlightOption(firstRow);
      else clearHighlight();
    } else {
      clearHighlight();
    }
  };

  // Get active values in both form and filter modes
  const getSelectedValues = (): Set<string> => {
    const values = new Set<string>();
    pills.querySelectorAll<HTMLInputElement>(HELD_VALUE_INPUTS).forEach(input => {
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

  const setHint = (row: HTMLElement, hint: string) => {
    const slot = row.querySelector<HTMLElement>("[data-search-select-hint]");
    if (hint) row.setAttribute("data-hint", hint);
    else row.removeAttribute("data-hint");
    if (!slot) {
      if (hint) console.warn("search-select: a hint reached a row with no hint slot");
      return;
    }
    slot.textContent = hint;
    slot.hidden = !hint;
  };

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
    setHint(row, option.hint ?? "");
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

  const createRow = options.querySelector<HTMLElement>("[data-search-select-create]");
  //: One POST at a time: no route absorbs a repeat.
  let creating = false;

  /** Every label the panel holds, lowercased. */
  const loadedLabels = (): string[] =>
    Array.from(
      options.querySelectorAll<HTMLElement>(
        "[data-search-select-option], [data-search-select-none-option]"
      )
    ).map(row => (row.getAttribute("data-label") ?? "").trim().toLowerCase());

  // Equality, not the substring the panel filters with: `PlayStation`
  // beside `PlayStation 4` matches that filter, and a rule built on it
  // would refuse to create any name a longer one holds.
  const createRowOffered = (query: string): boolean => {
    if (!create || !createRow) return false;
    const wanted = query.trim().toLowerCase();
    if (!wanted) return false;
    return Boolean(replaceVerb) || !loadedLabels().includes(wanted);
  };

  //: Exact, case kept: `halo` beside `Halo` is another name.
  const replacesARow = (query: string): boolean =>
    Boolean(replaceVerb) &&
    Array.from(options.querySelectorAll<HTMLElement>("[data-search-select-option]")).some(
      row => (row.getAttribute("data-label") ?? "").trim() === query.trim()
    );

  // Shown once an answer decides, as the no-results node is: a row
  // judged on the loaded window alone flashes on every keystroke.
  const setCreateRow = (query: string) => {
    if (!createRow) return;
    const offered = createRowOffered(query);
    createRow.hidden = !offered;
    if (offered) {
      const label = createRow.querySelector<HTMLElement>("[data-label]") ?? createRow;
      const verb = replacesARow(query) ? replaceVerb : createVerb;
      label.textContent = `${verb} \u201c${query.trim()}\u201d`;
      //: It replaces the empty-state message rather than standing beside it.
      noResults?.classList.add("hidden");
    }
  };

  /** Put the created row in the panel: an id it holds takes the new label. */
  const upsertOption = (option: SearchSelectOption) => {
    const held = options.querySelector<HTMLElement>(
      `[data-search-select-option][data-value="${cssEscape(option.value)}"]`
    );
    if (held) {
      held.setAttribute("data-label", option.label);
      setLabel(held, option.label);
      (held as OptionRow)._searchSelectOption = option;
      return held;
    }
    const row = buildRow(option);
    options.insertBefore(row, noResults ?? createRow ?? null);
    return row;
  };

  /** Commit the typed name as `create` says. */
  const commitCreate = () => {
    if (creating || !createRow || createRow.hidden) return;
    const name = search.value.trim();
    if (!name) return;
    if (create === "select") {
      const option: SearchSelectOption = { value: name, label: name, data: {} };
      upsertOption(option);
      createRow.hidden = true;
      selectOption(option);
      hidePanel();
      closeAfterPick();
      return;
    }
    if (create === "event") {
      container.dispatchEvent(
        new CustomEvent<SearchSelectCreateDetail>("search-select:create", {
          bubbles: true,
          detail: { name, replaces: replacesARow(name) },
        })
      );
      return;
    }
    if (create !== "post") return;
    creating = true;
    createRow.setAttribute("aria-disabled", "true");
    const body = { name, ...resolveParams(container, params) };
    const clearsAtStart = clears;
    void window
      .fetchWithEvents(createUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify(body),
      })
      .then(response => {
        if (response.ok)
          return response.json() as Promise<{ value: string; label: string }>;
        //: A refusal queues its own sentence, which rides the header.
        //: An answer that queues none says nothing at all, so this does.
        if (!response.headers.get("X-Events")) {
          reportClientError(
            "search-select[create]",
            `${response.status} from ${createUrl}`
          );
        }
        return null;
      })
      .then(created => {
        //: A refusal keeps the query, and its sentence is the toast the
        //: route queued. Nothing is selected.
        if (!created) return;
        const option: SearchSelectOption = {
          value: created.value,
          label: created.label,
          data: {},
        };
        upsertOption(option);
        createRow.hidden = true;
        if (clears !== clearsAtStart) return;
        selectOption(option);
        hidePanel();
        closeAfterPick();
      })
      .catch(error => {
        //: Nothing else reports here: the row would un-dim on a POST
        //: that never landed, and a second press would look the same.
        reportClientError(
          "search-select[create]",
          String((error as Error)?.message ?? error)
        );
      })
      .finally(() => {
        creating = false;
        createRow.removeAttribute("aria-disabled");
      });
  };

  /** Hold the one option a search answered, where nothing is held. */
  const commitTheSoleOption = () => {
    if (!commitSoleOption || multi || soleDeclined) return;
    //: A typed box holds a name, not a label to overwrite.
    if (container._searchSelectDirty) return;
    if (pills.querySelector('input[type="hidden"]')) return;
    const rows = options.querySelectorAll<HTMLElement>("[data-search-select-option]");
    if (rows.length !== 1) return;
    const option = optionFromRow(rows[0]);
    container._searchSelectSetSelected?.(option.value, option.label);
    //: Select it, as focus does, so the next key replaces it.
    if (document.activeElement === search) search.select();
  };

  // ── A depended-on field changed: the loaded window is about another
  //    parent's rows, and so is any selection held from it. ──
  const onDependencyChange = () => {
    if (!dependencyFields.length) return;
    const signature = dependencySignature(container, dependencyFields);
    if (signature === dependencyValues) return;
    dependencyValues = signature;
    soleDeclined = false;
    //: None belongs to no parent.
    if (noneLabel) {
      if (!holdsNone()) holdNone();
    } else {
      container._searchSelectClear?.();
    }
    loadedQuery = null;
    if (searchUrl) fetchFromServer(currentQuery());
  };

  // ── Fetch matching rows from the server. The previous in-flight request is
  //    aborted so a slower earlier response can never overwrite a newer one. ──
  const fetchFromServer = (query: string) => {
    pendingRequest?.controller.abort();
    //: A param the route requires and the form has not filled in: the
    //: request would be refused, and an empty panel reads as an answer.
    //: The panel names the field to fill in instead.
    const unfilled = unfilledFields(container, params);
    if (unfilled.length) {
      pendingRequest = null;
      loadedQuery = null;
      answering(() => {
        renderRows([]);
        if (createRow) createRow.hidden = true;
        const names = unfilled.map(field => fieldLabel(container, field));
        setEmptyMessage(`Pick a ${names.join(" and a ")} first`);
        setNoResults(true);
      });
      return;
    }
    setEmptyMessage(null);
    const request: PendingSearch = { controller: new AbortController(), query };
    pendingRequest = request;
    // Built via URL so a search-url that already carries a query string (e.g.
    // the preset picker's ?mode=games) composes instead of double-`?`ing.
    const url = new URL(searchUrl ?? "", window.location.origin);
    url.searchParams.set("q", query);
    Object.entries(resolveParams(container, params)).forEach(([key, value]) => {
      url.searchParams.set(key, value);
    });
    dependencyValues = dependencySignature(container, dependencyFields);
    if (prefetch && !query) url.searchParams.set("limit", String(prefetch));
    const signal = request.controller.signal;
    fetch(url.toString(), { credentials: "same-origin", signal })
      .then(response => {
        if (!response.ok) throw new Error(`${response.status} from ${url.pathname}`);
        return response.json() as Promise<SearchSelectOption[]>;
      })
      .then(items => {
        //: An answer can land after its abort.
        if (signal.aborted) return;
        pendingRequest = null;
        loadedQuery = query;
        answering(() => {
          renderRows(items);
          // Re-apply the live query: the box may hold more text than was sent.
          const remaining = filterRows(currentQuery());
          commitTheSoleOption();
          setCreateRow(currentQuery());
          setNoResults(remaining === 0);
          autoHighlight(currentQuery());
          //: A panel holding the create row alone still opens.
          if (createRow && !createRow.hidden) showPanel();
        });
      })
      .catch(error => {
        //: Superseded or cancelled; nothing awaits it.
        if (error?.name === "AbortError" || signal.aborted) return;
        pendingRequest = null;
        answering(() => {
          setEmptyMessage(LOAD_FAILED);
          setNoResults(true);
        });
        reportClientError("search-select[search]", String(error?.message ?? error));
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
      if (createRow) createRow.hidden = true;
      setNoResults(false);
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        fetchFromServer(query);
      }, DEBOUNCE_MS);
    } else {
      const remaining = filterRows(query);
      setCreateRow(query);
      setNoResults(remaining === 0);
    }
    autoHighlight(query);
    showPanel();
  };

  // ── Single-select combobox: the search box shows the committed label. A
  //    value is committed only by an explicit pick; the first edit of a
  //    committed field clears it. The box text is never rewritten except by a
  //    pick filling in its label — blur touches neither value nor text. ──
  if (!multi) container._searchSelectLabel = search.value;

  //: Single-select: each option held since setOptions.
  const remembered = new Map<string, SearchSelectOption>();
  const renderedHeld = multi ? null : pills.querySelector<HTMLInputElement>(HELD_VALUE_INPUTS);
  if (renderedHeld) {
    remembered.set(renderedHeld.value, {
      value: renderedHeld.value,
      label: search.value,
      data: {},
    });
  }

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
    openList();
  };

  //: Fill the list for the box text, then open.
  const openList = () => {
    if (freeText) {
      rebuildFreeTextRow(currentQuery());
    } else if (searchUrl) {
      const query = currentQuery();
      filterRows(query);
      setNoResults(false);
      if (prefetch && loadedQuery !== query && pendingRequest?.query !== query) {
        //: Not debounced: an open asks at once.
        fetchFromServer(query);
      } else {
        autoHighlight(query);
      }
    } else {
      setNoResults(filterRows(currentQuery()) === 0);
      autoHighlight(currentQuery());
    }
    showPanel();
  };
  search.addEventListener("focus", runFocus);

  // A click fires no focus while focused.
  search.addEventListener("click", () => {
    if (document.activeElement === search && !isPanelOpen() && !search.disabled) openList();
  });

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
    // editing abandons it — clear the value now, so only an explicit pick
    // commits one (revert-on-leave restores it on a leave). With nothing
    // committed there is no value to clear and no event fires.
    if (!multi && !container._searchSelectDirty) {
      container._searchSelectDirty = true;
      if (container._searchSelectLabel) {
        heldBeforeDrop = droppable();
        pills.innerHTML = "";
        container._searchSelectLabel = "";
        emitChange(null);
      }
    }
    runSearch();
    // After the first-edit branch above — an earlier call would still see the
    // hidden input on the exact keystroke that abandons the committed value.
    syncUncommitted();
  });

  // ── Keyboard navigation (both form and filter modes) ──
  search.addEventListener("keydown", (event) => {
    const { key } = event;

    if (!["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(key)) return;
    const visible = getVisibleOptions();
    if (visible.length === 0) {
      if (key === "Escape" && !delegated) hidePanel();
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
        if (highlightedRow.hasAttribute("data-search-select-create")) {
          commitCreate();
          return;
        }
        if (highlightedRow.hasAttribute("data-search-select-none-option")) {
          pickNone();
          return;
        }
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
          closeAfterPick();
        }
        hidePanel(); // also clears the highlight
      }
    } else if (key === "Escape" && !delegated) {
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

  // Fire the external row-action event (form mode only: the preset delete ×).
  const dispatchAction = (action: string, option: SearchSelectOption) => {
    container.dispatchEvent(
      new CustomEvent<SearchSelectActionDetail>("search-select:action", {
        bubbles: true,
        detail: { name, action, option },
      })
    );
  };

  // ── Option click. One action-button lookup: filter +/− add a pill inline; a
  //    form-mode action button goes out as an event. ──
  options.addEventListener("click", (event) => {
    const target = event.target as Element;

    if (target.closest("[data-search-select-none-option]")) {
      pickNone();
      return;
    }

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

    if (target.closest("[data-search-select-create]")) {
      commitCreate();
      return;
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
      closeAfterPick();
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
      if (key !== "value" && key !== "label" && key !== "hint" && key !== "ssOption") {
        data[key] = row.dataset[key] ?? "";
      }
    });
    const option: SearchSelectOption = {
      value: row.getAttribute("data-value") ?? "",
      label: row.getAttribute("data-label") ?? "",
      data,
    };
    const hint = row.getAttribute("data-hint");
    if (hint) option.hint = hint;
    return option;
  };

  // `emit` lets a programmatic restore (setSelected) seed the selection WITHOUT
  // firing search-select:change — otherwise restoring a value after a re-render
  // would re-trigger the consumer's on-change logic (e.g. the leaf row's field
  // reset), looping. User-driven picks pass emit=true (the default); form
  // mode emits only when the held changes.
  const selectOption = (option: SearchSelectOption, emit = true) => {
    const before = heldNow();
    heldBeforeDrop = null;
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
      remembered.set(option.value, option);
      hidePanel();
    }
    if (emit) soleDeclined = false;
    syncUncommitted();
    if (emit && (isFilter || !sameHeld(before, heldNow()))) emitChange(option);
  };

  // A + dialog's created row lands here.
  const takeCreated = (event: CustomEvent<FormDialogCreatedDetail>) => {
    if (search.disabled) return;
    upsertOption(event.detail);
    selectOption(event.detail);
    // Taken only once it landed.
    event.preventDefault();
    event.stopPropagation();
  };
  container.addEventListener(FORM_DIALOG_CREATED, takeCreated);
  face?.addEventListener(FORM_DIALOG_CREATED, takeCreated);

  // Commit a value from code, firing no change.
  container._searchSelectSetSelected = (value: string, label?: string) => {
    selectOption({ value, label: label ?? value, data: {} }, false);
  };

  // Public refetch: re-request the prefetch window with a blank query. The box
  // shows the held label again, never a stale query. The request in flight
  // keeps the focus that follows from asking again.
  container._searchSelectRefetch = () => {
    if (!searchUrl) return;
    //: A debounced search for the old query would answer after this one.
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    search.value = multi ? "" : (container._searchSelectLabel ?? "");
    if (!multi) container._searchSelectDirty = false;
    syncUncommitted();
    fetchFromServer("");
  };

  // Public silent clear: drop the committed selection (hidden inputs, label,
  // query text) without firing search-select:change. Consumers whose pick is a
  // command rather than a persistent value (the preset picker) call this right
  // after handling the pick, so no lingering selection can pin a stale row
  // through renderRows' selected-value preservation (issue #297).
  container._searchSelectClear = () => {
    heldBeforeDrop = null;
    pills.innerHTML = "";
    container._searchSelectLabel = "";
    container._searchSelectDirty = false;
    search.value = "";
    syncUncommitted();
    syncSelectedStates();
  };

  //: Hold none: an empty value that posts.
  const holdNone = () => {
    container._searchSelectClear?.();
    const input = buildHidden("");
    input.setAttribute("data-search-select-none", "");
    pills.appendChild(input);
    search.value = noneLabel;
    container._searchSelectLabel = noneLabel;
    syncUncommitted();
  };

  //: A person picks none.
  const pickNone = () => {
    const before = heldNow();
    holdNone();
    soleDeclined = false;
    hidePanel();
    if (!sameHeld(before, heldNow())) emitNone();
    closeAfterPick();
  };

  const offeredRow = (value: string): HTMLElement | undefined =>
    Array.from(options.querySelectorAll<HTMLElement>("[data-search-select-option]")).find(
      row => row.getAttribute("data-value") === value
    );
  const knownOption = (value: string): SearchSelectOption | undefined => {
    const offered = offeredRow(value);
    return offered ? optionFromRow(offered) : remembered.get(value);
  };
  container._searchSelectOffers = (value: string) => knownOption(value) !== undefined;
  container._searchSelectHeldLabel = () => {
    const { values, none } = heldNow();
    if (!none && values.length !== 1) return null;
    return container._searchSelectLabel || null;
  };

  //: Hold a row or remembered value.
  container._searchSelectHoldValue = (value: string): boolean => {
    const option = knownOption(value);
    const alreadyHeld =
      !container._searchSelectDirty && sameHeld(heldNow(), { values: [value], none: false });
    if (option && alreadyHeld) return true;
    if (option) selectOption(option, false);
    else if (noneLabel) holdNone();
    else container._searchSelectClear?.();
    return option !== undefined;
  };
  container._searchSelectHoldNone = () => {
    // A rewrite would close an open panel.
    if (!holdsNone()) holdNone();
  };

  //: Replace rows; forget memory; drop unoffered held.
  container._searchSelectSetOptionGroups = (groups: SearchSelectOptionGroup[]) => {
    remembered.clear();
    options
      .querySelectorAll<HTMLElement>(
        "[data-search-select-option], [data-search-select-group-header]"
      )
      .forEach(node => node.remove());
    const before = noResults ?? null;
    const items = groups.flatMap(group => group.options);
    for (const group of groups) {
      const header = group.label ? cloneTemplate("header") : null;
      if (header) {
        header.textContent = group.label;
        options.insertBefore(header, before);
      }
      group.options.forEach(item => options.insertBefore(buildRow(item), before));
    }
    const selected = getSelectedValues();
    const stillOffered = items.some(item => selected.has(String(item.value)));
    if (selected.size && !stillOffered) {
      if (noneLabel) holdNone();
      else container._searchSelectClear?.();
    }
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
      pills.querySelectorAll<HTMLInputElement>(HELD_VALUE_INPUTS)
    ).map(input => input.value);
  };

  const dispatchChange = (detail: SearchSelectChangeDetail) => {
    syncSelectedStates();
    syncClearButton();
    if (syncUrl) syncToUrl(detail.values);
    container.dispatchEvent(
      new CustomEvent<SearchSelectChangeDetail>("search-select:change", {
        bubbles: true,
        detail,
      })
    );
  };

  const emitChange = (last: SearchSelectOption | null) =>
    dispatchChange({ name, values: currentValues(), last, none: false });

  const emitNone = () => dispatchChange({ name, values: [], last: null, none: true });

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
  // Seed the uncommitted cue too — a no-op for the server-rendered states
  // (committed label + hidden input, or empty box), but keeps the attribute
  // truthful if init ever runs against hydrated markup.
  syncUncommitted();

  // Late answers must not reopen the panel.
  const cancelPendingSearch = () => {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    pendingRequest?.controller.abort();
    pendingRequest = null;
  };

  // ── The clear ×: empties query and value, or holds none. ──
  if (clearButton) {
    //: Pointer press keeps focus: no phone keyboard.
    clearButton.addEventListener("mousedown", event => event.preventDefault());
    //: Tab onto × closes the panel.
    clearButton.addEventListener("focus", () => {
      cancelPendingSearch();
      hidePanel();
    });
    clearButton.addEventListener("click", () => {
      // A disabled box takes no clear.
      if (search.disabled) return;
      const heldValue = currentValues().length > 0;
      const fromFocus = document.activeElement === clearButton;
      cancelPendingSearch();
      clears += 1;
      container._searchSelectClear?.();
      soleDeclined = true;
      //: Loaded rows answered the old query; drop them.
      if (searchUrl) {
        options
          .querySelectorAll("[data-search-select-option]")
          .forEach(row => row.remove());
        loadedQuery = null;
        if (!fromFocus && isPanelOpen()) fetchFromServer("");
      }
      filterRows("");
      setCreateRow("");
      setNoResults(false);
      if (noneLabel) {
        holdNone();
        emitNone();
      } else if (heldValue) {
        emitChange(null);
      }
      container.dispatchEvent(
        new CustomEvent<SearchSelectClearDetail>("search-select:clear", {
          bubbles: true,
          detail: { name },
        })
      );
      //: × hides; focus moves to the input.
      if (fromFocus) search.focus();
    });
  }

  // ── Close panel when focus leaves the widget (e.g. Tab away) ──
  // focusout bubbles, so the container catches the input losing focus in every
  // mode. Option mousedown preventDefault keeps the input focused during a
  // click, so this only fires on a genuine exit.
  //: Restores what a first keystroke dropped.
  const revertDrop = (): void => {
    const restore = heldBeforeDrop;
    heldBeforeDrop = null;
    if (props.revertOnLeave && restore && !pills.querySelector('input[type="hidden"]')) {
      if (restore.none) holdNone();
      else selectOption({ value: restore.value, label: restore.label, data: {} }, false);
    }
    // Otherwise blur keeps text and value.
  };
  container.addEventListener("focusout", (event) => {
    //: Moves blur it; the hide leaves.
    if (lent()) return;
    if (!container.contains(event.relatedTarget as Node)) {
      cancelPendingSearch();
      hidePanel(); // also clears the highlight
      revertDrop();
    }
  });

  // ── The face: name, mirrored state, its own ×. ──
  if (face && faceOpen) {
    const open = faceOpen;
    const fieldName =
      search.labels?.[0]?.textContent?.trim() ||
      search.getAttribute("aria-label")?.trim() ||
      search.placeholder.trim();
    if (faceName && fieldName) faceName.textContent = `${fieldName}${FACE_SEPARATOR}`;
    const sheetTitle = dropdownHost
      ? ownChild(dropdownHost, `[${SHEET_ATTRIBUTES.title}]`)
      : null;
    if (sheetTitle && !sheetTitle.textContent?.trim()) sheetTitle.textContent = fieldName;

    //: Code writes the box's state directly.
    const mirrorBox = () => {
      open.disabled = search.disabled;
      for (const attribute of ["aria-invalid", "aria-describedby"]) {
        const value = search.getAttribute(attribute);
        if (value === null) open.removeAttribute(attribute);
        else open.setAttribute(attribute, value);
      }
    };
    mirrorBox();
    new MutationObserver(mirrorBox).observe(search, {
      attributes: true,
      attributeFilter: ["disabled", "aria-invalid", "aria-describedby"],
    });

    const openSheet = () => {
      if (!open.disabled) dropdownHost?.open(open);
    };
    open.addEventListener("click", openSheet);
    //: The label's box is hidden below sm.
    for (const label of Array.from(search.labels ?? [])) {
      label.addEventListener("click", (event) => {
        if (face.getClientRects().length === 0) return;
        event.preventDefault();
        openSheet();
      });
    }
    faceClear?.addEventListener("click", () => {
      clearButton?.click();
      open.focus();
    });
  }

  // Typed text is the value; submitting commits the draft.
  if (create === "select") {
    const hostingForm = container.closest("form");
    if (!hostingForm) {
      //: Only a form submit commits a typed draft.
      throw new Error(`search-select[${props.name}]: create="select" outside a form`);
    }
    hostingForm.addEventListener("formdata", event => {
      const draft = search.value.trim();
      if (container._searchSelectDirty && draft) event.formData.set(props.name, draft);
    });
  }

  // A field source is a dependency: the hosting form is where both a native
  // control's `change` and another combobox's own event arrive.
  if (dependencyFields.length) {
    dependencyValues = dependencySignature(container, dependencyFields);
    const form = container.closest("form");
    form?.addEventListener("change", onDependencyChange);
    form?.addEventListener("search-select:change", onDependencyChange);
  }

  // The + follows its source fields.
  const dialogCreateParams = parseParams(props.dialogCreateParams || null, DIALOG_CREATE_CONTEXT);
  const dialogCreateFields = sourceFields(dialogCreateParams);
  if (dialogCreateFields.length) {
    const rewrite = (): void => rewriteDialogCreate(container, dialogCreateParams);
    container._searchSelectRewriteDialogCreate = rewrite;
    const onSourceInput = (event: Event): void => {
      const target = event.target;
      if (target instanceof Element && dialogCreateFields.includes(target.getAttribute("name") ?? "")) {
        rewrite();
      }
    };
    const form = container.closest("form");
    form?.addEventListener("input", onSourceInput);
    form?.addEventListener("change", onSourceInput);
    rewrite();
  }

  // Focus before wiring fired no event; replay.
  if (!search.hasAttribute("autofocus")) {
    //: A click or script focused it first.
    if (document.activeElement === search) runFocus();
  } else {
    // Only an empty autofocus box opens.
    //: A held none counts as empty.
    const startedEmpty = !search.value || holdsNone();
    // Native autofocus lands before this frame.
    requestAnimationFrame(() => {
      if (!search.isConnected || !startedEmpty) return;
      if (document.activeElement === search) {
        // Listener missed native autofocus; open explicitly.
        runFocus();
      } else {
        search.focus();
      }
    });
  }

  return true;
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
      ? Array.from(pills.querySelectorAll<HTMLInputElement>(HELD_VALUE_INPUTS)).map(input => input.value)
      : [];
    container.setAttribute("data-values", JSON.stringify(values));
  });
}

export class SearchSelectElement extends HTMLElement {
  private initialized = false;

  connectedCallback(): void {
    // Moved rows keep listeners; wire once.
    if (!this.initialized) this.initialized = initWidget(this);
    //: Inserted anew, the source may differ.
    else (this as SearchSelectContainer)._searchSelectRewriteDialogCreate?.();
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

  /** Hold `value` silently, else none or nothing. */
  holdValue(value: string): boolean {
    return this.initializedPart("_searchSelectHoldValue")(value);
  }

  /** Hold none, firing no change. */
  holdNone(): void {
    this.initializedPart("_searchSelectHoldNone")();
  }

  /** Whether a row or memory offers `value`. */
  offers(value: string): boolean {
    return this.initializedPart("_searchSelectOffers")(value);
  }

  /** Whether it has wired itself. */
  get wired(): boolean {
    return this.initialized;
  }

  /** Held label, none's included; null mid-edit. */
  heldLabel(): string | null {
    return this.initializedPart("_searchSelectHeldLabel")();
  }

  private initializedPart<Part extends HeldPart>(
    part: Part
  ): NonNullable<SearchSelectContainer[Part]> {
    const found = (this as SearchSelectContainer)[part];
    if (!found) throw new Error(`search-select[${this.getAttribute("name")}]: not initialised`);
    return found as NonNullable<SearchSelectContainer[Part]>;
  }

  /** Silently drop the committed selection (hidden inputs, label, query text)
   *  without firing a change event. Leaves nothing picked, never none.
   *  No-op until the widget has initialised. */
  clearSelection(): void {
    (this as SearchSelectContainer)._searchSelectClear?.();
  }

  /** Replace inline rows silently; drops an unoffered value. */
  setOptions(options: SearchSelectOption[]): void {
    this.setOptionGroups([{ label: "", options }]);
  }

  /** Grouped `setOptions`; a blank label heads nothing. */
  setOptionGroups(groups: SearchSelectOptionGroup[]): void {
    (this as SearchSelectContainer)._searchSelectSetOptionGroups?.(groups);
  }
}

customElements.define("search-select", SearchSelectElement);
