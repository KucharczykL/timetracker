/** A dialog answer, read and checked. */
import { reportClientError } from "../../client-errors.js";
import type {
  ContinueAnswer,
  DoneAnswer,
  PageAnswer,
  ToastPayload,
} from "../../generated/form-dialog.js";

/** Origin, path and sorted query. */
export type PageUrl = string;
/** An absolute module script URL. */
export type ModuleUrl = string;
export type Messages = readonly ToastPayload[];

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

export interface Page {
  /** Consumed when inserted. */
  readonly content: DocumentFragment;
  readonly title: string;
  readonly modules: readonly ModuleUrl[];
  readonly messages: Messages;
}

export type Answer =
  /** `url`: what the content's URLs resolve against. */
  | { readonly kind: "page"; readonly url: URL; readonly page: Page }
  | { readonly kind: "done"; readonly url: URL; readonly messages: Messages }
  | { readonly kind: "continue"; readonly url: URL }
  /** Not a dialog answer. */
  | { readonly kind: "none"; readonly status: number };

/** Every script but data scripts. */
const RUNNABLE_SCRIPT = 'script:not([type*="json"])';

function report(detail: string): void {
  reportClientError("form-dialog[answer]", detail, { toast: false });
}

type Fields = Record<string, unknown>;

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function isTextList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isText);
}

function isMessages(value: unknown): value is ToastPayload[] {
  return Array.isArray(value);
}

function isPage(fields: Fields): fields is Fields & PageAnswer {
  return (
    fields.kind === "page" &&
    isText(fields.title) &&
    isText(fields.html) &&
    isTextList(fields.modules) &&
    isMessages(fields.messages)
  );
}

function isDone(fields: Fields): fields is Fields & DoneAnswer {
  return fields.kind === "done" && isText(fields.url) && isMessages(fields.messages);
}

function isContinue(fields: Fields): fields is Fields & ContinueAnswer {
  return fields.kind === "continue" && isText(fields.url);
}

function contentOf(html: string): DocumentFragment {
  const template = document.createElement("template");
  template.innerHTML = html;
  const content = document.importNode(template.content, true);
  const dropped = content.querySelectorAll(RUNNABLE_SCRIPT);
  if (dropped.length > 0) report(`dropped ${dropped.length} script(s) from page content`);
  dropped.forEach((script) => script.remove());
  return content;
}

async function fieldsOf(response: Response): Promise<Fields | null> {
  if (!(response.headers.get("content-type") ?? "").includes("application/json")) return null;
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    report(`unreadable JSON (status ${response.status}): ${String(error)}`);
    return null;
  }
  return typeof body === "object" && body !== null ? (body as Fields) : null;
}

/** `requested` stands in for an empty `response.url`. */
export async function readAnswer(response: Response, requested: URL): Promise<Answer> {
  const url = new URL(response.url || requested.href);
  const fields = await fieldsOf(response);
  if (fields && isPage(fields)) {
    const page: Page = {
      content: contentOf(fields.html),
      title: fields.title,
      modules: fields.modules.map((module) => new URL(module, url).href),
      messages: fields.messages,
    };
    return { kind: "page", url, page };
  }
  if (fields && isDone(fields)) {
    return { kind: "done", url: new URL(fields.url, url), messages: fields.messages };
  }
  if (fields && isContinue(fields)) return { kind: "continue", url: new URL(fields.url, url) };
  if (fields) report(`unknown answer (status ${response.status}): ${String(fields.kind)}`);
  return { kind: "none", status: response.status };
}
