// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetClientErrorState } from "./client-errors.js";
import {
  buildDetail,
  installGlobalErrorHandler,
  safeStringify,
  shouldReport,
  type ErrorFields,
} from "./global-error-handler.js";

const base: ErrorFields = { message: "", filename: "", lineno: 0, colno: 0, stack: "" };

describe("global-error-handler pure helpers", () => {
  it("safeStringify handles Symbol without throwing", () => {
    expect(() => safeStringify(Symbol("x"))).not.toThrow();
    expect(safeStringify(Symbol("x"))).toBe("<unstringifiable rejection reason>");
  });

  it("safeStringify handles null/undefined via fallback", () => {
    expect(safeStringify(null)).toBe("null");
    expect(safeStringify(undefined)).toBe("undefined");
  });

  it("safeStringify uses name+message for error-like objects", () => {
    expect(safeStringify({ name: "TypeError", message: "boom" })).toBe("TypeError: boom");
  });

  it("safeStringify does not emit [object Object]", () => {
    expect(safeStringify({})).not.toBe("[object Object]");
  });

  it("shouldReport drops extension filenames", () => {
    expect(shouldReport({ ...base, message: "x", filename: "chrome-extension://abc/c.js" })).toBe(false);
    expect(shouldReport({ ...base, message: "x", filename: "moz-extension://abc/c.js" })).toBe(false);
  });

  it("shouldReport drops an extension URL in the stack frame even with a page filename", () => {
    expect(
      shouldReport({ ...base, message: "x", filename: "https://site/app.js", stack: "at f (chrome-extension://abc/c.js:1:1)" }),
    ).toBe(false);
  });

  it("shouldReport drops opaque cross-origin Script error", () => {
    expect(shouldReport({ ...base, message: "Script error.", filename: "", stack: "" })).toBe(false);
  });

  it("shouldReport keeps a same-origin error", () => {
    expect(shouldReport({ ...base, message: "boom", filename: "https://site/app.js", stack: "at f (https://site/app.js:2:3)" })).toBe(true);
  });

  it("shouldReport keeps an inline error (empty filename but has a stack)", () => {
    expect(shouldReport({ ...base, message: "boom", filename: "", stack: "at f (<anonymous>:1:1)" })).toBe(true);
  });

  it("buildDetail joins message, location, first frame", () => {
    const detail = buildDetail({
      message: "boom",
      filename: "https://site/app.js",
      lineno: 2,
      colno: 3,
      stack: "Error: boom\n    at f (https://site/app.js:2:3)",
    });
    expect(detail).toBe("boom @ https://site/app.js:2:3 | at f (https://site/app.js:2:3)");
  });

  it("buildDetail omits location when filename empty", () => {
    const detail = buildDetail({ ...base, message: "boom", stack: "at f (<anonymous>:1:1)" });
    expect(detail).toBe("boom | at f (<anonymous>:1:1)");
  });

  it("buildDetail keeps a Firefox-style first frame (line 0 is not the message)", () => {
    const detail = buildDetail({ ...base, message: "boom", stack: "f@https://site/app.js:2:3" });
    expect(detail).toBe("boom | f@https://site/app.js:2:3");
  });

  it("buildDetail caps a huge filename to 200 chars", () => {
    const detail = buildDetail({ ...base, message: "m", filename: "https://site/" + "a".repeat(500), lineno: 1, colno: 1 });
    expect(detail.length).toBeLessThanOrEqual(500);
    expect(detail).toContain("https://site/" + "a".repeat(180)); // 200-char slice present
  });

  it("buildDetail truncates the whole detail to 500 chars", () => {
    const detail = buildDetail({ ...base, message: "m".repeat(600) });
    expect(detail.length).toBe(500);
  });
});

describe("global-error-handler window integration", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let toast: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    __resetClientErrorState();
    vi.restoreAllMocks();
    toast = vi.fn();
    (window as unknown as { toast: typeof toast }).toast = toast;
    fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("crypto", { randomUUID: () => "abcd1234-0000-0000-0000-000000000000" });
    installGlobalErrorHandler(); // idempotent; registers once across the file
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reports an uncaught error once, log-only (no toast)", () => {
    window.dispatchEvent(
      new ErrorEvent("error", {
        message: "boom",
        filename: "https://site/app.js",
        lineno: 2,
        colno: 3,
        error: new Error("boom"),
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(toast).not.toHaveBeenCalled();
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.context).toBe("window.onerror");
    expect(body.detail).toContain("boom");
  });

  it("reports an unhandled rejection with a non-Error reason", () => {
    window.dispatchEvent(
      new PromiseRejectionEvent("unhandledrejection", {
        promise: Promise.reject("bad").catch(() => {}) as unknown as Promise<unknown>,
        reason: "bad",
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.context).toBe("unhandledrejection");
    expect(body.detail).toContain("bad");
  });

  it("does not report an extension-origin error", () => {
    window.dispatchEvent(
      new ErrorEvent("error", { message: "x", filename: "chrome-extension://abc/c.js", lineno: 1, colno: 1 }),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
