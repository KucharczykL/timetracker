/** Background bulk batches, as toasts. */
import { getCsrfToken } from "./csrf.js";
import type { ToastAction, ToastType } from "./elements/toast-stack.js";

const BATCH_STATES = ["queued", "running", "finished", "stopped", "failed"] as const;
const TOAST_TYPES: readonly ToastType[] = ["success", "error", "info", "warning", "debug"];
type BatchState = (typeof BATCH_STATES)[number];

export interface BatchToast {
  id: string;
  message: string;
  type: ToastType;
  sticky: boolean;
  action?: ToastAction;
}

export interface BatchOut {
  token: string;
  state: BatchState;
  terminal: boolean;
  origin: string;
  toast: BatchToast;
}

const POLL_INTERVAL_MS = 2_000;
const MAX_POLL_INTERVAL_MS = 30_000;
/** Failures before the person is told. */
const FAILURES_TOLD = 5;
const TOAST_PREFIX = "bulk-batch:";
const POLL_FAILED_TOAST = `${TOAST_PREFIX}poll`;
const POLL_FAILED =
  "Could not check the progress of a bulk change. Reload the page to see it.";

/** The page under a batch changed. */
export const PAGE_STALE = "page:stale";

function isAction(value: unknown): value is ToastAction {
  if (!value || typeof value !== "object") return false;
  const action = value as Record<string, unknown>;
  return typeof action.label === "string" && typeof action.url === "string";
}

function isToast(value: unknown): value is BatchToast {
  if (!value || typeof value !== "object") return false;
  const toast = value as Record<string, unknown>;
  return typeof toast.id === "string"
    && typeof toast.message === "string"
    && (TOAST_TYPES as readonly unknown[]).includes(toast.type)
    && typeof toast.sticky === "boolean"
    && (toast.action === undefined || isAction(toast.action));
}

export function isBatch(value: unknown): value is BatchOut {
  if (!value || typeof value !== "object") return false;
  const batch = value as Record<string, unknown>;
  return typeof batch.token === "string"
    && (BATCH_STATES as readonly unknown[]).includes(batch.state)
    && typeof batch.terminal === "boolean"
    && typeof batch.origin === "string"
    && isToast(batch.toast);
}

/** Valid entries; each rejected one logged. */
function batchesIn(values: readonly unknown[]): BatchOut[] {
  return values.filter((value) => {
    if (isBatch(value)) return true;
    console.error("Unreadable bulk batch", value);
    return false;
  }) as BatchOut[];
}

function dismissalKey(token: string): string {
  return `timetracker:bulk-dismissed:${token}`;
}

/** Storage may be blocked; that is "not dismissed". */
function wasDismissed(token: string): boolean {
  try {
    return sessionStorage.getItem(dismissalKey(token)) !== null;
  } catch {
    return false;
  }
}

function rememberDismissal(token: string): void {
  try {
    sessionStorage.setItem(dismissalKey(token), "1");
  } catch (error) {
    console.warn("Could not remember a dismissed bulk toast", error);
  }
}

function onThisPage(origin: string): boolean {
  try {
    return new URL(origin, location.origin).pathname === location.pathname;
  } catch {
    return false;
  }
}

class PollRefused extends Error {}

export class BulkBatchCoordinator {
  private readonly batches = new Map<string, BatchOut>();
  /** What each toast last said. */
  private readonly sent = new Map<string, string>();
  private readonly statusUrl: string | null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private failures = 0;
  private destroyed = false;

  constructor() {
    const root = document.documentElement;
    this.statusUrl = root.dataset.bulkBatchesUrl ?? null;
    this.onToastDismissed = this.onToastDismissed.bind(this);
    window.addEventListener("toast-dismissed", this.onToastDismissed);
    for (const batch of this.read(root.dataset.bulkBatches)) this.apply(batch);
    this.scheduleNext();
  }

  destroy(): void {
    this.destroyed = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    window.removeEventListener("toast-dismissed", this.onToastDismissed);
  }

