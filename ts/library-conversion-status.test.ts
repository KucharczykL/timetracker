// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LibraryConversionCoordinator } from "./library-conversion-status.js";

interface State {
  library_id: string;
  requested_version: number;
  requested_currency: string;
  published_version: number;
  published_currency: string;
  status: "pending" | "running" | "failed" | "complete";
  retry_at: string | null;
  last_error: string;
}

const running: State = {
  library_id: "library-one",
  requested_version: 4,
  requested_currency: "CZK",
  published_version: 3,
  published_currency: "EUR",
  status: "running",
  retry_at: null,
  last_error: "",
};

function configure(state: State): void {
  document.documentElement.dataset.libraryConversionState = JSON.stringify(state);
  document.documentElement.dataset.libraryConversionStatusUrl = "/api/conversion/status";
}

function response(state: State): Response {
  return { ok: true, json: async () => state } as Response;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-15T12:00:00Z"));
  sessionStorage.clear();
  for (const key of Object.keys(document.documentElement.dataset)) {
    delete document.documentElement.dataset[key];
  }
  window.toast = vi.fn();
  window.removeToast = vi.fn();
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("LibraryConversionCoordinator", () => {
  it("reconstructs running state on load and announces observed completion", async () => {
    configure(running);
    vi.mocked(fetch).mockResolvedValue(response({
      ...running,
      published_version: 4,
      published_currency: "CZK",
      status: "complete",
    }));

    const coordinator = new LibraryConversionCoordinator();
    expect(window.toast).toHaveBeenCalledWith(
      "Prices are being converted. Totals will update when conversion is complete.",
      "info",
      expect.objectContaining({ duration: null }),
    );

    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetch).toHaveBeenCalledWith(
      "/api/conversion/status",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
    expect(window.removeToast).toHaveBeenCalled();
    expect(window.toast).toHaveBeenLastCalledWith(
      "Prices converted. Totals are now up to date.",
      "success",
    );
    coordinator.destroy();
  });

  it("never replays historical success in a tab that saw only complete state", () => {
    configure({
      ...running,
      published_version: 4,
      published_currency: "CZK",
      status: "complete",
    });

    const coordinator = new LibraryConversionCoordinator();
    expect(window.toast).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    coordinator.destroy();
  });

  it("persists same-tab dismissal across navigation without stopping polling", async () => {
    configure(running);
    vi.mocked(fetch).mockResolvedValue(response({
      ...running,
      published_version: 4,
      status: "complete",
    }));
    const first = new LibraryConversionCoordinator();
    const stableId = vi.mocked(window.toast).mock.calls[0][2]?.id as string;
    window.dispatchEvent(new CustomEvent("toast-dismissed", {
      detail: { id: stableId },
    }));
    expect(sessionStorage.getItem(
      "timetracker:conversion-dismissed:library-one:4:running",
    )).toBe("1");
    first.destroy();

    vi.mocked(window.toast).mockClear();
    const afterNavigation = new LibraryConversionCoordinator();
    expect(window.toast).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(window.toast).toHaveBeenCalledWith(
      "Prices converted. Totals are now up to date.",
      "success",
    );
    afterNavigation.destroy();
  });

  it("uses tab-local dismissal and a later version bypasses it", () => {
    configure(running);
    const first = new LibraryConversionCoordinator();
    const stableId = vi.mocked(window.toast).mock.calls[0][2]?.id as string;
    window.dispatchEvent(new CustomEvent("toast-dismissed", {
      detail: { id: stableId },
    }));
    first.destroy();

    vi.mocked(window.toast).mockClear();
    configure({ ...running, requested_version: 5 });
    const later = new LibraryConversionCoordinator();
    expect(window.toast).toHaveBeenCalledWith(
      expect.stringContaining("being converted"),
      "info",
      expect.objectContaining({ id: stableId }),
    );
    later.destroy();

    sessionStorage.clear();
    vi.mocked(window.toast).mockClear();
    configure(running);
    const otherTab = new LibraryConversionCoordinator();
    expect(window.toast).toHaveBeenCalled();
    otherTab.destroy();
  });

  it("keeps failure persistent, waits for retry_at, then exposes retry phase", async () => {
    const failed: State = {
      ...running,
      status: "failed",
      retry_at: "2026-08-15T12:01:00Z",
      last_error: "rate unavailable",
    };
    configure(failed);
    vi.mocked(fetch).mockResolvedValue(response({
      ...failed,
      status: "running",
    }));

    const coordinator = new LibraryConversionCoordinator();
    expect(window.toast).toHaveBeenCalledWith(
      "Prices couldn't be converted. Existing totals are still available. We'll retry automatically.",
      "error",
      expect.objectContaining({ duration: null, id: "library-conversion:library-one" }),
    );
    await vi.advanceTimersByTimeAsync(59_999);
    expect(fetch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(window.toast).toHaveBeenLastCalledWith(
      expect.stringContaining("being converted"),
      "info",
      expect.objectContaining({ duration: null, id: "library-conversion:library-one" }),
    );
    coordinator.destroy();
  });

  it("replaces running with failure using one stable toast id", async () => {
    configure(running);
    vi.mocked(fetch).mockResolvedValue(response({
      ...running,
      status: "failed",
      retry_at: "2026-08-15T12:15:00Z",
      last_error: "rate unavailable",
    }));
    const coordinator = new LibraryConversionCoordinator();
    const stableId = vi.mocked(window.toast).mock.calls[0][2]?.id;

    await vi.advanceTimersByTimeAsync(2_000);

    expect(window.toast).toHaveBeenLastCalledWith(
      "Prices couldn't be converted. Existing totals are still available. We'll retry automatically.",
      "error",
      { id: stableId, duration: null },
    );
    expect(window.removeToast).not.toHaveBeenCalledWith(stableId);
    coordinator.destroy();
  });
});
