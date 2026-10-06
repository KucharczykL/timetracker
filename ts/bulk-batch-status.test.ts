// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  type BatchOut,
  BulkBatchCoordinator,
  isBatch,
} from "./bulk-batch-status.js";
import { PAGE_STALE } from "./elements/form-dialog/events.js";
import fixtures from "./bulk-batch-status.fixtures.json";

const reportClientError = vi.hoisted(() => vi.fn(() => "error-id"));
vi.mock("./client-errors.js", () => ({ reportClientError }));

const TOKEN = "01900000-0000-7000-8000-000000000001";
const STOP = { label: "Stop", url: `/tracker/bulk/batch/${TOKEN}/stop/` };
const UNDO = { label: "Undo", url: `/tracker/bulk/undo/${TOKEN}/` };

function batch(state: BatchOut["state"], overrides: Partial<BatchOut> = {}): BatchOut {
  const terminal = ["finished", "stopped", "failed"].includes(state);
  return {
    token: TOKEN,
    state,
    terminal,
    origin: "/tracker/session/list?page=2",
    toast: {
      id: `bulk-batch:${TOKEN}`,
      message: `Remove 2 sessions: ${state}.`,
      type: terminal ? "success" : "info",
      sticky: true,
      action: terminal ? UNDO : STOP,
    },
    ...overrides,
  };
}

function configure(batches: unknown): void {
  document.documentElement.dataset.bulkBatches = JSON.stringify(batches);
  document.documentElement.dataset.bulkBatchesUrl = "/api/bulk/batches";
}

function answer(batches: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => batches } as Response;
}

function dismiss(): void {
  window.dispatchEvent(
    new CustomEvent("toast-dismissed", { detail: { id: `bulk-batch:${TOKEN}` } }),
  );
}

let coordinator: BulkBatchCoordinator | null = null;
const toast = vi.fn();
const removeToast = vi.fn();
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
  window.removeToast = removeToast;
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  coordinator?.destroy();
  coordinator = null;
  toast.mockReset();
  removeToast.mockReset();
  fetchMock.mockReset();
  reportClientError.mockClear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  delete document.documentElement.dataset.bulkBatches;
  delete document.documentElement.dataset.bulkBatchesUrl;
});

describe("the server's shapes", () => {
  it("accepts every batch the server can send", () => {
    expect(fixtures.length).toBeGreaterThan(0);
    for (const fixture of fixtures as unknown[]) expect(isBatch(fixture)).toBe(true);
  });
});

