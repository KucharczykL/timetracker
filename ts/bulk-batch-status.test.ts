// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type BatchOut, BulkBatchCoordinator, PAGE_STALE } from "./bulk-batch-status.js";

const TOKEN = "01900000-0000-7000-8000-000000000001";

function batch(state: BatchOut["state"], overrides: Partial<BatchOut> = {}): BatchOut {
  const terminal = ["finished", "stopped", "failed"].includes(state);
  return {
    token: TOKEN,
    state,
    origin: "/tracker/session/list?page=2",
    toast: {
      id: `bulk-batch:${TOKEN}`,
      message: `Remove 2 sessions: ${state}.`,
      type: terminal ? "success" : "info",
      sticky: true,
      action: terminal
        ? { label: "Undo", url: `/tracker/bulk/undo/${TOKEN}/` }
        : { label: "Stop", url: `/tracker/bulk/batch/${TOKEN}/stop/` },
    },
    ...overrides,
  };
}

function configure(batches: BatchOut[]): void {
  document.documentElement.dataset.bulkBatches = JSON.stringify(batches);
  document.documentElement.dataset.bulkBatchesUrl = "/api/bulk/batches";
}

function answer(batches: BatchOut[]): Response {
  return { ok: true, json: async () => batches } as Response;
}

let coordinator: BulkBatchCoordinator | null = null;
const toast = vi.fn();
const fetchMock = vi.fn();

function start(): BulkBatchCoordinator {
  coordinator = new BulkBatchCoordinator();
  return coordinator;
}

beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.clear();
  window.history.replaceState(null, "", "/tracker/session/list");
  window.toast = toast;
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  coordinator?.destroy();
  coordinator = null;
  toast.mockReset();
  fetchMock.mockReset();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  delete document.documentElement.dataset.bulkBatches;
  delete document.documentElement.dataset.bulkBatchesUrl;
});

describe("BulkBatchCoordinator", () => {
  it("shows each batch's toast, sticky", () => {
    configure([batch("running")]);
    start();
    expect(toast).toHaveBeenCalledWith("Remove 2 sessions: running.", "info", {
      id: `bulk-batch:${TOKEN}`,
      duration: null,
      action: { label: "Stop", url: `/tracker/bulk/batch/${TOKEN}/stop/` },
    });
  });

  it("keeps a non-sticky toast's own timer", () => {
    configure([batch("finished", {
      toast: { ...batch("finished").toast, sticky: false, action: undefined },
    })]);
    start();
    expect(toast.mock.calls[0][2].duration).toBeUndefined();
  });

  it("polls while one runs and sends a toast again only on change", async () => {
    configure([batch("running")]);
    fetchMock.mockResolvedValue(answer([batch("running")]));
    start();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/bulk/batches?tokens=${TOKEN}`,
      expect.anything(),
    );
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("fires page:stale once when a batch from this page ends", async () => {
    configure([batch("running")]);
    fetchMock.mockResolvedValue(answer([batch("finished")]));
    const stale = vi.fn();
    document.addEventListener(PAGE_STALE, stale);
    start();
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.advanceTimersByTimeAsync(4_000);
    document.removeEventListener(PAGE_STALE, stale);
    expect(stale).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledTimes(2);
  });

  it("leaves another page alone", async () => {
    configure([batch("running", { origin: "/tracker/game/list" })]);
    fetchMock.mockResolvedValue(answer([batch("finished", { origin: "/tracker/game/list" })]));
    const stale = vi.fn();
    document.addEventListener(PAGE_STALE, stale);
    start();
    await vi.advanceTimersByTimeAsync(2_000);
    document.removeEventListener(PAGE_STALE, stale);
    expect(stale).not.toHaveBeenCalled();
  });

  it("refreshes nothing for a batch that ended before the page", () => {
    configure([batch("finished")]);
    const stale = vi.fn();
    document.addEventListener(PAGE_STALE, stale);
    start();
    document.removeEventListener(PAGE_STALE, stale);
    expect(stale).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("remembers a running toast's dismissal", () => {
    configure([batch("running")]);
    start();
    window.dispatchEvent(
      new CustomEvent("toast-dismissed", { detail: { id: `bulk-batch:${TOKEN}` } }),
    );
    coordinator!.destroy();
    toast.mockReset();
    start();
    expect(toast).not.toHaveBeenCalled();
  });

  it("announces a dismissed end", () => {
    document.cookie = "csrftoken=secret";
    configure([batch("finished")]);
    fetchMock.mockResolvedValue({ ok: true } as Response);
    start();
    window.dispatchEvent(
      new CustomEvent("toast-dismissed", { detail: { id: `bulk-batch:${TOKEN}` } }),
    );
    expect(fetchMock).toHaveBeenCalledWith(`/api/bulk/batches/${TOKEN}/announced`, {
      method: "POST",
      headers: { "X-CSRFToken": "secret" },
    });
  });
});
