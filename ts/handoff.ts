/** What the tab's next load reads. */
import { reportClientError } from "./client-errors.js";

/** An element id. */
export type ElementId = string;

/** Finds the opener again after a load. */
export interface OpenerKey {
  readonly id: ElementId | null;
  readonly href: string | null;
}

type StorageKey = `handoff:${string}`;

const MESSAGES_KEY: StorageKey = "handoff:messages";
const OPENER_KEY: StorageKey = "handoff:opener";
/** Older, a hand-off missed its load. */
const HANDOFF_LIFETIME_MS = 60_000;

interface Stamped {
  readonly at: number;
  readonly value: unknown;
}

function report(detail: string): void {
  reportClientError("handoff", detail, { toast: false });
}

function isStamped(value: unknown): value is Stamped {
  const candidate = value as Stamped | null;
  return typeof candidate?.at === "number" && candidate !== null && "value" in candidate;
}

function isOpenerKey(value: unknown): value is OpenerKey {
  const candidate = value as OpenerKey | null;
  const textOrNull = (part: unknown): boolean => part === null || typeof part === "string";
  return candidate !== null && textOrNull(candidate.id) && textOrNull(candidate.href);
}

/** Throws on an unreadable entry. */
function peek(key: StorageKey): Stamped | null {
  const stored = sessionStorage.getItem(key);
  if (stored === null) return null;
  const value: unknown = JSON.parse(stored);
  if (!isStamped(value)) throw new Error(`unreadable ${key}: ${stored}`);
  return value;
}

function stash(key: StorageKey, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify({ at: Date.now(), value }));
  } catch (error) {
    report(String((error as Error)?.message ?? error));
  }
}

/** Fresh and well-formed, else null; clears it. */
function take<Value>(key: StorageKey, isValue: (value: unknown) => value is Value): Value | null {
  try {
    const stamped = peek(key);
    sessionStorage.removeItem(key);
    if (!stamped) return null;
    if (Date.now() - stamped.at > HANDOFF_LIFETIME_MS) {
      report(`dropped ${key} older than a minute`);
      return null;
    }
    if (!isValue(stamped.value)) throw new Error(`malformed ${key}`);
    return stamped.value;
  } catch (error) {
    sessionStorage.removeItem(key);
    report(String((error as Error)?.message ?? error));
    return null;
  }
}

function isMessageList(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

/** Appends to messages waiting already. */
export function handOffMessages(payloads: readonly unknown[]): void {
  if (payloads.length === 0) return;
  let earlier: unknown[] = [];
  try {
    const waiting = peek(MESSAGES_KEY)?.value;
    if (isMessageList(waiting)) earlier = waiting;
  } catch (error) {
    report(String((error as Error)?.message ?? error));
  }
  stash(MESSAGES_KEY, [...earlier, ...payloads]);
}

export function takeHandedOffMessages(): unknown[] {
  return take(MESSAGES_KEY, isMessageList) ?? [];
}

export function handOffOpener(opener: OpenerKey): void {
  stash(OPENER_KEY, opener);
}

export function takeHandedOffOpener(): OpenerKey | null {
  return take(OPENER_KEY, isOpenerKey);
}
