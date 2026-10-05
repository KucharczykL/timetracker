/** Messages a fetch consumed, for the next page. */
import { reportClientError } from "./client-errors.js";

const STORAGE_KEY = "toast-handoff";

function report(error: unknown): void {
  reportClientError("toast-handoff", String((error as Error)?.message ?? error), {
    toast: false,
  });
}

/** Appends to any not yet taken. */
export function handOffMessages(payloads: readonly unknown[]): void {
  if (payloads.length === 0) return;
  try {
    const waiting: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "[]");
    const earlier = Array.isArray(waiting) ? waiting : [];
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...earlier, ...payloads]));
  } catch (error) {
    report(error);
  }
}

/** Reads and clears the handed-off messages. */
export function takeHandedOffMessages(): unknown[] {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored === null) return [];
    sessionStorage.removeItem(STORAGE_KEY);
    const payloads: unknown = JSON.parse(stored);
    return Array.isArray(payloads) ? payloads : [payloads];
  } catch (error) {
    report(error);
    return [];
  }
}
