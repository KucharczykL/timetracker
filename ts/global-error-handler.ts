/**
 * Global uncaught-error net (issue #328). Registers window "error" +
 * "unhandledrejection" listeners that funnel uncaught failures into the shared
 * client-error seam, log-only (no toast). Page-global furniture loaded directly
 * by Page(), a sibling of toast.ts — not a custom element.
 *
 * Handlers must never throw: a throw inside a window "error" listener re-fires
 * the error event and re-enters this handler. Every listener body is wrapped in
 * a swallowing try/catch.
 */
import { reportClientError } from "./client-errors.js";

export interface ErrorFields {
  message: string;
  filename: string;
  lineno: number;
  colno: number;
  stack: string;
}

const EXTENSION_SCHEMES = [
  "chrome-extension://",
  "moz-extension://",
  "safari-extension://",
  "safari-web-extension://",
];

let installed = false;

/** Coerce an unhandledrejection reason into a message string without throwing. */
export function safeStringify(reason: unknown): string {
  if (typeof reason === "symbol") {
    return "<unstringifiable rejection reason>";
  }
  if (
    reason &&
    typeof reason === "object" &&
    typeof (reason as { message?: unknown }).message === "string"
  ) {
    const name =
      typeof (reason as { name?: unknown }).name === "string"
        ? (reason as { name: string }).name
        : "Error";
    return `${name}: ${(reason as { message: string }).message}`;
  }
  if (reason && typeof reason === "object") {
    try {
      const text = JSON.stringify(reason);
      return text || "<unstringifiable rejection reason>";
    } catch {
      return "<unstringifiable rejection reason>";
    }
  }
  try {
    const text = String(reason);
    return text || "<unstringifiable rejection reason>";
  } catch {
    return "<unstringifiable rejection reason>";
  }
}

/** First non-empty stack line, skipping a V8 leading message line (Firefox has none). */
function firstStackFrame(stack: string, message: string): string {
  const lines = stack
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) return "";
  // V8 format: first line is "ErrorType: message" (ends with the message text).
  // Firefox format: first line is already a frame ("f@url:line:col") — keep it.
  // Skip line 0 only when it ends with the message (V8 header), not a frame line.
  if (message && lines[0].endsWith(message) && !lines[0].startsWith("at ") && !lines[0].includes("@")) {
    return lines[1] ?? "";
  }
  return lines[0];
}

/** A bare URL whose origin is an extension scheme (checked at the start). */
function isExtensionUrl(value: string): boolean {
  return EXTENSION_SCHEMES.some((scheme) => value.startsWith(scheme));
}

/** A stack frame line embedding an extension URL (scheme appears mid-string). */
function frameHasExtensionUrl(frame: string): boolean {
  return EXTENSION_SCHEMES.some((scheme) => frame.includes(scheme));
}

export function shouldReport(fields: ErrorFields): boolean {
  const frame = firstStackFrame(fields.stack, fields.message);
  if (isExtensionUrl(fields.filename) || frameHasExtensionUrl(frame)) return false;
  if (fields.message.startsWith("Script error") && fields.filename === "" && fields.stack === "") {
    return false;
  }
  return true;
}

export function buildDetail(fields: ErrorFields): string {
  const parts: string[] = [fields.message];
  if (fields.filename) {
    const filename = fields.filename.slice(0, 200);
    parts.push(`@ ${filename}:${fields.lineno}:${fields.colno}`);
  }
  const frame = firstStackFrame(fields.stack, fields.message);
  if (frame) parts.push(`| ${frame}`);
  return parts.join(" ").slice(0, 500);
}

function report(context: string, fields: ErrorFields): void {
  if (!shouldReport(fields)) return;
  reportClientError(context, buildDetail(fields), { toast: false });
}

function onError(event: ErrorEvent): void {
  try {
    const target = event.target;
    if (target && target !== window && target instanceof HTMLElement) {
      // Resource-load error (fires on the element, seen thanks to capture:true).
      const url = target.getAttribute("src") ?? target.getAttribute("href") ?? "";
      report("window.onerror", {
        message: `resource load failed: <${target.localName}>`,
        filename: url,
        lineno: 0,
        colno: 0,
        stack: "",
      });
      return;
    }
    report("window.onerror", {
      message: event.message ?? "",
      filename: event.filename ?? "",
      lineno: event.lineno ?? 0,
      colno: event.colno ?? 0,
      stack: event.error?.stack ?? "",
    });
  } catch {
    // Never throw from an error listener (would re-enter via the error event).
  }
}

function onRejection(event: PromiseRejectionEvent): void {
  try {
    const reason = event.reason;
    const isError = reason instanceof Error;
    report("unhandledrejection", {
      message: isError ? reason.message : safeStringify(reason),
      filename: "",
      lineno: 0,
      colno: 0,
      stack: isError ? (reason.stack ?? "") : "",
    });
  } catch {
    // Never throw.
  }
}

export function installGlobalErrorHandler(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("error", onError, { capture: true });
  window.addEventListener("unhandledrejection", onRejection);
}

installGlobalErrorHandler();
