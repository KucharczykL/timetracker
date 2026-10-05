/** Messages a fetch consumed, for the next page. */
import { reportClientError } from "./client-errors.js";
import { normalizedUrl, type PageUrl } from "./elements/form-dialog/answer.js";

const STORAGE_KEY = "toast-handoff";
/** Older than this, a hand-off missed its page. */
const HANDOFF_LIFETIME_MS = 60_000;

interface HandOff {
  readonly target: PageUrl;
  readonly at: number;
  readonly messages: readonly unknown[];
}

function report(detail: string): void {
  reportClientError("toast-handoff", detail, { toast: false });
}

function isHandOff(value: unknown): value is HandOff {
  const candidate = value as HandOff | null;
  return (
    typeof candidate?.target === "string" &&
    typeof candidate.at === "number" &&
    Array.isArray(candidate.messages)
  );
}

function readStored(): HandOff | null {
  const stored = sessionStorage.getItem(STORAGE_KEY);
  if (stored === null) return null;
  const value: unknown = JSON.parse(stored);
  if (!isHandOff(value)) throw new Error(`unreadable hand-off: ${stored}`);
  return value;
}

/** For the page at `target`; appends to one waiting there. */
export function handOffMessages(payloads: readonly unknown[], target: string | URL): void {
  if (payloads.length === 0) return;
  try {
    const page = normalizedUrl(target);
    const waiting = readStored();
    const earlier = waiting?.target === page ? waiting.messages : [];
    const handOff: HandOff = { target: page, at: Date.now(), messages: [...earlier, ...payloads] };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(handOff));
  } catch (error) {
    report(String((error as Error)?.message ?? error));
  }
}

/** This page's messages; clears any hand-off. */
export function takeHandedOffMessages(): unknown[] {
  try {
    const waiting = readStored();
    sessionStorage.removeItem(STORAGE_KEY);
    if (!waiting) return [];
    if (waiting.target !== normalizedUrl(location.href)) {
      report(`dropped messages for ${waiting.target}`);
      return [];
    }
    if (Date.now() - waiting.at > HANDOFF_LIFETIME_MS) {
      report("dropped messages older than a minute");
      return [];
    }
    return [...waiting.messages];
  } catch (error) {
    sessionStorage.removeItem(STORAGE_KEY);
    report(String((error as Error)?.message ?? error));
    return [];
  }
}
