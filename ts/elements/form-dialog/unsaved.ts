/** What a form dialog's forms hold. */

/** A form's position in the body, then a field name. */
type SnapshotKey = string;
/** Every form's values, by form and name. */
export type FormSnapshot = ReadonlyMap<SnapshotKey, readonly string[]>;

/** A sign-in rewrites it everywhere. */
const CSRF_NAME = "csrfmiddlewaretoken";

function keyOf(formIndex: number, name: string): SnapshotKey {
  return `${formIndex}\u0000${name}`;
}

/** One submitted value, as comparable text. */
export function fieldValue(value: FormDataEntryValue): string {
  if (typeof value === "string") return value;
  if (value.name === "" && value.size === 0) return "";
  return `file:${value.name}:${value.size}:${value.lastModified}`;
}

function formsOf(body: ParentNode): HTMLFormElement[] {
  return [...body.querySelectorAll("form")];
}

function readForm(form: HTMLFormElement, formIndex: number, into: Map<SnapshotKey, string[]>): void {
  for (const [name, value] of new FormData(form)) {
    if (name === CSRF_NAME) continue;
    const key = keyOf(formIndex, name);
    const values = into.get(key) ?? [];
    values.push(fieldValue(value));
    into.set(key, values);
  }
}

export function snapshotForms(body: ParentNode): FormSnapshot {
  const snapshot = new Map<SnapshotKey, string[]>();
  formsOf(body).forEach((form, formIndex) => readForm(form, formIndex, snapshot));
  return snapshot;
}

/** Empty strings alone read as nothing. */
function normalised(values: readonly string[] | undefined): readonly string[] {
  if (values === undefined || values.every((value) => value === "")) return [];
  return values;
}

function sameValues(left: readonly string[] | undefined, right: readonly string[] | undefined): boolean {
  const first = normalised(left);
  const second = normalised(right);
  return first.length === second.length && first.every((value, index) => value === second[index]);
}

function keysOfForm(snapshot: FormSnapshot, formIndex: number): SnapshotKey[] {
  const prefix = keyOf(formIndex, "");
  return [...snapshot.keys()].filter((key) => key.startsWith(prefix));
}

/** The forms whose values left the baseline. */
export function changedForms(body: ParentNode, baseline: FormSnapshot): HTMLFormElement[] {
  return formsOf(body).filter((form, formIndex) => {
    const current = new Map<SnapshotKey, string[]>();
    readForm(form, formIndex, current);
    const keys = new Set([...keysOfForm(baseline, formIndex), ...current.keys()]);
    return [...keys].some((key) => !sameValues(baseline.get(key), current.get(key)));
  });
}
