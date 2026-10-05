/** Where an answer goes. */
import { type Answer, type AnswerPage, type MessagePayload, sameUrl } from "./answer.js";

export type Messages = readonly MessagePayload[];

export interface SubmitContext {
  /** The host page's URL, as `location` holds it. */
  hostUrl: string;
  /** No other modal is open. */
  alone: boolean;
}

export type OpenRoute =
  | { kind: "toast"; messages: Messages }
  | { kind: "navigate"; url: URL; messages: Messages }
  | { kind: "present"; page: AnswerPage }
  /** Follow the link itself. */
  | { kind: "follow" };

export type SubmitRoute =
  | { kind: "present"; page: AnswerPage }
  /** Not saved; the server answered no page. */
  | { kind: "error"; status: number }
  | { kind: "swap"; page: AnswerPage }
  | { kind: "navigate"; url: URL; messages: Messages }
  | { kind: "closeTop"; messages: Messages };

export function routeOpen(answer: Answer, hostUrl: string): OpenRoute {
  const page = answer.page;
  if (answer.redirected && sameUrl(answer.url, hostUrl)) {
    return { kind: "toast", messages: page?.messages ?? [] };
  }
  if (!page) return { kind: "follow" };
  if (page.readOnly) return { kind: "navigate", url: answer.url, messages: page.messages };
  return { kind: "present", page };
}

export function routeSubmit(answer: Answer, context: SubmitContext): SubmitRoute {
  const page = answer.page;
  // A redirect saved; show where it went.
  if (!page) {
    return answer.redirected
      ? { kind: "navigate", url: answer.url, messages: [] }
      : { kind: "error", status: answer.status };
  }
  if (!answer.redirected || !page.readOnly) return { kind: "present", page };
  if (!context.alone) return { kind: "closeTop", messages: page.messages };
  if (sameUrl(answer.url, context.hostUrl)) return { kind: "swap", page };
  return { kind: "navigate", url: answer.url, messages: page.messages };
}

export function assertNever(value: never): never {
  throw new Error(`form-dialog: unhandled route ${JSON.stringify(value)}`);
}
