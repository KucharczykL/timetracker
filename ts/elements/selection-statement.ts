/** A table's selection, and the statement it makes. */

export type SelectionStatement =
  | { mode: "some"; keys: string[] }
  | { mode: "all"; filter: string; count: number; except: string[] };

/** Either the keys a person marked, or the set beside the rows taken out of
 * it — never both, because the mark means the opposite thing under each. */
export type SelectionState =
  | { mode: "some"; keys: ReadonlySet<string> }
  | { mode: "all"; except: ReadonlySet<string> };

export function emptySelection(): SelectionState {
  return { mode: "some", keys: new Set() };
}

export function markedKeys(state: SelectionState): ReadonlySet<string> {
  return state.mode === "all" ? state.except : state.keys;
}

/** Whether a row stands selected. The one place that reads the inversion. */
export function isMarked(state: SelectionState, key: string): boolean {
  return state.mode === "all" ? !state.except.has(key) : state.keys.has(key);
}

function withMarks(
  state: SelectionState,
  marks: Set<string>,
): SelectionState {
  return state.mode === "all"
    ? { mode: "all", except: marks }
    : { mode: "some", keys: marks };
}

/** One row's mark; under the set, an exclusion. */
export function toggleKey(state: SelectionState, key: string): SelectionState {
  const marks = new Set(markedKeys(state));
  if (marks.has(key)) marks.delete(key);
  else marks.add(key);
  return withMarks(state, marks);
}

/** Check-all: the whole page marked, or taken back. */
export function setPage(
  state: SelectionState,
  pageKeys: string[],
  checked: boolean,
): SelectionState {
  const marks = new Set(markedKeys(state));
  const excluding = state.mode === "all";
  for (const key of pageKeys) {
    if (excluding === checked) marks.delete(key);
    else marks.add(key);
  }
  return withMarks(state, marks);
}

export function selectAllMatching(): SelectionState {
  return { mode: "all", except: new Set() };
}

/** Keys the table no longer holds.
 *
 * Only a marked key is dropped: under the set an exclusion outlives its row,
 * because dropping it would put the removed row back in the scope and raise
 * the count — and a removal in this app can be undone, so the row may return.
 */
export function forgetKeys(
  state: SelectionState,
  gone: Iterable<string>,
): SelectionState {
  if (state.mode === "all") return state;
  const keys = new Set(state.keys);
  for (const key of gone) keys.delete(key);
  return { mode: "some", keys };
}

/** The keys between two rows, inclusive. */
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
  const marked = pageKeys.filter((key) => isMarked(state, key)).length;
  if (marked === 0) return "unchecked";
  return marked === pageKeys.length ? "checked" : "indeterminate";
}

/** How many rows the selection holds. `matchingCount` is the paginator's, and
 * is read only under the set. */
export function selectionCount(
  state: SelectionState,
  matchingCount: number,
): number {
  if (state.mode === "some") return state.keys.size;
  if (!Number.isFinite(matchingCount)) return 0;
  return Math.max(matchingCount - state.except.size, 0);
}

/** The statement, sorted: one selection, one value. */
export function statementFor(
  state: SelectionState,
  filter: string,
  count: number,
): SelectionStatement {
  if (state.mode === "some") return { mode: "some", keys: [...state.keys].sort() };
  return { mode: "all", filter, count, except: [...state.except].sort() };
}
