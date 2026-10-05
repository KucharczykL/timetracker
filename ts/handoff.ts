/** What the tab's next load reads. */
import { reportClientError } from "./client-errors.js";
import type { ElementId } from "./elements/form-dialog/rewrite.js";
import type { ToastPayload } from "./generated/form-dialog.js";

/** The `href` attribute as written. */
export type LinkHref = string;

/** Finds the opener again after a load. */
export interface OpenerKey {
  readonly id: ElementId | null;
  readonly href: LinkHref | null;
}

type StorageKey = `handoff:${string}`;
type EpochMilliseconds = number;

const MESSAGES_KEY: StorageKey = "handoff:messages";
const OPENER_KEY: StorageKey = "handoff:opener";
/** Older, a hand-off missed its load. */
const HANDOFF_LIFETIME_MS = 60_000;

interface Stamped {
  readonly at: EpochMilliseconds;
  readonly value: unknown;
}

function report(detail: string): void {
  reportClientError("handoff", detail, { toast: false });
}

function messageOf(error: unknown): string {
  return String((error as Error)?.message ?? error);
}

function isStamped(value: unknown): value is Stamped {
  const candidate = value as Stamped | null;
  return candidate !== null && typeof candidate?.at === "number" && "value" in candidate;
}

function isOpenerKey(value: unknown): value is OpenerKey {
  const candidate = value as OpenerKey | null;
  const textOrNull = (part: unknown): boolean => part === null || typeof part === "string";
  return candidate !== null && textOrNull(candidate.id) && textOrNull(candidate.href);
}

function isMessageList(value: unknown): value is unknown[] {
  return Array.isArray(value);
}

function isFresh(stamped: Stamped): boolean {
  return Date.now() - stamped.at <= HANDOFF_LIFETIME_MS;
}

/** Throws on an unreadable entry. */
function peek(key: StorageKey): Stamped | null {
  const stored = sessionStorage.getItem(key);
  if (stored === null) return null;
  const value: unknown = JSON.parse(stored);
  if (!isStamped(value)) throw new Error(`unreadable ${key}: ${stored}`);
  return value;
}

/** Blocked storage throws on every touch. */
function forget(key: StorageKey): void {
  try {
    sessionStorage.removeItem(key);
  } catch (error) {
    report(messageOf(error));
  }
}

function stash(key: StorageKey, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify({ at: Date.now(), value }));
  } catch (error) {
    report(messageOf(error));
  }
}

/** Fresh and well-formed, else null; clears it. */
function take<Value>(key: StorageKey, isValue: (value: unknown) => value is Value): Value | null {
  let stamped: Stamped | null;
  try {
    stamped = peek(key);
  } catch (error) {
    report(messageOf(error));
    stamped = null;
  }
  forget(key);
  if (!stamped) return null;
  if (!isFresh(stamped)) {
    report(`dropped ${key} older than a minute`);
    return null;
  }
  if (!isValue(stamped.value)) {
    report(`malformed ${key}`);
    return null;
  }
  return stamped.value;
}

/** Appends to fresh messages waiting already. */
export function handOffMessages(payloads: readonly ToastPayload[]): void {
  if (payloads.length === 0) return;
  let earlier: unknown[] = [];
  try {
    const waiting = peek(MESSAGES_KEY);
    if (waiting && isFresh(waiting) && isMessageList(waiting.value)) earlier = waiting.value;
  } catch (error) {
    report(messageOf(error));
  }
  stash(MESSAGES_KEY, [...earlier, ...payloads]);
}

/** Unchecked: storage is a trust boundary. */
export function takeHandedOffMessages(): unknown[] {
  return take(MESSAGES_KEY, isMessageList) ?? [];
}

export function handOffOpener(opener: OpenerKey): void {
  stash(OPENER_KEY, opener);
}

export function takeHandedOffOpener(): OpenerKey | null {
  return take(OPENER_KEY, isOpenerKey);
}