describe("BulkBatchCoordinator", () => {
  it("shows each batch's toast, sticky", () => {
    configure([batch("running")]);
    start();
    expect(toast).toHaveBeenCalledWith("Remove 2 sessions: running.", "info", {
      id: `bulk-batch:${TOKEN}`,
      duration: null,
      action: STOP,
    });
  });

  it("logs and skips an unreadable batch", () => {
    configure([{ token: TOKEN }, batch("running")]);
    start();
    expect(console.error).toHaveBeenCalledWith("Unreadable bulk batch", { token: TOKEN });
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("survives page data that is no JSON", () => {
    document.documentElement.dataset.bulkBatches = "{";
    document.documentElement.dataset.bulkBatchesUrl = "/api/bulk/batches";
    start();
    expect(toast).not.toHaveBeenCalled();
  });

  it("announces an end whose toast keeps its timer", () => {
    const quiet = batch("finished");
    quiet.toast = { ...quiet.toast, sticky: false, action: undefined };
    configure([quiet]);
    fetchMock.mockResolvedValue({ ok: true } as Response);
    start();
    expect(toast.mock.calls[0][2].duration).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/bulk/batches/${TOKEN}/announced`,
      expect.objectContaining({ method: "POST" }),
    );
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

  it("keeps a dismissal from waiting through running", async () => {
    configure([batch("queued")]);
    fetchMock.mockResolvedValue(answer([batch("running")]));
    start();
    dismiss();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("shows the end after a dismissed running toast", async () => {
    configure([batch("running")]);
    fetchMock.mockResolvedValue(answer([batch("finished")]));
    start();
    dismiss();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(toast).toHaveBeenCalledTimes(2);
    expect(toast.mock.calls[1][2].action).toEqual(UNDO);
  });

  it("works with storage blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    configure([batch("running")]);
    start();
    dismiss();
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("announces a dismissed end", () => {
    document.cookie = "csrftoken=secret";
    configure([batch("finished")]);
    fetchMock.mockResolvedValue({ ok: true } as Response);
    start();
    dismiss();
    expect(fetchMock).toHaveBeenCalledWith(`/api/bulk/batches/${TOKEN}/announced`, {
      method: "POST",
      headers: { "X-CSRFToken": "secret" },
    });
  });

  it("forgets a batch the server no longer answers", async () => {
    configure([batch("running")]);
    fetchMock.mockResolvedValue(answer([]));
    start();
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(removeToast).toHaveBeenCalledWith(`bulk-batch:${TOKEN}`);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("backs off while polls fail, then says so", async () => {
    configure([batch("running")]);
    fetchMock.mockResolvedValue(answer(null, 500));
    start();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("Could not check"),
      "warning",
      expect.objectContaining({ duration: null }),
    );
  });

  it("stops polling when the session is gone", async () => {
    configure([batch("running")]);
    fetchMock.mockResolvedValue(answer(null, 403));
    start();
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenLastCalledWith(
      expect.stringContaining("Could not check"),
      "warning",
      expect.anything(),
    );
  });
});

describe("BulkBatchCoordinator on page:stale", () => {
  const OTHER = "01900000-0000-7000-8000-000000000002";
  const undoBatch = (state: BatchOut["state"]): BatchOut =>
    batch(state, {
      token: OTHER,
      toast: { ...batch(state).toast, id: `bulk-batch:${OTHER}`, message: `Undo: ${state}.` },
    });

  function stale(): void {
    document.dispatchEvent(new CustomEvent(PAGE_STALE));
  }

  function deferred(): { promise: Promise<Response>; resolve: (value: Response) => void } {
    let resolve!: (value: Response) => void;
    const promise = new Promise<Response>((done) => {
      resolve = done;
    });
    return { promise, resolve };
  }

  it("reads what a page carries, naming no token", async () => {
    configure([]);
    fetchMock.mockResolvedValue(answer([]));
    start();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/bulk/batches", expect.anything());
  });

  it("shows a batch it did not know, then follows it", async () => {
    configure([]);
    fetchMock.mockResolvedValueOnce(answer([undoBatch("queued")]));
    fetchMock.mockResolvedValueOnce(answer([undoBatch("finished")]));
    start();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(toast).toHaveBeenCalledWith("Undo: queued.", "info", expect.anything());
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/bulk/batches?tokens=${OTHER}`,
      expect.anything(),
    );
    expect(toast).toHaveBeenLastCalledWith("Undo: finished.", "success", expect.anything());
  });

  it("takes away the toast of a batch the server no longer shows", async () => {
    configure([batch("finished")]);
    fetchMock.mockResolvedValue(answer([undoBatch("queued")]));
    start();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(removeToast).toHaveBeenCalledWith(`bulk-batch:${TOKEN}`);
    expect(removeToast).toHaveBeenCalledTimes(1);
  });

  it("reads nothing for its own page:stale", async () => {
    configure([batch("running")]);
    fetchMock.mockResolvedValue(answer([batch("finished")]));
    const fired = vi.fn();
    document.addEventListener(PAGE_STALE, fired);
    start();
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.advanceTimersByTimeAsync(4_000);
    document.removeEventListener(PAGE_STALE, fired);
    expect(fired).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalledWith("/api/bulk/batches", expect.anything());
  });

  it("never steps a known end back to running", async () => {
    configure([batch("finished")]);
    fetchMock.mockResolvedValue(answer([batch("running")]));
    start();
    stale();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(toast).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("drops an answer a later reconcile overtook", async () => {
    configure([]);
    const first = deferred();
    fetchMock.mockReturnValueOnce(first.promise);
    fetchMock.mockResolvedValueOnce(answer([undoBatch("queued")]));
    fetchMock.mockResolvedValue(answer([undoBatch("running")]));
    start();
    stale();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    first.resolve(answer([]));
    await vi.advanceTimersByTimeAsync(0);
    expect(removeToast).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith("Undo: queued.", "info", expect.anything());
  });

  it("starts no second poll while one is out", async () => {
    configure([batch("running")]);
    const poll = deferred();
    fetchMock.mockReturnValueOnce(poll.promise);
    fetchMock.mockResolvedValueOnce(answer([batch("running")]));
    start();
    await vi.advanceTimersByTimeAsync(2_000);
    stale();
    await vi.advanceTimersByTimeAsync(4_000);
    const polls = fetchMock.mock.calls.filter(([url]) => String(url).includes("tokens="));
    expect(polls).toHaveLength(1);
    poll.resolve(answer([batch("running")]));
  });

  it.each([
    ["a server error", () => fetchMock.mockResolvedValue(answer(null, 500))],
    ["a network error", () => fetchMock.mockRejectedValue(new TypeError("offline"))],
    ["an answer that is no list", () => fetchMock.mockResolvedValue(answer({}))],
  ])("says nothing on %s, and reports it", async (_case, failing) => {
    configure([]);
    failing();
    start();
    for (let press = 0; press < 6; press += 1) stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(toast).not.toHaveBeenCalled();
    expect(reportClientError).toHaveBeenCalledWith(
      "bulk-batch-status[reconcile]",
      expect.any(String),
      { toast: false },
    );
  });

  it("counts a failed reconcile as no poll failure", async () => {
    configure([batch("running")]);
    fetchMock.mockResolvedValueOnce(answer(null, 500));
    fetchMock.mockResolvedValue(answer([batch("running")]));
    start();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/bulk/batches?tokens=${TOKEN}`,
      expect.anything(),
    );
  });

  it("warns when the session is gone", async () => {
    configure([]);
    fetchMock.mockResolvedValue(answer(null, 403));
    start();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("Could not check"),
      "warning",
      expect.objectContaining({ duration: null }),
    );
  });

  it("takes the warning away once a reconcile is answered", async () => {
    configure([]);
    fetchMock.mockResolvedValueOnce(answer(null, 403));
    fetchMock.mockResolvedValue(answer([]));
    start();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(removeToast).toHaveBeenCalledWith("bulk-batch:poll");
  });

  it("keeps a short-lived end to its own timer", async () => {
    const quiet = batch("finished");
    quiet.toast = { ...quiet.toast, sticky: false, action: undefined };
    configure([quiet]);
    fetchMock.mockResolvedValue(answer([]));
    start();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(removeToast).not.toHaveBeenCalled();
  });

  it("keeps a dismissed running batch hidden", async () => {
    configure([batch("running")]);
    fetchMock.mockResolvedValue(answer([batch("running", { toast: { ...batch("running").toast, message: "Remove 2 sessions: 1 of 2." } })]));
    start();
    dismiss();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("lets no late poll bring back what a reconcile forgot", async () => {
    configure([batch("running")]);
    const poll = deferred();
    fetchMock.mockReturnValueOnce(poll.promise);
    fetchMock.mockResolvedValueOnce(answer([]));
    start();
    await vi.advanceTimersByTimeAsync(2_000);
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(removeToast).toHaveBeenCalledWith(`bulk-batch:${TOKEN}`);
    poll.resolve(answer([batch("finished")]));
    await vi.advanceTimersByTimeAsync(0);
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("stops listening once destroyed", async () => {
    const removed = vi.spyOn(document, "removeEventListener");
    configure([]);
    const listening = start();
    listening.destroy();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(removed).toHaveBeenCalledWith(PAGE_STALE, expect.any(Function));
  });

  it("listens to nothing without a route", async () => {
    document.documentElement.dataset.bulkBatches = "[]";
    start();
    stale();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
