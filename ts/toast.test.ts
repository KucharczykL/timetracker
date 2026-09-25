// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "./toast.js";

function responseWithTrigger(): Response {
  return new Response("", {
    headers: {
      "X-Events": JSON.stringify({
        "show-toast": { message: "Theme saved", type: "success" },
      }),
    },
  });
}

describe("fetchWithEvents", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseWithTrigger()));
  });

  afterEach(() => vi.restoreAllMocks());

  it("continues to dispatch response triggers immediately by default", async () => {
    const listener = vi.fn();
    document.addEventListener("show-toast", listener, { once: true });

    await window.fetchWithEvents("/settings");

    expect(listener).toHaveBeenCalledWith(expect.objectContaining({
      detail: { message: "Theme saved", type: "success" },
    }));
  });

  it("can defer response triggers until the caller validates the response", async () => {
    const listener = vi.fn();
    document.addEventListener("show-toast", listener);

    const response = await (window.fetchWithEvents as any)(
      "/settings",
      {},
      "deferred",
    );

    expect(listener).not.toHaveBeenCalled();
    (window as any).dispatchResponseEvents(response);
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({
      detail: { message: "Theme saved", type: "success" },
    }));
    document.removeEventListener("show-toast", listener);
  });
});
