/** Where an answer goes. */
import { type Answer, type PageUrl, sameUrl } from "./answer.js";

export interface RouteContext {
  hostUrl: PageUrl;
  /** Only this dialog is open. */
  alone: boolean;
}

export type OpenRoute =
  | { kind: "toast" }
  | { kind: "navigate"; url: URL }
  | { kind: "present" }
  /** Follow the link itself. */
  | { kind: "follow" };

export type SubmitRoute =
  | { kind: "present" }
  | { kind: "error" }
  | { kind: "swap" }
  | { kind: "navigate"; url: URL }
  | { kind: "closeTop" };

export function routeOpen(answer: Answer, context: RouteContext): OpenRoute {
  if (answer.redirected && sameUrl(answer.url, context.hostUrl)) return { kind: "toast" };
  if (!answer.page) return { kind: "follow" };
  if (answer.page.readOnly) return { kind: "navigate", url: answer.url };
  return { kind: "present" };
}

export function routeSubmit(answer: Answer, context: RouteContext): SubmitRoute {
  if (!answer.page) return { kind: "error" };
  if (!answer.redirected || !answer.page.readOnly) return { kind: "present" };
  if (!context.alone) return { kind: "closeTop" };
  if (sameUrl(answer.url, context.hostUrl)) return { kind: "swap" };
  return { kind: "navigate", url: answer.url };
}
