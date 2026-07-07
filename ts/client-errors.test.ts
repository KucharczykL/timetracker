// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  __resetClientErrorState,
  parseJSONWithReport,
  readJSONProp,
  reportClientError,
} from "./client-errors.js";

describe("client-errors", () => {
  let toast: ReturnType<typeof vi.fn>;
  let fetchMock: ReturnType<typeof vi.fn>;

  // The module-level dedupe Set persists across tests in this file (a static
  // import can't be reset), so each test below uses a DISTINCT context key to
  // stay isolated — never rely on a per-test reset here.
  beforeEach(() => {
    vi.restoreAllMocks();
    toast = vi.fn();
    (window as unknown as { toast: typeof toast }).toast = toast;
    fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("crypto", { randomUUID: () => "abcd1234-0000-0000-0000-000000000000" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("valid JSON parses through with no report", async () => {
    const value = parseJSONWithReport('[{"id":"1"}]', [], "ctx");
    expect(value).toEqual([{ id: "1" }]);
    expect(toast).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("malformed JSON returns the fallback and reports once", async () => {
    const fallback: unknown[] = [];
    const value = parseJSONWithReport("{not json", fallback, "ctx-a");
    expect(value).toBe(fallback);
    expect(console.error).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/client-error/");
  });

  it("marks the element when one is supplied", () => {
    const element = document.createElement("div");
    parseJSONWithReport("{bad", [], "ctx-mark", element);
    expect(element.getAttribute("data-degraded")).toBe("json-parse");
    expect(element.className).toContain("ring-2");
    expect(element.className).toContain("ring-red-500");
    expect(element.getAttribute("title")).toContain("abcd1234");
  });

  it("skips the mark when no element is supplied", () => {
    // parseFieldMeta-style call: no element, still reports.
    parseJSONWithReport("{bad", null, "ctx-nomark");
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("dedupes a repeated context+detail (one toast, one POST)", () => {
    parseJSONWithReport("{bad", [], "ctx-dup");
    parseJSONWithReport("{bad", [], "ctx-dup");
    expect(toast).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reports distinct details under one context separately", () => {
    reportClientError("ctx-two", "first");
    reportClientError("ctx-two", "second");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("readJSONProp derives context from tag[attr]", () => {
    const element = document.createElement("search-select");
    element.setAttribute("data-included", "{bad");
    const value = readJSONProp(element, "data-included", []);
    expect(value).toEqual([]);
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.context).toBe("search-select[data-included]");
  });

  it("never throws when fetch rejects", () => {
    fetchMock.mockReturnValue(Promise.reject(new Error("network down")));
    expect(() => reportClientError("ctx-net", "x")).not.toThrow();
  });

  it("suppresses the toast when options.toast is false but still POSTs", () => {
    reportClientError("ctx-notoast", "detail", { toast: false });
    expect(toast).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("caps reports at 25 per page; the 26th is suppressed", () => {
    __resetClientErrorState();
    for (let index = 0; index < 25; index += 1) {
      reportClientError("ctx-cap", `detail-${index}`);
    }
    expect(fetchMock).toHaveBeenCalledTimes(25);
    reportClientError("ctx-cap", "detail-26");
    expect(fetchMock).toHaveBeenCalledTimes(25); // no 26th POST
  });

  it("a deduped repeat does not consume cap budget", () => {
    __resetClientErrorState();
    reportClientError("ctx-budget", "same");
    reportClientError("ctx-budget", "same"); // deduped, no increment
    for (let index = 0; index < 24; index += 1) {
      reportClientError("ctx-budget", `distinct-${index}`);
    }
    // 1 + 24 = 25 distinct reports, all under the cap.
    expect(fetchMock).toHaveBeenCalledTimes(25);
  });
});
