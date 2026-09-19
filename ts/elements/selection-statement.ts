/** The selection a table holds, and the statement it makes of it.
 *
 * Pure: no DOM, no element. A selection is either the keys a person marked or
 * the whole matching set beside the exclusions taken off it since — never the
 * keys as a fallback for the set, because a page holds one page of keys and
 * the set is every row the filter matches.
 */

export type SelectionStatement =
  | { keys: string[] }
  | { all: true; filter: string; count: number; except: string[] };

export interface SelectionState {
  keys: Set<string>;
  all: boolean;
  except: Set<string>;
}

export function emptySelection(): SelectionState {
  return { keys: new Set(), all: false, except: new Set() };
}

export function clearSelection(): SelectionState {
  return emptySelection();
}

function copy(state: SelectionState): SelectionState {
  return {
    keys: new Set(state.keys),
    all: state.all,
    except: new Set(state.except),
  };
}

/** One row's mark. Under the matching set this records an exclusion, so the
 * scope survives a person taking one row back out of it. */
export function toggleKey(state: SelectionState, key: string): SelectionState {
  const next = copy(state);
  const marks = next.all ? next.except : next.keys;
  if (marks.has(key)) marks.delete(key);
  else marks.add(key);
  return next;
}

/** Check-all for the page: every key on the page marked, or every one of them
 * taken back. */
export function setPage(
  state: SelectionState,
  pageKeys: string[],
  checked: boolean,
): SelectionState {
  const next = copy(state);
  const marks = next.all ? next.except : next.keys;
  for (const key of pageKeys) {
    if (next.all === checked) marks.delete(key);
    else marks.add(key);
  }
  return next;
}

export function selectAllMatching(state: SelectionState): SelectionState {
  const next = copy(state);
  next.all = true;
  next.keys.clear();
  next.except.clear();
  return next;
}

/** The keys between two rows of the page, inclusive, in page order. An anchor
 * the page no longer holds leaves the target alone. */
export function rangeKeys(
  pageKeys: string[],
  anchorKey: string,
  targetKey: string,
): string[] {
  const anchor = pageKeys.indexOf(anchorKey);
  const target = pageKeys.indexOf(targetKey);
  if (target < 0) return [];
  if (anchor < 0) return [targetKey];
  const start = Math.min(anchor, target);
  const end = Math.max(anchor, target);
  return pageKeys.slice(start, end + 1);
}

export type CheckAllState = "checked" | "indeterminate" | "unchecked";

export function checkAllState(
  state: SelectionState,
  pageKeys: string[],
): CheckAllState {
  const marked = pageKeys.filter((key) =>
    state.all ? !state.except.has(key) : state.keys.has(key),
  ).length;
  if (marked === 0) return "unchecked";
  return marked === pageKeys.length ? "checked" : "indeterminate";
}

/** How many rows the selection holds. `matchingCount` is the paginator's, and
 * is read only under the matching set. */
export function selectionCount(
  state: SelectionState,
  matchingCount: number,
): number {
  if (!state.all) return state.keys.size;
  return Math.max(matchingCount - state.except.size, 0);
}

/** The statement, sorted so one selection reads as one value. */
export function statementFor(
  state: SelectionState,
  filter: string,
  count: number,
): SelectionStatement {
  if (!state.all) return { keys: [...state.keys].sort() };
  return { all: true, filter, count, except: [...state.except].sort() };
}
