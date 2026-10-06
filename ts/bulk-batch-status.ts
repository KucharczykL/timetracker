/** Background bulk batches, as toasts. */
import { reportClientError } from "./client-errors.js";
import { getCsrfToken } from "./csrf.js";
import { PAGE_STALE } from "./elements/form-dialog/events.js";
import type { ToastAction, ToastType } from "./elements/toast-stack.js";

const BATCH_STATES = ["queued", "running", "finished", "stopped", "failed"] as const;
const TOAST_TYPES: readonly ToastType[] = ["success", "error", "info", "warning", "debug"];
type BatchState = (typeof BATCH_STATES)[number];
type BatchToken = string;
/** Whether polling goes on. */
type PollEnd = "continue" | "stop";

export interface BatchToast {
  id: string;
  message: string;
  type: ToastType;
  sticky: boolean;
  action?: ToastAction;
}

export interface BatchOut {
  token: BatchToken;
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
  return values.filter((value): value is BatchOut => {
    if (isBatch(value)) return true;
    console.error("Unreadable bulk batch", value);
    return false;
  });
}

function dismissalKey(token: BatchToken): string {
  return `timetracker:bulk-dismissed:${token}`;
}

/** Storage may be blocked; that is "not dismissed". */
function wasDismissed(token: BatchToken): boolean {
  try {
    return sessionStorage.getItem(dismissalKey(token)) !== null;
  } catch {
    return false;
  }
}

function rememberDismissal(token: BatchToken): void {
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

function isRefusal(response: Response): boolean {
  return response.status === 401 || response.status === 403;
}

/** The batches a status URL answers. */
async function fetchBatches(url: string): Promise<BatchOut[]> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (isRefusal(response)) throw new PollRefused(`bulk batches ${response.status}`);
  if (!response.ok) throw new Error(`bulk batches ${response.status}`);
  const value: unknown = await response.json();
  if (!Array.isArray(value)) throw new Error("bulk batches answer is no list");
  return batchesIn(value);
}

/** A sticky end, or a running batch. */
function outlivesItsTimer(batch: BatchOut): boolean {
  return !batch.terminal || batch.toast.sticky;
}

export class BulkBatchCoordinator {
  private readonly batches = new Map<BatchToken, BatchOut>();
  /** What each toast last said. */
  private readonly sent = new Map<BatchToken, string>();
  private readonly statusUrl: string | null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private polling = false;
  private failures = 0;
  private toldPollFailed = false;
  private destroyed = false;
  /** Set while dispatching page:stale; dispatch is synchronous. */
  private staling = false;
  /** Counts reconciles; only the latest applies. */
  private reconciliation = 0;

  constructor() {
    const root = document.documentElement;
    this.statusUrl = root.dataset.bulkBatchesUrl ?? null;
    this.onToastDismissed = this.onToastDismissed.bind(this);
    this.onPageStale = this.onPageStale.bind(this);
    window.addEventListener("toast-dismissed", this.onToastDismissed);
    if (this.statusUrl) document.addEventListener(PAGE_STALE, this.onPageStale);
    for (const batch of this.read(root.dataset.bulkBatches)) this.apply(batch);
    this.scheduleNext();
  }

  destroy(): void {
    this.destroyed = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    window.removeEventListener("toast-dismissed", this.onToastDismissed);
    document.removeEventListener(PAGE_STALE, this.onPageStale);
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
    // A late answer never revives an end.
    if (held?.terminal && !batch.terminal) return;
    this.batches.set(batch.token, batch);
    if (held && !held.terminal && batch.terminal && onThisPage(batch.origin)) {
      this.staling = true;
      try {
        document.dispatchEvent(new CustomEvent(PAGE_STALE));
      } finally {
        this.staling = false;
      }
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

  private forget(token: BatchToken): void {
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

  private onPageStale(): void {
    if (this.staling) return;
    void this.reconcile();
  }

  /** Take what a page load would carry. */
  private async reconcile(): Promise<void> {
    if (this.destroyed || !this.statusUrl) return;
    this.reconciliation += 1;
    const asked = this.reconciliation;
    let answered: BatchOut[];
    try {
      answered = await fetchBatches(this.statusUrl);
    } catch (error) {
      if (error instanceof PollRefused) this.tellPollFailed();
      // The page's next load shows them.
      reportClientError("bulk-batch-status[reconcile]", String(error), { toast: false });
      return;
    }
    if (this.destroyed || asked !== this.reconciliation) return;
    // The session answers again.
    this.failures = 0;
    if (this.toldPollFailed) {
      this.toldPollFailed = false;
      window.removeToast(POLL_FAILED_TOAST);
    }
    for (const batch of answered) this.apply(batch);
    const shown = new Set(answered.map((batch) => batch.token));
    for (const [token, batch] of [...this.batches]) {
      if (shown.has(token) || !outlivesItsTimer(batch)) continue;
      console.warn("A bulk batch is gone", token);
      this.forget(token);
    }
    this.scheduleNext();
  }

  private tellPollFailed(): void {
    this.toldPollFailed = true;
    window.toast(POLL_FAILED, "warning", { id: POLL_FAILED_TOAST, duration: null });
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
      reportClientError("bulk-batch-status[announce]", String(error), { toast: false });
    }
  }

  private running(): BatchToken[] {
    return [...this.batches.values()]
      .filter((batch) => !batch.terminal)
      .map((batch) => batch.token);
  }

  private scheduleNext(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    // A poll in flight schedules the next.
    if (this.polling) return;
    if (this.destroyed || !this.statusUrl || this.running().length === 0) return;
    const delay = Math.min(POLL_INTERVAL_MS * 2 ** this.failures, MAX_POLL_INTERVAL_MS);
    this.timer = setTimeout(() => void this.poll(), delay);
  }

  private async poll(): Promise<void> {
    const tokens = this.running();
    if (this.destroyed || !this.statusUrl || tokens.length === 0) return;
    this.polling = true;
    let end: PollEnd;
    try {
      end = await this.pollOnce(tokens);
    } finally {
      this.polling = false;
    }
    if (end === "continue") this.scheduleNext();
  }

  private async pollOnce(tokens: BatchToken[]): Promise<PollEnd> {
    try {
      const query = new URLSearchParams({ tokens: tokens.join(",") });
      const fetched = await fetchBatches(`${this.statusUrl}?${query}`);
      // A reconcile forgot it meanwhile.
      const answered = fetched.filter((batch) => this.batches.has(batch.token));
      for (const batch of answered) this.apply(batch);
      const known = new Set(answered.map((batch) => batch.token));
      for (const token of tokens.filter((asked) => !known.has(asked) && this.batches.has(asked))) {
        console.warn("A bulk batch is gone", token);
        this.forget(token);
      }
      this.failures = 0;
    } catch (error) {
      console.error("Could not refresh bulk batches", error);
      this.failures += 1;
      if (error instanceof PollRefused || this.failures === FAILURES_TOLD) this.tellPollFailed();
      if (error instanceof PollRefused) return "stop";
    }
    return "continue";
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
