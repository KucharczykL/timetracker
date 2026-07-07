# Global Window Error Handler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route uncaught browser errors (`window` `error` + `unhandledrejection`) into the existing #232 client-error seam — log-only, rate-limited, noise-filtered.

**Architecture:** A new root-level TS module `ts/global-error-handler.ts` registers two `window` listeners that extract → noise-filter → build a payload → call the shared `reportClientError` with `{ toast: false }`. The seam (`ts/client-errors.ts`) gains an optional no-toast flag and a per-page hard cap. The module is loaded first in the `Page()` head (like `toast.ts`), not as a custom element.

**Tech Stack:** TypeScript (compiled by `tsc` to `games/static/js/dist/`), vitest (jsdom), Django (`common/layout.py` `Page()`), pnpm via Nix dev shell.

## Global Constraints

- **Run every command in the Nix dev shell:** prefix with `direnv exec .` (e.g. `direnv exec . make check`). A bare `make`/`pnpm`/`pytest` has no toolchain.
- **Module path → dist path:** `tsconfig.json` `rootDir: "ts"`, `outDir: "games/static/js/dist"`, subtree preserved. `ts/foo.ts` → `dist/foo.js`. The new module MUST live at `ts/global-error-handler.ts` (root) so it emits `dist/global-error-handler.js`. Do NOT put it under `ts/elements/`.
- **Handlers must never throw.** Every listener body is wrapped in a swallowing `try/catch`; a throw inside a `window` `error` listener re-fires the error event and re-enters the handler.
- **Complete-word variable names** (CLAUDE.md): `firstStackFrame`, `event`, `element` — never `frame`-as-`f`, `el`, `e`.
- **No toast for global errors** — the handler passes `{ toast: false }`. Log-only.
- **Hard cap = 25 reports/page**; dedup check precedes cap increment (a deduped repeat spends no budget); reports 1–25 POST, #26 is first suppressed.
- **`detail` ≤ 500 chars** client-side (`ClientErrorIn.detail` `max_length=500`, `games/api.py:497`); `filename` capped at 200 within it.
- **Test files** (`*.test.ts`) are emit-excluded by `tsconfig.json`, type-checked via `tsconfig.check.json`; both run under `make ts-check` inside `make check`.
- **Verification gate:** full `direnv exec . make check` green before done (lint + format + mypy + ts-check + vitest + entire pytest incl. e2e).

---

## Task 1: Seam — no-toast option, hard cap, test-reset export

Extend `ts/client-errors.ts` so an uncaught-error caller can report without a toast, the endpoint is bounded per page, and tests can reset module state.

**Files:**
- Modify: `ts/client-errors.ts`
- Test: `ts/client-errors.test.ts` (extend existing)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `reportClientError(context: string, detail: string, options?: { toast?: boolean }): string` — `toast` defaults `true`. Widened, backward-compatible.
  - `interface ReportOptions { toast?: boolean }` (exported).
  - `__resetClientErrorState(): void` — test-only; clears the dedup `Set` and zeroes the cap counter.

- [ ] **Step 1: Write the failing tests**

Append to `ts/client-errors.test.ts` (before the final closing `});` of the `describe`). Add `__resetClientErrorState` to the import on line 3:

```ts
import {
  __resetClientErrorState,
  parseJSONWithReport,
  readJSONProp,
  reportClientError,
} from "./client-errors.js";
```

New cases:

```ts
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `direnv exec . pnpm exec vitest run ts/client-errors.test.ts`
Expected: FAIL — `__resetClientErrorState` is not exported; the toast-option and cap cases fail.

- [ ] **Step 3: Implement the seam changes**

In `ts/client-errors.ts`:

Add below the `const reported = new Set<string>();` line (currently line 19):

```ts
const MAX_REPORTS_PER_PAGE = 25;
let reportCount = 0;

export interface ReportOptions {
  toast?: boolean;
}
```

Replace the whole `reportClientError` function (currently lines 27–49) with:

```ts
export function reportClientError(
  context: string,
  detail: string,
  options: ReportOptions = {},
): string {
  const { toast = true } = options;
  const id = errorId();
  const key = `${context}|${detail}`;
  if (reported.has(key)) return id;
  reported.add(key);

  reportCount += 1;
  if (reportCount > MAX_REPORTS_PER_PAGE) {
    // One line at the boundary, then silence: bound endpoint load, not page CPU.
    if (reportCount === MAX_REPORTS_PER_PAGE + 1) {
      console.error("client error reporting suppressed (cap reached)");
    }
    return id;
  }

  console.error(`client error [${id}] ${context}: ${detail}`);
  if (toast && typeof window !== "undefined") {
    window.toast?.(`Filter failed to load (error ${id}) — reload the page`, "error");
  }

  if (typeof fetch !== "undefined" && typeof document !== "undefined") {
    void fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
      body: JSON.stringify({ error_id: id, context, detail, url: location.href }),
    }).catch(() => {
      // Reporting must never break the page: swallow network/HTTP failure.
    });
  }

  return id;
}

