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
