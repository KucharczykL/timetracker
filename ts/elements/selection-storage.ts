/** Where a selection waits while a person turns the page. */

import { SelectionState } from "./selection-statement.js";

const PREFIX = "selectable-table:";
const VERSION = 1;

/** One selection per table: the library and the table name it, the path tells
 * its pages apart from another list's. */
export function storageKeyFor(scope: string, path: string): string {
  return `${PREFIX}${scope}:${path}`;
}

function store(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function writeSelection(
  key: string,
  filter: string,
  state: SelectionState,
): void {
  if (state.mode === "some" && state.keys.size === 0) {
    forgetSelection(key);
    return;
  }
  const value =
    state.mode === "all"
      ? { version: VERSION, filter, all: true, except: [...state.except] }
      : { version: VERSION, filter, all: false, keys: [...state.keys] };
  try {
    store()?.setItem(key, JSON.stringify(value));
  } catch {
    // An unstorable selection still stands on this page.
  }
}

function stringsOf(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is string => typeof entry === "string");
}

/** Parsed into the state, never cast into it: what comes back is a person's
 * own storage, which anything may have written. */
function stateOf(value: Record<string, unknown>): SelectionState | null {
  if (value.all === true) {
    return { mode: "all", except: new Set(stringsOf(value.except)) };
  }
  const keys = new Set(stringsOf(value.keys));
  return keys.size ? { mode: "some", keys } : null;
}

export function readSelection(
  key: string,
  filter: string,
): SelectionState | null {
  let raw: string | null = null;
  try {
    raw = store()?.getItem(key) ?? null;
  } catch {
    return null;
  }
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // Nobody will read this value either; it only costs a parse each load.
    forgetSelection(key);
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) {
    forgetSelection(key);
    return null;
  }
  const value = parsed as Record<string, unknown>;
  if (value.version !== VERSION) {
    forgetSelection(key);
    return null;
  }
  // A filter is kept, not forgotten: the set it names is one a person may
  // come back to, and its selection is still that set's.
  if (value.filter !== filter) return null;
  return stateOf(value);
}

export function forgetSelection(key: string): void {
  try {
    store()?.removeItem(key);
  } catch {
    // Nothing kept, nothing to forget.
  }
}
