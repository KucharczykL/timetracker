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
const DEGRADED_CLASSES = "ring-2 ring-red-500";

// One report + one toast per distinct failure per page load.
const reported = new Set<string>();

function errorId(): string {
  return crypto.randomUUID().slice(0, 8);
}

/** Log a browser-side error to the server + console, deduped, best-effort toast.
 *  Returns the generated error id. Never throws. */
export function reportClientError(context: string, detail: string): string {
  const id = errorId();
  const key = `${context}|${detail}`;
  if (reported.has(key)) return id;
  reported.add(key);

  console.error(`client error [${id}] ${context}: ${detail}`);
  if (typeof window !== "undefined") {
    window.toast?.(`Filter failed to load (error ${id}) — reload the page`, "error");
  }

  if (typeof fetch !== "undefined" && typeof document !== "undefined") {
    void fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
      body: JSON.stringify({ error_id: id, context, detail, url: location.href }),
    }).catch(() => {
      // Reporting must never break the page: swallow network/HTTP failure.
    });
  }

  return id;
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