/** Test-only: reset the module-level dedup Set and cap counter. Never called in production. */
export function __resetClientErrorState(): void {
  reported.clear();
  reportCount = 0;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `direnv exec . pnpm exec vitest run ts/client-errors.test.ts`
Expected: PASS — all pre-existing cases plus the three new ones.

- [ ] **Step 5: Commit**

```bash
git add ts/client-errors.ts ts/client-errors.test.ts
git commit -m "Seam: no-toast option + per-page cap + test reset (#328)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Global error handler module

The new listener module: `safeStringify`, `shouldReport`, `buildDetail`, the two handlers, idempotent install.

**Files:**
- Create: `ts/global-error-handler.ts`
- Test: `ts/global-error-handler.test.ts`

**Interfaces:**
- Consumes: `reportClientError(context, detail, { toast: false })` from Task 1 (`./client-errors.js`).
- Produces (all exported for tests):
  - `interface ErrorFields { message: string; filename: string; lineno: number; colno: number; stack: string }`
  - `safeStringify(reason: unknown): string`
  - `shouldReport(fields: ErrorFields): boolean`
  - `buildDetail(fields: ErrorFields): string`
  - `installGlobalErrorHandler(): void` (idempotent; called on import).

- [ ] **Step 1: Write the failing tests**

Create `ts/global-error-handler.test.ts`:

```ts
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `direnv exec . pnpm exec vitest run ts/global-error-handler.test.ts`
Expected: FAIL — `./global-error-handler.js` does not exist.

- [ ] **Step 3: Implement the module**

Create `ts/global-error-handler.ts`:

```ts
/**
 * Global uncaught-error net (issue #328). Registers window "error" +
 * "unhandledrejection" listeners that funnel uncaught failures into the shared
 * client-error seam, log-only (no toast). Page-global furniture loaded directly
 * by Page(), a sibling of toast.ts — not a custom element.
 *
 * Handlers must never throw: a throw inside a window "error" listener re-fires
 * the error event and re-enters this handler. Every listener body is wrapped in
 * a swallowing try/catch.
 */
import { reportClientError } from "./client-errors.js";

export interface ErrorFields {
  message: string;
  filename: string;
  lineno: number;
  colno: number;
  stack: string;
}

const EXTENSION_SCHEMES = [
  "chrome-extension://",
  "moz-extension://",
  "safari-extension://",
  "safari-web-extension://",
];

let installed = false;

/** Coerce an unhandledrejection reason into a message string without throwing. */
export function safeStringify(reason: unknown): string {
  if (
    reason &&
    typeof reason === "object" &&
    typeof (reason as { message?: unknown }).message === "string"
  ) {
    const name =
      typeof (reason as { name?: unknown }).name === "string"
        ? (reason as { name: string }).name
        : "Error";
    return `${name}: ${(reason as { message: string }).message}`;
  }
  try {
    const text = String(reason);
    return text || "<unstringifiable rejection reason>";
  } catch {
    return "<unstringifiable rejection reason>";
  }
}

/** First non-empty stack line, skipping a V8 leading message line (Firefox has none). */
function firstStackFrame(stack: string, message: string): string {
  const lines = stack
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) return "";
  if (message && lines[0].startsWith(message)) return lines[1] ?? "";
  return lines[0];
}

function inExtension(value: string): boolean {
  return EXTENSION_SCHEMES.some((scheme) => value.startsWith(scheme));
}

export function shouldReport(fields: ErrorFields): boolean {
  const frame = firstStackFrame(fields.stack, fields.message);
  if (inExtension(fields.filename) || inExtension(frame)) return false;
  if (fields.message.startsWith("Script error") && fields.filename === "" && fields.stack === "") {
    return false;
  }
  return true;
}

export function buildDetail(fields: ErrorFields): string {
  const parts: string[] = [fields.message];
  if (fields.filename) {
    const filename = fields.filename.slice(0, 200);
    parts.push(`@ ${filename}:${fields.lineno}:${fields.colno}`);
  }
  const frame = firstStackFrame(fields.stack, fields.message);
  if (frame) parts.push(`| ${frame}`);
  return parts.join(" ").slice(0, 500);
}

function report(context: string, fields: ErrorFields): void {
  if (!shouldReport(fields)) return;
  reportClientError(context, buildDetail(fields), { toast: false });
}

function onError(event: ErrorEvent): void {
  try {
    const target = event.target;
    if (target && target !== window && target instanceof HTMLElement) {
      // Resource-load error (fires on the element, seen thanks to capture:true).
      const url = target.getAttribute("src") ?? target.getAttribute("href") ?? "";
      report("window.onerror", {
        message: `resource load failed: <${target.localName}>`,
        filename: url,
        lineno: 0,
        colno: 0,
        stack: "",
      });
      return;
    }
    report("window.onerror", {
      message: event.message ?? "",
      filename: event.filename ?? "",
      lineno: event.lineno ?? 0,
      colno: event.colno ?? 0,
      stack: event.error?.stack ?? "",
    });
  } catch {
    // Never throw from an error listener (would re-enter via the error event).
  }
}

function onRejection(event: PromiseRejectionEvent): void {
  try {
    const reason = event.reason;
    const isError = reason instanceof Error;
    report("unhandledrejection", {
      message: isError ? reason.message : safeStringify(reason),
      filename: "",
      lineno: 0,
      colno: 0,
      stack: isError ? (reason.stack ?? "") : "",
    });
  } catch {
    // Never throw.
  }
}

export function installGlobalErrorHandler(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("error", onError, { capture: true });
  window.addEventListener("unhandledrejection", onRejection);
}

installGlobalErrorHandler();
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `direnv exec . pnpm exec vitest run ts/global-error-handler.test.ts`
Expected: PASS — all pure-helper and window-integration cases.

- [ ] **Step 5: Commit**

```bash
git add ts/global-error-handler.ts ts/global-error-handler.test.ts
git commit -m "Global window error/unhandledrejection handler (#328)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Wire into the page + full verification

Load the compiled module first in the `Page()` head so listeners register before vendor/dist scripts run, then prove the whole suite green.

**Files:**
- Modify: `common/layout.py` (head script list, currently line 526+)

**Interfaces:**
- Consumes: the compiled `games/static/js/dist/global-error-handler.js` from Task 2.
- Produces: nothing for later tasks (final task).

- [ ] **Step 1: Add the script to the head**

In `common/layout.py`, insert one line immediately **before** the existing `Script(src=static("js/htmx.min.js")),` (currently line 526), so the block reads:

```python
                        Script(src=static("js/dist/global-error-handler.js")),
                        Script(src=static("js/htmx.min.js")),
                        Script(src=static("js/flowbite.min.js")),
                        Script(src=static("js/dist/htmx-redirect-toast.js")),
                        Script(src=static("js/dist/toast.js")),
```

(First in the list — before vendor and other dist scripts — for earliest registration. No `defer`, matching its neighbors.)

- [ ] **Step 2: Compile TypeScript so dist is fresh**

Run: `direnv exec . make ts`
Expected: no errors; `games/static/js/dist/global-error-handler.js` now exists.

Verify: `ls games/static/js/dist/global-error-handler.js`
Expected: the file is listed (confirms the root-level path mapping is correct).

- [ ] **Step 3: Confirm the page serves the script tag**

Run: `direnv exec . uv run pytest tests/test_rendered_pages.py -q`
Expected: PASS (existing page-render tests still green with the added head script).

- [ ] **Step 4: Full verification gate**

Run: `direnv exec . make check`
Expected: green — ruff lint + format-check, mypy, ts-check (incl. both new `.test.ts` type-checked via `tsconfig.check.json`), vitest (new suites pass), entire pytest incl. e2e.

- [ ] **Step 5: Commit**

```bash
git add common/layout.py
git commit -m "Load global error handler on every page (#328)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed)

**Spec coverage:**
- Decision 1 (no toast) → Task 1 `{ toast: false }` option + Task 2 `report()` passes it; test asserts no toast.
- Decision 2 (dedup + 25 cap) → Task 1 cap logic + two cap tests.
- Decision 3 (noise filter: extension in filename OR stack, cross-origin) → Task 2 `shouldReport` + tests.
- Decision 4 (message + source + first frame payload, 500 cap, filename 200 cap) → Task 2 `buildDetail` + tests.
- Never-throw / safeStringify → Task 2 try/catch handlers + `safeStringify` + Symbol test.
- V8/Firefox stack line-0 handling → Task 2 `firstStackFrame` + Firefox-style test.
- `{ capture: true }` resource-load errors → Task 2 `onError` resource branch.
- Root module path → Global Constraints + Task 2 file path + Task 3 `ls` verification.
- Loading first in head → Task 3 Step 1.
- Test-only reset → Task 1 `__resetClientErrorState` used by Task 2 integration `beforeEach`.

**Placeholder scan:** none — every code step shows full code; every run step shows command + expected output.

**Type consistency:** `reportClientError(context, detail, options?)` and `ReportOptions` defined in Task 1, consumed with `{ toast: false }` in Task 2. `ErrorFields` shape identical across `shouldReport`/`buildDetail`/tests. `__resetClientErrorState` exported in Task 1, imported in Task 2 test. `installGlobalErrorHandler` name consistent between module and test.

**Out-of-scope items** (from spec) intentionally have no task: `stack_trace` field, Sentry, token-bucket, `rejectionhandled` tracking, double-handler dedup — all explicit non-goals.
