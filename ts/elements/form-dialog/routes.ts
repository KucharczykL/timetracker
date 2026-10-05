/** Where an answer goes. */
import type { Answer, Messages, Page } from "./answer.js";

export type OpenRoute =
  | { kind: "present"; page: Page; url: URL }
  | { kind: "toast"; messages: Messages }
  | { kind: "continue"; url: URL }
  /** Follow the link itself. */
  | { kind: "follow" };

export type SubmitRoute =
  | { kind: "present"; page: Page; url: URL }
  | { kind: "continue"; url: URL }
  /** The last dialog closes; the host reloads. */
  | { kind: "close"; target: URL; messages: Messages }
  | { kind: "closeTop"; messages: Messages }
  | { kind: "error"; status: number };

export function routeOpen(answer: Answer): OpenRoute {
  switch (answer.kind) {
    case "page":
      return { kind: "present", page: answer.page, url: answer.url };
    case "done":
      return { kind: "toast", messages: answer.messages };
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
  throw new Error(`form-dialog: unhandled route ${JSON.stringify(value)}`);
}
