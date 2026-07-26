/**
 * Client-error reporting seam (issue #232). One home for turning a browser-side
 * failure into (1) a guaranteed server log line, (2) a best-effort toast, and
 * (3) a best-effort inline mark, replacing the old silent console.warn pattern
 * scattered across the filter widgets.
 *
 * Signal reliability is deliberately tiered: the server POST always fires; the
 * toast may be lost on initial page load (its listener attaches during
 * alpine:init, after a custom element's connectedCallback); the ring mark may
 * sit inside a closed dropdown panel. The log line is the one guaranteed signal.
 */
import { getCsrfToken } from "./csrf.js";

const ENDPOINT = "/api/client-error/";
// The literal class string Tailwind's ts/ scan compiles (never concatenate).
const DEGRADED_CLASSES = "ring-2 ring-danger";

// One report + one toast per distinct failure per page load.
const reported = new Set<string>();

const MAX_REPORTS_PER_PAGE = 25;
let reportCount = 0;

export interface ReportOptions {
  toast?: boolean;
}

// `crypto.randomUUID` is SECURE-CONTEXT ONLY: on a plain-http origin that is
// not localhost — a LAN dev server at http://10.0.0.x:8000, say — it is
// `undefined`, and so is `crypto.subtle`. `crypto.getRandomValues` is not
// gated that way, so it covers the case; Math.random is the last resort.
//
// This is load-bearing, not defensive noise: errorId() runs inside
// reportClientError, which is itself called from `catch` blocks all over the
// app. A throw here escapes the catch that invoked it and turns a HANDLED
// degradation into a hard failure — e.g. a missing `Temporal` (Safari < 26)
// went from "calendar header lacks its month name" to "calendar renders
// nothing and its toggle does nothing", because the reporting call in the
// catch threw before the caller could return its fallback.
function errorId(): string {
  const cryptoApi = globalThis.crypto;
  try {
    const uuid = cryptoApi?.randomUUID?.();
    if (uuid) return uuid.slice(0, 8);
    if (cryptoApi?.getRandomValues) {
      const bytes = new Uint8Array(4);
      cryptoApi.getRandomValues(bytes);
      return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    }
  } catch {
    // Fall through: an id is a correlation aid, never a reason to fail.
  }
  return Math.random().toString(16).slice(2, 10).padStart(8, "0");
}

/** Log a browser-side error to the server + console, deduped, best-effort toast.
 *  Returns the generated error id. Never throws. */
export function reportClientError(
  context: string,
  detail: string,
  options: ReportOptions = {},
): string {
  const { toast = true } = options;
  const id = errorId();
  const key = `${context}|${detail}`;
  if (reported.has(key)) return id;
  reported.add(key);

  reportCount += 1;
  if (reportCount > MAX_REPORTS_PER_PAGE) {
    // One line at the boundary, then silence: bound endpoint load, not page CPU.
    if (reportCount === MAX_REPORTS_PER_PAGE + 1) {
      console.error("client error reporting suppressed (cap reached)");
    }
    return id;
  }

  console.error(`client error [${id}] ${context}: ${detail}`);
  if (toast && typeof window !== "undefined") {
    window.toast?.(`Filter failed to load (error ${id}) — reload the page`, "error");
  }

  if (typeof fetch !== "undefined" && typeof document !== "undefined") {
    // The try wraps the CALL SET-UP, not just the promise: getCsrfToken() and
    // JSON.stringify run synchronously while building the request, so a throw
    // there would escape past the .catch() and out of this function.
    try {
      void fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
        body: JSON.stringify({ error_id: id, context, detail, url: location.href }),
      }).catch(() => {
        // Reporting must never break the page: swallow network/HTTP failure.
      });
    } catch {
      // Same contract for a synchronous failure while assembling the request.
    }
  }

  return id;
}

/** Test-only: reset the module-level dedup Set and cap counter. Never called in production. */
export function __resetClientErrorState(): void {
  reported.clear();
  reportCount = 0;
}

function markDegraded(element: HTMLElement, id: string): void {
  element.setAttribute("data-degraded", "json-parse");
  element.setAttribute("title", `Failed to load (error ${id})`);
  element.classList.add(...DEGRADED_CLASSES.split(" "));
}

/** Parse `raw` as JSON; on failure report + (best-effort) mark + return `fallback`. */
export function parseJSONWithReport<T>(
  raw: string | null | undefined,
  fallback: T,
  context: string,
  element?: HTMLElement,
): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch (error) {
    const detail = String((error as Error)?.message ?? error);
    const id = reportClientError(context, detail);
    if (element) markDegraded(element, id);
    return fallback;
  }
}

/** Read `attr` off `element` as JSON; context auto-derived as `tag[attr]`. */
export function readJSONProp<T>(element: Element, attr: string, fallback: T): T {
  const host = element instanceof HTMLElement ? element : undefined;
  return parseJSONWithReport<T>(
    element.getAttribute(attr),
    fallback,
    `${element.localName}[${attr}]`,
    host,
  );
}
