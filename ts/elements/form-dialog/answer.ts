/** A fetched page, read at its final URL. */
import { reportClientError } from "../../client-errors.js";

/** Origin, path and sorted query. */
export type PageUrl = string;

export function normalizedUrl(url: string | URL): PageUrl {
  const parsed = new URL(url, location.href);
  const pairs = Array.from(parsed.searchParams).sort(([nameA, valueA], [nameB, valueB]) =>
    nameA === nameB ? compare(valueA, valueB) : compare(nameA, nameB),
  );
  const query = new URLSearchParams(pairs).toString();
  return `${parsed.origin}${parsed.pathname}${query ? `?${query}` : ""}`;
}

function compare(left: string, right: string): number {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

export function sameUrl(left: string | URL, right: string | URL): boolean {
  return normalizedUrl(left) === normalizedUrl(right);
}

export interface AnswerPage {
  /** The children of `#main-container`. */
  content: DocumentFragment;
  /** `data-page-title`: the raw page title. */
  title: string;
  readOnly: boolean;
  /** The `#django-messages` payloads. */
  messages: unknown[];
  /** Absolute module script URLs. */
  modules: string[];
  /** The children of `#navbar`, when present. */
  navbar: DocumentFragment | null;
  /** The `data-*` attributes of `<html>`. */
  htmlData: Record<string, string>;
  documentTitle: string;
}

export interface Answer {
  url: URL;
  redirected: boolean;
  status: number;
  /** Null without `#main-container`. */
  page: AnswerPage | null;
}

/** Scripts that would run; data scripts stay. */
const RUNNABLE_SCRIPT =
  'script:not([type]), script[type=""], script[type="module"], script[type="text/javascript"]';

function childrenOf(element: Element): DocumentFragment {
  const fragment = document.createDocumentFragment();
  fragment.append(...Array.from(element.childNodes, (node) => document.importNode(node, true)));
  fragment.querySelectorAll(RUNNABLE_SCRIPT).forEach((script) => script.remove());
  return fragment;
}

function readMessages(parsed: Document): unknown[] {
  const script = parsed.getElementById("django-messages");
  if (!script) return [];
  try {
    const payloads: unknown = JSON.parse(script.textContent || "[]");
    return Array.isArray(payloads) ? payloads : [payloads];
  } catch (error) {
    reportClientError("form-dialog[messages]", String((error as Error)?.message ?? error), {
      toast: false,
    });
    return [];
  }
}

function htmlData(parsed: Document): Record<string, string> {
  const data: Record<string, string> = {};
  for (const attribute of parsed.documentElement.attributes) {
    if (attribute.name.startsWith("data-")) data[attribute.name] = attribute.value;
  }
  return data;
}

export function readPage(parsed: Document, url: URL): AnswerPage | null {
  const main = parsed.getElementById("main-container");
  if (!main) return null;
  const navbar = parsed.getElementById("navbar");
  return {
    content: childrenOf(main),
    title: main.getAttribute("data-page-title") ?? "",
    readOnly: main.hasAttribute("data-read-only"),
    messages: readMessages(parsed),
    modules: Array.from(
      parsed.querySelectorAll<HTMLScriptElement>("script[type=module][src]"),
      (script) => new URL(script.getAttribute("src") ?? "", url).href,
    ),
    navbar: navbar ? childrenOf(navbar) : null,
    htmlData: htmlData(parsed),
    documentTitle: parsed.title,
  };
}

/** `requested` stands in for an empty `response.url`. */
export async function readAnswer(response: Response, requested: URL): Promise<Answer> {
  const url = new URL(response.url || requested.href);
  const contentType = response.headers.get("content-type") ?? "";
  const page = contentType.includes("text/html")
    ? readPage(new DOMParser().parseFromString(await response.text(), "text/html"), url)
    : null;
  return { url, redirected: response.redirected, status: response.status, page };
}
