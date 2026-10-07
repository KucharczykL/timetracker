/** What a form dialog's forms hold. */

type FieldName = string;
/** One form's values, by field name. */
type FormValues = ReadonlyMap<FieldName, readonly string[]>;
/** One entry per form, in document order. */
export type FormSnapshot = readonly FormValues[];

/** A sign-in rewrites it everywhere. */
const CSRF_NAME = "csrfmiddlewaretoken";

/** One submitted value, as comparable text. */
export function fieldValue(value: FormDataEntryValue): string {
  if (typeof value === "string") return value;
  if (value.name === "" && value.size === 0) return "";
  return `file:${value.name}:${value.size}:${value.lastModified}`;
}

/** A nested dialog's forms are its own. */
function formsOf(body: ParentNode): HTMLFormElement[] {
  const owner = body instanceof Element ? body.closest("dialog") : null;
  return [...body.querySelectorAll("form")].filter((form) => form.closest("dialog") === owner);
}

function readForm(form: HTMLFormElement): FormValues {
  const values = new Map<FieldName, string[]>();
  for (const [name, value] of new FormData(form)) {
    if (name === CSRF_NAME) continue;
    values.set(name, [...(values.get(name) ?? []), fieldValue(value)]);
  }
  return values;
}

export function snapshotForms(body: ParentNode): FormSnapshot {
  return formsOf(body).map(readForm);
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

function sameForm(baseline: FormValues | undefined, current: FormValues): boolean {
  const before = baseline ?? new Map<FieldName, readonly string[]>();
  const names = new Set([...before.keys(), ...current.keys()]);
  return [...names].every((name) => sameValues(before.get(name), current.get(name)));
}

/** The forms whose values left the baseline. */
export function changedForms(body: ParentNode, baseline: FormSnapshot): HTMLFormElement[] {
  return formsOf(body).filter((form, formIndex) => !sameForm(baseline[formIndex], readForm(form)));
}
