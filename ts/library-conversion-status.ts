type ConversionStatus = "pending" | "running" | "failed" | "complete";
type ConversionPhase = "running" | "retry" | "failure";

interface ConversionState {
  library_id: string;
  requested_version: number;
  requested_currency: string;
  published_version: number;
  published_currency: string;
  status: ConversionStatus;
  retry_at: string | null;
  last_error: string;
}

const POLL_INTERVAL_MS = 2_000;
const MAX_WAIT_CHUNK_MS = 60_000;
const RUNNING_MESSAGE =
  "Prices are being converted. Totals will update when conversion is complete.";
const SUCCESS_MESSAGE = "Prices converted. Totals are now up to date.";
const FAILURE_MESSAGE =
  "Prices couldn't be converted. Existing totals are still available. We'll retry automatically.";

function isState(value: unknown): value is ConversionState {
  if (!value || typeof value !== "object") return false;
  const state = value as Record<string, unknown>;
  return typeof state.library_id === "string"
    && Number.isInteger(state.requested_version)
    && typeof state.requested_currency === "string"
    && Number.isInteger(state.published_version)
    && typeof state.published_currency === "string"
    && ["pending", "running", "failed", "complete"].includes(String(state.status))
    && (state.retry_at === null || typeof state.retry_at === "string")
    && typeof state.last_error === "string";
}

function phaseFor(state: ConversionState): ConversionPhase | null {
  if (state.status === "failed") return "failure";
  if (state.status === "pending" || state.status === "running") {
    return state.retry_at ? "retry" : "running";
  }
  return null;
}

function toastId(state: ConversionState, _phase: ConversionPhase): string {
  return `library-conversion:${state.library_id}`;
}

function dismissalKey(state: ConversionState, phase: ConversionPhase): string {
  return `timetracker:conversion-dismissed:${state.library_id}:${state.requested_version}:${phase}`;
}

function observedVersionKey(state: ConversionState): string {
  return `timetracker:conversion-observed:${state.library_id}`;
}

export class LibraryConversionCoordinator {
  private state: ConversionState | null = null;
  private readonly statusUrl: string | null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;
  private activeToastId: string | null = null;

  constructor() {
    const root = document.documentElement;
    this.statusUrl = root.dataset.libraryConversionStatusUrl ?? null;
    const raw = root.dataset.libraryConversionState;
    if (raw && this.statusUrl) {
      try {
        const parsed: unknown = JSON.parse(raw);
        if (isState(parsed)) this.state = parsed;
      } catch (error) {
        console.error("Invalid library conversion state", error);
      }
    }
    this.onToastDismissed = this.onToastDismissed.bind(this);
    window.addEventListener("toast-dismissed", this.onToastDismissed);
    if (this.state) this.applyState(this.state);
  }

  destroy(): void {
    this.destroyed = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    window.removeEventListener("toast-dismissed", this.onToastDismissed);
  }

  private onToastDismissed(event: Event): void {
    const id = (event as CustomEvent<{ id?: unknown }>).detail?.id;
    if (typeof id !== "string" || id !== this.activeToastId || !this.state) return;
    const phase = phaseFor(this.state);
    if (phase) sessionStorage.setItem(dismissalKey(this.state, phase), "1");
  }

  private applyState(state: ConversionState): void {
    if (this.destroyed) return;
    this.state = state;
    const phase = phaseFor(state);
    if (phase) {
      sessionStorage.setItem(
        observedVersionKey(state), String(state.requested_version),
      );
      if (this.activeToastId && this.activeToastId !== toastId(state, phase)) {
        window.removeToast(this.activeToastId);
      }
      this.activeToastId = toastId(state, phase);
      if (!sessionStorage.getItem(dismissalKey(state, phase))) {
        window.toast(
          phase === "failure" ? FAILURE_MESSAGE : RUNNING_MESSAGE,
          phase === "failure" ? "error" : "info",
          { id: this.activeToastId, duration: null },
        );
      }
      this.scheduleNext(state);
      return;
    }

    if (this.activeToastId) window.removeToast(this.activeToastId);
    this.activeToastId = null;
    const observedKey = observedVersionKey(state);
    const observedVersion = sessionStorage.getItem(observedKey);
    const observedRequestedVersion = observedVersion === null
      ? null
      : Number(observedVersion);
    if (
      state.status === "complete"
      && state.published_version === state.requested_version
      && observedRequestedVersion !== null
      && Number.isSafeInteger(observedRequestedVersion)
      && observedRequestedVersion <= state.published_version
    ) {
      sessionStorage.removeItem(observedKey);
      window.toast(SUCCESS_MESSAGE, "success");
    } else if (state.status === "complete" && observedVersion !== null) {
      sessionStorage.removeItem(observedKey);
    }
  }

  private scheduleNext(state: ConversionState): void {
    if (this.timer) clearTimeout(this.timer);
    let delay = POLL_INTERVAL_MS;
    if (state.status === "failed" && state.retry_at) {
      const remaining = Date.parse(state.retry_at) - Date.now();
      delay = remaining > 0 ? remaining : POLL_INTERVAL_MS;
    }
    delay = Math.min(Math.max(delay, 0), MAX_WAIT_CHUNK_MS);
    this.timer = setTimeout(() => void this.poll(), delay);
  }

  private async poll(): Promise<void> {
    if (this.destroyed || !this.statusUrl || !this.state) return;
    if (this.state.status === "failed" && this.state.retry_at) {
      const remaining = Date.parse(this.state.retry_at) - Date.now();
      if (remaining > 0) {
        this.scheduleNext(this.state);
        return;
      }
    }
    try {
      const response = await fetch(this.statusUrl, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`conversion status ${response.status}`);
      const value: unknown = await response.json();
      if (!isState(value) || value.library_id !== this.state.library_id) {
        throw new Error("invalid conversion status response");
      }
      if (value.requested_version < this.state.requested_version) {
        this.scheduleNext(this.state);
        return;
      }
      this.applyState(value);
    } catch (error) {
      console.error("Could not refresh library conversion status", error);
      this.scheduleNext(this.state);
    }
  }
}

function startCoordinator(): void {
  new LibraryConversionCoordinator();
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startCoordinator, { once: true });
} else {
  startCoordinator();
}
