/** Where a selection waits while a person turns the page. */

import { emptySelection, SelectionState } from "./selection-statement.js";

const PREFIX = "selectable-table:";
const VERSION = 1;

interface StoredSelection {
  version: number;
  filter: string;
  keys: string[];
  all: boolean;
  except: string[];
}

/** One selection per list, so its pages share it. */
export function storageKeyFor(path: string): string {
  return `${PREFIX}${path}`;
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
  if (!state.all && state.keys.size === 0) {
    forgetSelection(key);
    return;
  }
  const value: StoredSelection = {
    version: VERSION,
    filter,
    keys: [...state.keys],
    all: state.all,
    except: [...state.except],
  };
  try {
    store()?.setItem(key, JSON.stringify(value));
  } catch {
    // An unstorable selection still stands on this page.
  }
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
  let value: StoredSelection;
  try {
    value = JSON.parse(raw) as StoredSelection;
  } catch {
    return null;
  }
  if (value?.version !== VERSION || value.filter !== filter) return null;
  const state = emptySelection();
  for (const marked of value.keys ?? []) state.keys.add(marked);
  for (const excluded of value.except ?? []) state.except.add(excluded);
  state.all = Boolean(value.all);
  if (!state.all && state.keys.size === 0) return null;
  return state;
}

export function forgetSelection(key: string): void {
  try {
    store()?.removeItem(key);
  } catch {
    // Nothing kept, nothing to forget.
  }
}
