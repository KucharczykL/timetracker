// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "./toast.js";

function responseWithTrigger(): Response {
  return new Response("", {
    headers: {
      "HX-Trigger": JSON.stringify({
        "show-toast": { message: "Theme saved", type: "success" },
      }),
    },
  });
}

describe("fetchWithHtmxTriggers", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseWithTrigger()));
  });

  afterEach(() => vi.restoreAllMocks());

  it("continues to dispatch response triggers immediately by default", async () => {
    const listener = vi.fn();
    document.addEventListener("show-toast", listener, { once: true });

    await window.fetchWithHtmxTriggers("/settings");

    expect(listener).toHaveBeenCalledWith(expect.objectContaining({
      detail: { message: "Theme saved", type: "success" },
    }));
  });

  it("can defer response triggers until the caller validates the response", async () => {
    const listener = vi.fn();
    document.addEventListener("show-toast", listener);

    const response = await (window.fetchWithHtmxTriggers as any)(
      "/settings",
      {},
      "deferred",
    );

    expect(listener).not.toHaveBeenCalled();
    (window as any).dispatchHtmxTriggers(response);
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({
      detail: { message: "Theme saved", type: "success" },
    }));
    document.removeEventListener("show-toast", listener);
  });
});

function installToastStore(): any {
  const stores: Record<string, any> = {};
  vi.stubGlobal("Alpine", {
    store(name: string, value?: unknown) {
      if (value !== undefined) stores[name] = value;
      return stores[name];
    },
    data: vi.fn(),
  });
  document.dispatchEvent(new Event("alpine:init"));
  return stores.toasts;
}

describe("stable toast lifecycle", () => {
  beforeEach(() => vi.useFakeTimers());

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("replaces a stable string id and clears its previous timer", () => {
    const store = installToastStore();
    store.addToast("first", "info", { id: "conversion", duration: 5_000 });
    const firstTimer = store.toasts[0].timer;

    store.addToast("second", "warning", { id: "conversion", duration: null });

    expect(store.toasts).toHaveLength(1);
    expect(store.toasts[0]).toMatchObject({
      id: "conversion",
      message: "second",
      type: "warning",
      duration: null,
      visible: true,
      timer: null,
    });
    expect(firstTimer).not.toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("removes stable toasts whether visible or already dismissed", () => {
    const store = installToastStore();
    store.addToast("running", "info", { id: "job", duration: null });
    window.removeToast("job");
    expect(store.toasts).toEqual([]);

    store.addToast("again", "info", { id: "job", duration: null });
    store.dismissToast("job");
    expect(store.toasts[0].visible).toBe(false);
    window.removeToast("job");
    expect(store.toasts).toEqual([]);
  });

  it("uses defaults and resumes only the remaining duration after pause", () => {
    const store = installToastStore();
    store.addToast("notice", "info");
    const id = store.toasts[0].id;

    vi.advanceTimersByTime(2_000);
    store.clearToastTimer(id);
    vi.advanceTimersByTime(10_000);
    expect(store.toasts[0].visible).toBe(true);

    store.resumeToastTimer(id);
    vi.advanceTimersByTime(2_999);
    expect(store.toasts[0].visible).toBe(true);
    vi.advanceTimersByTime(1);
    expect(store.toasts[0].visible).toBe(false);
  });
});
