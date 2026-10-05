/** Fits a fetched fragment into the host page. */
import {
  FORM_DIALOG_ID_ATTRIBUTES,
  FORM_DIALOG_ID_LIST_ATTRIBUTES,
} from "../../generated/form-dialog.js";
import type { ModuleUrl } from "./answer.js";
/** An element id. */
export type ElementId = string;
/** Prepended to every id, e.g. "form-dialog-3-". */
export type IdPrefix = string;

const URL_ATTRIBUTES = ["href", "action", "formaction"];

/** Every element, template contents included. */
function* elementsOf(root: ParentNode): Generator<Element> {
  if (root instanceof Element) yield root;
  for (const element of root.querySelectorAll("*")) {
    yield element;
    if (element instanceof HTMLTemplateElement) yield* elementsOf(element.content);
  }
}

/** Prefixes ids and the listed references. */
export function prefixIds(root: ParentNode, prefix: IdPrefix): void {
  const elements = Array.from(elementsOf(root));
  const ids = new Set(elements.map((element) => element.id).filter(Boolean));
  const prefixed = (id: ElementId): ElementId => (ids.has(id) ? `${prefix}${id}` : id);
  for (const element of elements) {
    if (element.id) element.id = prefixed(element.id);
    for (const name of FORM_DIALOG_ID_ATTRIBUTES) {
      const value = element.getAttribute(name);
      if (value) element.setAttribute(name, prefixed(value));
    }
    for (const name of FORM_DIALOG_ID_LIST_ATTRIBUTES) {
      const value = element.getAttribute(name);
      if (value) element.setAttribute(name, value.split(/\s+/).map(prefixed).join(" "));
    }
    const href = element.getAttribute("href");
    if (href?.startsWith("#")) element.setAttribute("href", `#${prefixed(href.slice(1))}`);
  }
}

/** Resolves URLs against the answer, not the host. */
export function resolveUrls(root: ParentNode, base: URL): void {
  for (const element of elementsOf(root)) {
    if (element instanceof HTMLFormElement && !element.getAttribute("action")) {
      element.setAttribute("action", base.href);
    }
    for (const name of URL_ATTRIBUTES) {
      const value = element.getAttribute(name);
      if (value === null || value.startsWith("#")) continue;
      element.setAttribute(name, new URL(value, base).href);
    }
  }
}

export type ModuleLoader = (url: ModuleUrl) => Promise<unknown>;

const loadModule: ModuleLoader = (url) => import(/* @vite-ignore */ url);

/** Rejects when any module fails. */
export async function importModules(
  urls: readonly ModuleUrl[],
  load: ModuleLoader = loadModule,
): Promise<void> {
  await Promise.all(urls.map((url) => load(url)));
}
