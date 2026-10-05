/** Where an answer goes. */
import type { Answer, Messages, Page } from "./answer.js";

type Present = { readonly kind: "present"; readonly page: Page; readonly url: URL };
type Continue = { readonly kind: "continue"; readonly url: URL };

export type OpenRoute =
  | Present
  | Continue
  | { readonly kind: "toast"; readonly messages: Messages }
  /** Finished elsewhere with nothing to say. */
  | { readonly kind: "navigate"; readonly url: URL }
  /** Follow the link itself. */
  | { readonly kind: "follow" };

export type SubmitRoute =
  | Present
  | Continue
  /** The last dialog closes; reload or go to `target`. */
  | { readonly kind: "close"; readonly target: URL; readonly messages: Messages }
  | { readonly kind: "closeTop"; readonly messages: Messages }
  | { readonly kind: "error"; readonly status: number };

export function routeOpen(answer: Answer): OpenRoute {
  switch (answer.kind) {
    case "page":
      return { kind: "present", page: answer.page, url: answer.url };
    case "done":
      return answer.messages.length > 0
        ? { kind: "toast", messages: answer.messages }
        : { kind: "navigate", url: answer.url };
    case "continue":
      return { kind: "continue", url: answer.url };
    case "none":
      return { kind: "follow" };
    default:
      return assertNever(answer);
  }
}

/** `alone`: no other modal is open. */
export function routeSubmit(answer: Answer, alone: boolean): SubmitRoute {
  switch (answer.kind) {
    case "page":
      return { kind: "present", page: answer.page, url: answer.url };
    case "continue":
      return { kind: "continue", url: answer.url };
    case "done":
      return alone
        ? { kind: "close", target: answer.url, messages: answer.messages }
        : { kind: "closeTop", messages: answer.messages };
    case "none":
      return { kind: "error", status: answer.status };
    default:
      return assertNever(answer);
  }
}

export function assertNever(value: never): never {
  throw new Error(`form-dialog: unhandled value ${JSON.stringify(value)}`);
}
