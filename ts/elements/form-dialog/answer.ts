/** A fetched page, read at its final URL. */
import { reportClientError } from "../../client-errors.js";

/** Origin, path and sorted query. */
export type PageUrl = string;
/** A toast payload; `<toast-stack>` checks it. */
export type MessagePayload = unknown;
/** An absolute module script URL. */
export type ModuleUrl = string;
/** `data-*` name to value. */
export type HtmlDataAttributes = Readonly<Record<string, string>>;

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
  /** `#main-container`'s children; consumed when inserted. */
  readonly content: DocumentFragment;
  /** `data-page-title`: the raw page title. */
  readonly title: string;
  /** The route is in `READ_ONLY`. */
  readonly readOnly: boolean;
  readonly messages: readonly MessagePayload[];
  readonly modules: readonly ModuleUrl[];
  /** `#navbar`'s children, when present. */
  readonly navbar: DocumentFragment | null;
  readonly htmlData: HtmlDataAttributes;
  /** The `<title>` text. */
  readonly documentTitle: string;
}

export interface Answer {
  readonly url: URL;
  readonly redirected: boolean;
  readonly status: number;
  /** Null for non-HTML or no `#main-container`. */
  readonly page: AnswerPage | null;
}

/** Every script but data scripts. */
const RUNNABLE_SCRIPT = 'script:not([type*="json"])';

function report(detail: string): void {
  reportClientError("form-dialog[answer]", detail, { toast: false });
}

function childrenOf(element: Element): DocumentFragment {
  const fragment = document.createDocumentFragment();
  fragment.append(...Array.from(element.childNodes, (node) => document.importNode(node, true)));
  const dropped = fragment.querySelectorAll(RUNNABLE_SCRIPT);
  if (dropped.length > 0) report(`dropped ${dropped.length} script(s) from page content`);
  dropped.forEach((script) => script.remove());
  return fragment;
}

function readMessages(parsed: Document): MessagePayload[] {
  const script = parsed.getElementById("django-messages");
  if (!script) return [];
  try {
    const payloads: unknown = JSON.parse(script.textContent || "[]");
    return Array.isArray(payloads) ? payloads : [payloads];
  } catch (error) {
    report(`unreadable messages: ${String((error as Error)?.message ?? error)}`);
    return [];
  }
}

function htmlData(parsed: Document): HtmlDataAttributes {
  const data: Record<string, string> = {};
  for (const attribute of parsed.documentElement.attributes) {
    if (attribute.name.startsWith("data-")) data[attribute.name] = attribute.value;
  }
  return data;
}

/** Classic scripts never load; name the missing ones. */
function reportClassicScripts(parsed: Document, url: URL): void {
  const loaded = new Set(
    Array.from(document.querySelectorAll<HTMLScriptElement>("script[src]"), (script) => script.src),
  );
  for (const script of parsed.querySelectorAll<HTMLScriptElement>("script[src]")) {
    if (script.type === "module") continue;
    const source = new URL(script.getAttribute("src") ?? "", url).href;
    if (!loaded.has(source)) report(`classic script not loaded: ${source}`);
  }
}

export function readPage(parsed: Document, url: URL): AnswerPage | null {
  const main = parsed.getElementById("main-container");
  if (!main) return null;
  reportClassicScripts(parsed, url);
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