  private read(raw: string | undefined): BatchOut[] {
    if (!raw) return [];
    try {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) return batchesIn(parsed);
      console.error("Bulk batches are no list", parsed);
    } catch (error) {
      console.error("Invalid bulk batches", error);
    }
    return [];
  }

  private apply(batch: BatchOut): void {
    if (this.destroyed) return;
    const held = this.batches.get(batch.token);
    this.batches.set(batch.token, batch);
    if (held && !held.terminal && batch.terminal && onThisPage(batch.origin)) {
      document.dispatchEvent(new CustomEvent(PAGE_STALE));
    }
    this.show(batch);
  }

  private show(batch: BatchOut): void {
    const { toast } = batch;
    const said = JSON.stringify(toast);
    if (this.sent.get(batch.token) === said) return;
    if (!batch.terminal && wasDismissed(batch.token)) return;
    window.toast(toast.message, toast.type, {
      id: toast.id,
      duration: toast.sticky ? null : undefined,
      action: toast.action,
    });
    this.sent.set(batch.token, said);
    // Its timer sends no dismissal.
    if (batch.terminal && !toast.sticky) void this.announce(batch);
  }

  private forget(token: string): void {
    const batch = this.batches.get(token);
    this.batches.delete(token);
    this.sent.delete(token);
    if (batch) window.removeToast(batch.toast.id);
  }

  private onToastDismissed(event: Event): void {
    const id = (event as CustomEvent<{ id?: unknown }>).detail?.id;
    if (typeof id !== "string" || !id.startsWith(TOAST_PREFIX)) return;
    const batch = this.batches.get(id.slice(TOAST_PREFIX.length));
    if (!batch) return;
    if (batch.terminal) {
      void this.announce(batch);
    } else {
      rememberDismissal(batch.token);
    }
  }

  private async announce(batch: BatchOut): Promise<void> {
    if (!this.statusUrl) return;
    try {
      const response = await fetch(`${this.statusUrl}/${batch.token}/announced`, {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
      });
      if (!response.ok) throw new Error(`announce ${response.status}`);
    } catch (error) {
      console.error("Could not mark a bulk batch seen", error);
    }
  }

  private running(): string[] {
    return [...this.batches.values()]
      .filter((batch) => !batch.terminal)
      .map((batch) => batch.token);
  }

  private scheduleNext(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.destroyed || !this.statusUrl || this.running().length === 0) return;
    const delay = Math.min(POLL_INTERVAL_MS * 2 ** this.failures, MAX_POLL_INTERVAL_MS);
    this.timer = setTimeout(() => void this.poll(), delay);
  }

  private async poll(): Promise<void> {
    const tokens = this.running();
    if (this.destroyed || !this.statusUrl || tokens.length === 0) return;
    try {
      const query = new URLSearchParams({ tokens: tokens.join(",") });
      const response = await fetch(`${this.statusUrl}?${query}`, {
        headers: { Accept: "application/json" },
      });
      if (response.status === 401 || response.status === 403) {
        throw new PollRefused(`bulk batches ${response.status}`);
      }
      if (!response.ok) throw new Error(`bulk batches ${response.status}`);
      const value: unknown = await response.json();
      if (!Array.isArray(value)) throw new Error("bulk batches answer is no list");
      const answered = batchesIn(value);
      for (const batch of answered) this.apply(batch);
      const known = new Set(answered.map((batch) => batch.token));
      for (const token of tokens.filter((asked) => !known.has(asked))) {
        console.warn("A bulk batch is gone", token);
        this.forget(token);
      }
      this.failures = 0;
    } catch (error) {
      console.error("Could not refresh bulk batches", error);
      this.failures += 1;
      if (error instanceof PollRefused || this.failures === FAILURES_TOLD) {
        window.toast(POLL_FAILED, "warning", { id: POLL_FAILED_TOAST, duration: null });
      }
      if (error instanceof PollRefused) return;
    }
    this.scheduleNext();
  }
}

function startCoordinator(): void {
  new BulkBatchCoordinator();
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startCoordinator, { once: true });
} else {
  startCoordinator();
}
