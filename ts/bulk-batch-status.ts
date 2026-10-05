/** Bulk batches running in the background, as toasts. */
import { getCsrfToken } from "./csrf.js";
import type { ToastAction } from "./elements/toast-stack.js";

const BATCH_STATES = ["queued", "running", "finished", "stopped", "failed"] as const;
type BatchState = (typeof BATCH_STATES)[number];
const TERMINAL: readonly BatchState[] = ["finished", "stopped", "failed"];

export interface BatchToast {
  id: string;
  message: string;
  type: string;
  sticky: boolean;
  action?: ToastAction;
}

export interface BatchOut {
  token: string;
  state: BatchState;
  origin: string;
  toast: BatchToast;
}

const POLL_INTERVAL_MS = 2_000;
const TOAST_PREFIX = "bulk-batch:";

/** The page under a batch has changed. */
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
    && typeof toast.type === "string"
    && typeof toast.sticky === "boolean"
    && (toast.action === undefined || isAction(toast.action));
}

function isBatch(value: unknown): value is BatchOut {
  if (!value || typeof value !== "object") return false;
  const batch = value as Record<string, unknown>;
  return typeof batch.token === "string"
    && (BATCH_STATES as readonly string[]).includes(String(batch.state))
    && typeof batch.origin === "string"
    && isToast(batch.toast);
}

function isTerminal(batch: BatchOut): boolean {
  return TERMINAL.includes(batch.state);
}

function dismissalKey(batch: BatchOut): string {
  return `timetracker:bulk-dismissed:${batch.token}:${batch.state}`;
}

function onThisPage(origin: string): boolean {
  try {
    return new URL(origin, location.origin).pathname === location.pathname;
  } catch {
    return false;
  }
}

export class BulkBatchCoordinator {
  private readonly batches = new Map<string, BatchOut>();
  /** What each toast last said. */
  private readonly sent = new Map<string, string>();
  private readonly statusUrl: string | null;
  private timer: ReturnType<typeof setTimeout> | null = null;
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
      return Array.isArray(parsed) ? parsed.filter(isBatch) : [];
    } catch (error) {
      console.error("Invalid bulk batches", error);
      return [];
    }
  }

  private apply(batch: BatchOut): void {
    if (this.destroyed) return;
    const held = this.batches.get(batch.token);
    this.batches.set(batch.token, batch);
    if (held && !isTerminal(held) && isTerminal(batch) && onThisPage(batch.origin)) {
      document.dispatchEvent(new CustomEvent(PAGE_STALE));
    }
    this.show(batch);
  }

  private show(batch: BatchOut): void {
    const { toast } = batch;
    const said = JSON.stringify(toast);
    if (this.sent.get(batch.token) === said) return;
    if (!isTerminal(batch) && sessionStorage.getItem(dismissalKey(batch))) return;
    this.sent.set(batch.token, said);
    window.toast(toast.message, toast.type, {
      id: toast.id,
      duration: toast.sticky ? null : undefined,
      action: toast.action,
    });
  }

  private onToastDismissed(event: Event): void {
    const id = (event as CustomEvent<{ id?: unknown }>).detail?.id;
    if (typeof id !== "string" || !id.startsWith(TOAST_PREFIX)) return;
    const batch = this.batches.get(id.slice(TOAST_PREFIX.length));
    if (!batch) return;
    if (isTerminal(batch)) {
      void this.announce(batch);
    } else {
      sessionStorage.setItem(dismissalKey(batch), "1");
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
      .filter((batch) => !isTerminal(batch))
      .map((batch) => batch.token);
  }

  private scheduleNext(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.destroyed || !this.statusUrl || this.running().length === 0) return;
    this.timer = setTimeout(() => void this.poll(), POLL_INTERVAL_MS);
  }

  private async poll(): Promise<void> {
    const tokens = this.running();
    if (this.destroyed || !this.statusUrl || tokens.length === 0) return;
    try {
      const query = new URLSearchParams({ tokens: tokens.join(",") });
      const response = await fetch(`${this.statusUrl}?${query}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`bulk batches ${response.status}`);
      const value: unknown = await response.json();
      if (!Array.isArray(value)) throw new Error("invalid bulk batches response");
      for (const batch of value.filter(isBatch)) this.apply(batch);
    } catch (error) {
      console.error("Could not refresh bulk batches", error);
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
