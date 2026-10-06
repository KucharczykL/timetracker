/** A dialog answer, read and checked. */
import { reportClientError } from "../../client-errors.js";
import {
  type ContinueAnswer,
  type CreatedAnswer,
  type CreatedOption,
  type DoneAnswer,
  PAGE_WIDTHS,
  type PageAnswer,
  type PageWidth,
  type ToastPayload,
} from "../../generated/form-dialog.js";

/** Origin, path and sorted query. */
export type PageUrl = string;
/** A module script URL, resolved absolute. */
export type ResolvedModuleUrl = string;
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
  /** Fitted by prepare, emptied by fill; once. */
  readonly content: DocumentFragment;
  readonly title: string;
  readonly width: PageWidth;
  readonly modules: readonly ResolvedModuleUrl[];
  readonly messages: Messages;
}

// Typed from the wire: a Python rename fails tsc.
const PAGE: PageAnswer["kind"] = "page";
const DONE: DoneAnswer["kind"] = "done";
const CONTINUE: ContinueAnswer["kind"] = "continue";
const CREATED: CreatedAnswer["kind"] = "created";

export type Answer =
  /** `url`: what the content's URLs resolve against. */
  | { readonly kind: typeof PAGE; readonly url: URL; readonly page: Page }
  | { readonly kind: typeof DONE; readonly url: URL; readonly messages: Messages }
  | { readonly kind: typeof CONTINUE; readonly url: URL }
  /** Done, with the row it made. */
  | {
      readonly kind: typeof CREATED;
      readonly url: URL;
      readonly messages: Messages;
      readonly option: Readonly<CreatedOption>;
    }
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

function isPageWidth(value: unknown): value is PageWidth {
  return PAGE_WIDTHS.includes(value as PageWidth);
}

function isTextList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isText);
}

/** Shape only; `<toast-stack>` checks the rest. */
function isMessages(value: unknown): value is ToastPayload[] {
  return (
    Array.isArray(value) &&
    value.every((message) => isText((message as Partial<ToastPayload> | null)?.message))
  );
}

function isPage(fields: Fields): fields is Fields & PageAnswer {
  return (
    fields.kind === PAGE &&
    isText(fields.title) &&
    isPageWidth(fields.width) &&
    isText(fields.html) &&
    isTextList(fields.modules) &&
    isMessages(fields.messages)
  );
}

function isDone(fields: Fields): fields is Fields & DoneAnswer {
  return fields.kind === DONE && isText(fields.url) && isMessages(fields.messages);
}

function isTextRecord(value: unknown): value is Record<string, string> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every(isText)
  );
}

function isOption(value: unknown): value is CreatedOption {
  const option = value as Partial<CreatedOption> | null;
  return (
    typeof option === "object" &&
    option !== null &&
    isText(option.value) &&
    isText(option.label) &&
    isTextRecord(option.data)
  );
}

/** The option is checked apart: a bad one is still done. */
function isCreated(
  fields: Fields,
): fields is Fields & Omit<CreatedAnswer, "option"> & { option: unknown } {
  return fields.kind === CREATED && isText(fields.url) && isMessages(fields.messages);
}

function isContinue(fields: Fields): fields is Fields & ContinueAnswer {
  return fields.kind === CONTINUE && isText(fields.url);
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
  if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
    report(`not a dialog answer (status ${response.status})`);
    return null;
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    report(`unreadable JSON (status ${response.status}): ${String(error)}`);
    return null;
  }
  if (typeof body === "object" && body !== null && !Array.isArray(body)) return body as Fields;
  report(`not an answer object (status ${response.status})`);
  return null;
}

/** `requested` stands in for an empty `response.url`. */
export async function readAnswer(response: Response, requested: URL): Promise<Answer> {
  const url = new URL(response.url || requested.href);
  const fields = await fieldsOf(response);
  if (!fields) return { kind: "none", status: response.status };
  if (isPage(fields)) {
    const page: Page = {
      content: contentOf(fields.html),
      title: fields.title,
      width: fields.width,
      modules: fields.modules.map((module) => new URL(module, url).href),
      messages: fields.messages,
    };
    return { kind: PAGE, url, page };
  }
  if (isDone(fields)) {
    return { kind: DONE, url: new URL(fields.url, url), messages: fields.messages };
  }
  if (isCreated(fields)) {
    const target = new URL(fields.url, url);
    if (isOption(fields.option)) {
      return { kind: CREATED, url: target, messages: fields.messages, option: fields.option };
    }
    // Saved all the same.
    report(`created answer with an unreadable option: ${JSON.stringify(fields.option)}`);
    return { kind: DONE, url: target, messages: fields.messages };
  }
  if (isContinue(fields)) return { kind: CONTINUE, url: new URL(fields.url, url) };
  report(`unknown answer (status ${response.status}): ${String(fields.kind)}`);
  return { kind: "none", status: response.status };
}
