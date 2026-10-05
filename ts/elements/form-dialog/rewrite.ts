/** Fits a fetched fragment into the host page. */
import type { ModuleUrl } from "./answer.js";

/** Attributes holding one id. */
const ID_ATTRIBUTES = ["list", "form", "popovertarget", "aria-activedescendant"];
/** Attributes holding a list of ids. */
const ID_LIST_ATTRIBUTES = [
  "for",
  "headers",
  "aria-labelledby",
  "aria-describedby",
  "aria-controls",
  "aria-owns",
  "aria-flowto",
  "aria-errormessage",
  "aria-details",
];
const URL_ATTRIBUTES = ["href", "action", "formaction"];

/** Every element, template contents included. */
function* elementsOf(root: ParentNode): Generator<Element> {
  if (root instanceof Element) yield root;
  for (const element of root.querySelectorAll("*")) {
    yield element;
    if (element instanceof HTMLTemplateElement) yield* elementsOf(element.content);
  }
}

/** Prefixes ids and every reference to them. */
export function prefixIds(root: ParentNode, prefix: string): void {
  const elements = Array.from(elementsOf(root));
  const ids = new Set(elements.map((element) => element.id).filter(Boolean));
  const prefixed = (id: string): string => (ids.has(id) ? `${prefix}${id}` : id);
  for (const element of elements) {
    if (element.id) element.id = prefixed(element.id);
    for (const name of ID_ATTRIBUTES) {
      const value = element.getAttribute(name);
      if (value) element.setAttribute(name, prefixed(value));
    }
    for (const name of ID_LIST_ATTRIBUTES) {
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
