# Client-Error Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the silent `console.warn` + empty-fallback pattern at every malformed-JSON-prop parse site in the filter widgets with a shared seam that logs a real error server-side (production-observable) and surfaces a best-effort user signal.

**Architecture:** A new Ninja endpoint `POST /api/client-error` writes one log line via a dedicated `client_errors` logger. A new browser module `ts/client-errors.ts` owns `reportClientError` (fire-and-forget POST + `console.error` + dedupe) and two JSON-parse helpers (`parseJSONWithReport`, `readJSONProp`) that report, best-effort toast, best-effort inline-mark, then return the caller's fallback. Every existing hand-rolled parse site migrates onto the seam.

**Tech Stack:** Django 6 + Django Ninja 1.6.2 (pydantic 2.13), TypeScript (ESM → `dist/`), vitest, pytest, Tailwind v4.

## Global Constraints

- Run every `make`/`pnpm`/`uv`/`pytest` command via `direnv exec .` (Nix shell). Never bare.
- Verification gate before done/push: full `direnv exec . make check` (lint + format-check + mypy + ts-check + vitest + entire pytest incl. `e2e/`) green.
- Signal reliability (do not overclaim): **server log = guaranteed**; **toast = best-effort** (listener registered in `alpine:init`, after a custom element's `connectedCallback` on initial load); **inline mark = best-effort** (may sit in a closed dropdown panel).
- New Django settings go through `config()` — N/A here (no new settings, only a LOGGING logger entry).
- Complete-word identifiers (`element` not `el`, `error` not `e`).
- ninja precedent for no-content: `response={204: None}` + `return Status(204, None)`.
- ninja/pydantic rejects over-length `Field(max_length=…)` with 422 before the handler.
- Tailwind v4 auto-scans `ts/` source; `dist/` is gitignored and NOT scanned. Runtime-applied classes MUST appear as verbatim literal strings in a `.ts` file, never concatenated. Run `make css` after adding one.
- Dedupe key is `context + "|" + detail`, never bare `context` (two same-tag elements would collide).

---

## File Structure

- **Create** `games/api.py` router `client_error_router` (in existing file) — the endpoint.
- **Modify** `timetracker/settings.py` — add `client_errors` logger.
- **Create** `ts/csrf.ts` — extract `getCsrfToken` (shared util; element modules must not own it).
- **Modify** `ts/elements/presets.ts` — import + re-export `getCsrfToken` from `../csrf.js`.
- **Create** `ts/client-errors.ts` — `reportClientError`, `parseJSONWithReport`, `readJSONProp`, dedupe.
- **Create** `ts/client-errors.test.ts` — vitest units.
- **Modify** `ts/elements/filter-widgets.ts` — delete `parseJSONAttr`, callers use `readJSONProp`.
- **Modify** `ts/elements/quick-filter-bar.ts` — `data-path` via `readJSONProp`; preset-load adds `reportClientError`.
- **Modify** `ts/elements/filter-group.ts` — models prop via `parseJSONWithReport`; filter prop + leaf-hydration catch → `reportClientError`.
- **Modify** `ts/elements/filter-summary.ts` — models prop via `parseJSONWithReport`.
- **Modify** `ts/elements/filter-tree/operations.ts` — `parseFieldMeta` via `parseJSONWithReport` (no element).
- **Create** `tests/test_client_error_api.py` — pytest endpoint units.
- **Modify** `tests/conftest.py` — add `capture_client_errors_logger` fixture.

---

## Task 1: Server endpoint + logger config

**Files:**
- Modify: `games/api.py` (add router near the other routers; register with `api.add_router`)
- Modify: `timetracker/settings.py:198-211` (LOGGING loggers block)
- Modify: `tests/conftest.py` (new fixture, mirrors `capture_games_logger`)
- Test: `tests/test_client_error_api.py` (create)

**Interfaces:**
- Produces: `POST /api/client-error` accepting JSON `{error_id, context, detail, url}`, returns 204; logs one `logging.getLogger("client_errors").error(...)` record with CRLF stripped from every client field.
- Produces (fixture): `capture_client_errors_logger` — context manager attaching `caplog` to the `client_errors` logger (which is `propagate=False`).

- [ ] **Step 1: Write the failing endpoint tests**

Create `tests/test_client_error_api.py`:

```python
"""Tests for the client-error report endpoint (POST /api/client-error).

The endpoint exists so a malformed-JSON-prop failure in the browser produces a
real server log line (issue #232) instead of an invisible console.warn.
"""

import logging

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


def _url() -> str:
    return "/api/client-error/"  # trailing slash: router `.post("/")`, matches /api/presets/


def _payload(**overrides) -> dict:
    payload = {
        "error_id": "abcd1234",
        "context": "filter-widgets[data-included]",
        "detail": "SyntaxError: Unexpected token",
        "url": "https://example.test/games/",
    }
    payload.update(overrides)
    return payload


def test_anonymous_is_rejected(db):
    anonymous = Client()
    response = anonymous.post(
        _url(), _payload(), content_type="application/json"
    )
    assert response.status_code == 401


def test_valid_report_returns_204_and_logs(auth_client, capture_client_errors_logger):
    with capture_client_errors_logger() as caplog:
        response = auth_client.post(
            _url(), _payload(), content_type="application/json"
        )
    assert response.status_code == 204
    records = [r for r in caplog.records if r.name == "client_errors"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "abcd1234" in message
    assert "filter-widgets[data-included]" in message


def test_crlf_is_stripped_from_log_line(auth_client, capture_client_errors_logger):
    with capture_client_errors_logger() as caplog:
        response = auth_client.post(
            _url(),
            _payload(detail="line one\r\nFORGED: fake entry"),
            content_type="application/json",
        )
    assert response.status_code == 204
    message = caplog.records[0].getMessage()
    assert "\n" not in message
    assert "\r" not in message


@pytest.mark.parametrize("field", ["error_id", "context", "detail", "url"])
def test_overlength_field_rejected_with_422(auth_client, field):
    response = auth_client.post(
        _url(), _payload(**{field: "x" * 1000}), content_type="application/json"
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Add the `capture_client_errors_logger` fixture**

In `tests/conftest.py`, directly after the existing `capture_games_logger` fixture, add:

```python
@pytest.fixture
def capture_client_errors_logger(caplog):
    """Context manager wiring ``caplog`` to the ``client_errors`` logger.

    ``client_errors`` sets ``propagate=False`` (timetracker/settings.py), so
    caplog's root handler never sees its records; attach caplog's handler
    directly for the block. Mirrors ``capture_games_logger``.
    """

    @contextlib.contextmanager
    def _capture():
        client_logger = logging.getLogger("client_errors")
        client_logger.addHandler(caplog.handler)
        caplog.set_level(logging.ERROR, logger="client_errors")
        try:
            yield caplog
        finally:
            client_logger.removeHandler(caplog.handler)

    return _capture
```

(`contextlib` and `logging` are already imported in `tests/conftest.py` for `capture_games_logger`.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `direnv exec . uv run pytest tests/test_client_error_api.py -v`
Expected: FAIL — 404 (endpoint absent) / fixture present but no route.

- [ ] **Step 4: Add the `client_errors` logger to settings**

In `timetracker/settings.py`, inside `LOGGING["loggers"]` (after the `games` entry), add:

```python
        "client_errors": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
```

- [ ] **Step 5: Implement the endpoint**

In `games/api.py`, add near the end (before/after `preset_router` block, following the existing router style). At the top the imports already include `from ninja import Field, ModelSchema, NinjaAPI, Router, Schema, Status`. Add `import logging` if not present (check top of file; add alongside the other stdlib imports).

```python
client_error_logger = logging.getLogger("client_errors")

client_error_router = Router()


class ClientErrorIn(Schema):
    error_id: str = Field(..., max_length=16)
    context: str = Field(..., max_length=200)
    detail: str = Field(..., max_length=500)
    url: str = Field(..., max_length=200)


def _one_line(value: str) -> str:
    """Collapse CR/LF so a client field cannot forge extra log entries."""
    return value.replace("\r", " ").replace("\n", " ")


@client_error_router.post("/", response={204: None})
def report_client_error(request, payload: ClientErrorIn):
    """Log a browser-side error so production observability can see it (#232).

    Auth + CSRF are inherited from ``NinjaAPI(auth=django_auth)``. Fields are
    length-capped by the schema (over-length -> 422) and CRLF-stripped so the
    single log line cannot be forged.
    """
    client_error_logger.error(
        "client error [%s] user=%s context=%s url=%s detail=%s",
        _one_line(payload.error_id),
        request.user,
        _one_line(payload.context),
        _one_line(payload.url),
        _one_line(payload.detail),
    )
    return Status(204, None)


api.add_router("/client-error", client_error_router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `direnv exec . uv run pytest tests/test_client_error_api.py -v`
Expected: PASS (all 7).

- [ ] **Step 7: Commit**

```bash
git add games/api.py timetracker/settings.py tests/conftest.py tests/test_client_error_api.py
git commit -m "Add POST /api/client-error endpoint + client_errors logger (#232)"
```

---

## Task 2: Extract shared CSRF helper

**Files:**
- Create: `ts/csrf.ts`
- Modify: `ts/elements/presets.ts:12-20` (remove definition, import + re-export)
- Test: existing `ts/elements/presets.test.ts` (unchanged — keeps importing `getCsrfToken` from `./presets.js` via the re-export)

**Interfaces:**
- Produces: `getCsrfToken(): string` exported from `ts/csrf.ts` (cookie first, hidden-input fallback, `""` + warn if absent).

- [ ] **Step 1: Create `ts/csrf.ts`**

```typescript
/**
 * CSRF-token read, shared by every module that POSTs to the Django API.
 * Prefers the `csrftoken` cookie, falls back to a rendered
 * `csrfmiddlewaretoken` hidden input.
 */
export function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  if (match) return decodeURIComponent(match[1]);
  const element = document.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]');
  if (element) return element.value;
  console.warn("csrf: token not found — authenticated POSTs will 403");
  return "";
}
```

- [ ] **Step 2: Rewire `presets.ts`**

In `ts/elements/presets.ts`, delete the `getCsrfToken` function body (lines 12-20) and replace with a re-export near the top imports:

```typescript
import { getCsrfToken } from "../csrf.js";

export { getCsrfToken };
```

(The two internal call sites at former lines 60/107 keep calling `getCsrfToken()` unchanged; `presets.test.ts` keeps importing it from `./presets.js`.)

- [ ] **Step 3: Type-check + run the preset tests**

Run: `direnv exec . make ts-check && direnv exec . pnpm vitest run ts/elements/presets.test.ts`
Expected: PASS (getCsrfToken tests still green through the re-export).

- [ ] **Step 4: Commit**

```bash
git add ts/csrf.ts ts/elements/presets.ts
git commit -m "Extract getCsrfToken into shared ts/csrf.ts (#232)"
```

---

## Task 3: Client seam module + tests

**Files:**
- Create: `ts/client-errors.ts`
- Test: `ts/client-errors.test.ts` (create)

**Interfaces:**
- Consumes: `getCsrfToken` from `ts/csrf.ts`; `window.toast(message, type)` (global).
- Produces:
  - `reportClientError(context: string, detail: string): string` — returns the 8-char error id; dedupes on `context + "|" + detail`; `console.error`s; fire-and-forget POST to `/api/client-error`; never throws.
  - `parseJSONWithReport<T>(raw: string | null | undefined, fallback: T, context: string, element?: HTMLElement): T`.
  - `readJSONProp<T>(element: Element, attr: string, fallback: T): T` — context = `${element.localName}[${attr}]`.

- [ ] **Step 1: Write the failing tests**

Create `ts/client-errors.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseJSONWithReport, readJSONProp, reportClientError } from "./client-errors.js";

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
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `direnv exec . pnpm vitest run ts/client-errors.test.ts`
Expected: FAIL — module `./client-errors.js` not found.

- [ ] **Step 3: Implement `ts/client-errors.ts`**

```typescript
/**
 * Client-error reporting seam (issue #232). One home for turning a browser-side
 * failure into (1) a guaranteed server log line, (2) a best-effort toast, and
 * (3) a best-effort inline mark, replacing the old silent console.warn pattern
 * scattered across the filter widgets.
 *
 * Signal reliability is deliberately tiered: the server POST always fires; the
 * toast may be lost on initial page load (its listener attaches during
 * alpine:init, after a custom element's connectedCallback); the ring mark may
 * sit inside a closed dropdown panel. The log line is the one guaranteed signal.
 */
import { getCsrfToken } from "./csrf.js";

const ENDPOINT = "/api/client-error/";
// The literal class string Tailwind's ts/ scan compiles (never concatenate).
const DEGRADED_CLASSES = "ring-2 ring-red-500";

// One report + one toast per distinct failure per page load.
const reported = new Set<string>();

function errorId(): string {
  return crypto.randomUUID().slice(0, 8);
}

/** Log a browser-side error to the server + console, deduped, best-effort toast.
 *  Returns the generated error id. Never throws. */
export function reportClientError(context: string, detail: string): string {
  const id = errorId();
  const key = `${context}|${detail}`;
  if (reported.has(key)) return id;
  reported.add(key);

  console.error(`client error [${id}] ${context}: ${detail}`);
  window.toast?.(`Filter failed to load (error ${id}) — reload the page`, "error");

  void fetch(ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": getCsrfToken() },
    body: JSON.stringify({ error_id: id, context, detail, url: location.href }),
  }).catch(() => {
    // Reporting must never break the page: swallow network/HTTP failure.
  });

  return id;
}

function markDegraded(element: HTMLElement, id: string): void {
  element.setAttribute("data-degraded", "json-parse");
  element.setAttribute("title", `Failed to load (error ${id})`);
  element.classList.add(...DEGRADED_CLASSES.split(" "));
}

/** Parse `raw` as JSON; on failure report + (best-effort) mark + return `fallback`. */
export function parseJSONWithReport<T>(
  raw: string | null | undefined,
  fallback: T,
  context: string,
  element?: HTMLElement,
): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch (error) {
    const detail = String((error as Error)?.message ?? error);
    const id = reportClientError(context, detail);
    if (element) markDegraded(element, id);
    return fallback;
  }
}

/** Read `attr` off `element` as JSON; context auto-derived as `tag[attr]`. */
export function readJSONProp<T>(element: Element, attr: string, fallback: T): T {
  const host = element instanceof HTMLElement ? element : undefined;
  return parseJSONWithReport<T>(
    element.getAttribute(attr),
    fallback,
    `${element.localName}[${attr}]`,
    host,
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `direnv exec . pnpm vitest run ts/client-errors.test.ts`
Expected: PASS (8).

- [ ] **Step 5: Commit**

```bash
git add ts/client-errors.ts ts/client-errors.test.ts
git commit -m "Add ts/client-errors seam: reportClientError + JSON parse helpers (#232)"
```

---

## Task 4: Migrate the parse sites

**Files:**
- Modify: `ts/elements/filter-widgets.ts` (delete `parseJSONAttr`; callers → `readJSONProp`)
- Modify: `ts/elements/quick-filter-bar.ts` (`data-path` → `readJSONProp`; preset-load adds `reportClientError`)
- Modify: `ts/elements/filter-group.ts` (models → `parseJSONWithReport`; filter prop + leaf hydration → `reportClientError`)
- Modify: `ts/elements/filter-summary.ts` (models → `parseJSONWithReport`)
- Modify: `ts/elements/filter-tree/operations.ts` (`parseFieldMeta` → `parseJSONWithReport`, no element)

**Interfaces:**
- Consumes: `readJSONProp`, `parseJSONWithReport`, `reportClientError` from `ts/client-errors.ts` (imported as `../client-errors.js` from `ts/elements/*`, `../../client-errors.js` from `ts/elements/filter-tree/*`).

- [ ] **Step 1: `filter-widgets.ts` — delete `parseJSONAttr`, migrate its two callers**

Add import at top:

```typescript
import { readJSONProp } from "../client-errors.js";
```

Delete the whole `parseJSONAttr` function (lines ~56-65). In `readSetWidget`, replace:

```typescript
  return buildSetCriterion(
    readJSONProp<PillEntry>(element, "data-included", []),
    readJSONProp<PillEntry>(element, "data-excluded", []),
    element.getAttribute("data-modifier"),
  );
```

- [ ] **Step 2: `quick-filter-bar.ts` — `data-path` + preset-load**

Update the import block (it currently pulls `parseJSONAttr` from `./filter-widgets.js` — remove that name):

```typescript
import {
  readLeafWidget,
  setupDeselectableRadios,
  setupModifierToggles,
} from "./filter-widgets.js";
import { readJSONProp, reportClientError } from "../client-errors.js";
```

In `serialize()`, replace the `data-path` read:

```typescript
        const path = readJSONProp<string>(widget, "data-path", []);
```

In the preset-load `catch (error)` block (keep its own toast + the `"preset load failed"` console substring the e2e guard asserts), add a report line before the existing `console.error`:

```typescript
    } catch (error) {
      reportClientError("quick-filter-bar[preset]", String(error));
      // Keep the "preset load failed" console substring (e2e crash guard).
      console.error("quick-filter-bar: preset load failed", error);
      window.toast("Preset is not a valid filter.", "error");
    }
```

- [ ] **Step 3: `filter-group.ts` — models, filter prop, leaf hydration**

Add import:

```typescript
import { parseJSONWithReport, reportClientError } from "../client-errors.js";
```

`parseModels` (~318): replace the `if (raw) { try … } catch …` block that fills `bundles` with:

```typescript
    const bundles = parseJSONWithReport<Record<string, ModelFieldBundleJson>>(
      raw,
      {},
      "filter-group[models]",
      this,
    );
```

(Remove the now-unused `let bundles … = {};` declaration; use the const above.)

Filter-prop seed (~286): the parse feeds `deserialize`, so keep one try but swap the log:

```typescript
      if (props.filter) {
        try {
          this.tree = deserialize(JSON.parse(props.filter), this.model, this.buildRegistry());
        } catch (error) {
          reportClientError("filter-group[filter]", String(error));
        }
      }
```

Leaf hydration (~1068): the caught value is a thrown `Error`, not JSON:

```typescript
        } catch (error) {
          // Fail open: a hydration bug on one leaf degrades to a blank widget.
          reportClientError("filter-group[leaf-hydration]", String((error as Error)?.message ?? error));
        }
```

- [ ] **Step 4: `filter-summary.ts` — models prop**

Add import:

```typescript
import { parseJSONWithReport } from "../client-errors.js";
```

`parseModels` (~70): replace the `let bundles … try/catch` with:

```typescript
    const bundles = parseJSONWithReport<Record<string, ModelBundleJson>>(
      raw,
      {},
      "filter-summary[models]",
      this,
    );
```

- [ ] **Step 5: `filter-tree/operations.ts` — `parseFieldMeta`**

Add import (two levels up):

```typescript
import { parseJSONWithReport } from "../../client-errors.js";
```

Replace the `parseFieldMeta` body:

```typescript
export function parseFieldMeta(raw: string): FilterFieldMeta | null {
  // No element to mark here (raw string only); report + toast still fire.
  return parseJSONWithReport<FilterFieldMeta | null>(raw, null, "filter-tree[field-meta]");
}
```

- [ ] **Step 6: Type-check + run the affected vitest suites**

Run: `direnv exec . make ts-check && direnv exec . pnpm vitest run ts/elements/quick-filter-bar.test.ts ts/elements/filter-group.test.ts ts/elements/filter-summary.test.ts ts/elements/filter-tree`
Expected: PASS. (The quick-filter-bar "invalid preset JSON toasts" test still passes — it asserts the toast + the `"preset load failed"` substring, both retained.)

- [ ] **Step 7: Build TS so e2e/local serving sees fresh output**

Run: `direnv exec . make ts`
Expected: no errors; `dist/` updated.

- [ ] **Step 8: Commit**

```bash
git add ts/elements/filter-widgets.ts ts/elements/quick-filter-bar.ts ts/elements/filter-group.ts ts/elements/filter-summary.ts ts/elements/filter-tree/operations.ts
git commit -m "Migrate filter-widget JSON parse sites onto the client-error seam (#232)"
```

---

## Task 5: Compile CSS, full gate, follow-up issues

**Files:** none (build + verify + issue-filing)

- [ ] **Step 1: Compile CSS so `ring-red-500` lands in `base.css`**

Run: `direnv exec . make css`
Then verify: `grep -c "ring-red-500" games/static/base.css`
Expected: ≥ 1 (was 0 before the literal existed).

- [ ] **Step 2: Full verification gate**

Run: `direnv exec . make check`
Expected: green (lint, format-check, mypy, ts-check, check-icons, vitest, full pytest incl. e2e).

- [ ] **Step 3: Commit the compiled CSS**

```bash
git add games/static/base.css
git commit -m "Compile base.css with ring-red-500 degraded-widget mark (#232)"
```

- [ ] **Step 4: File the two deferred follow-up issues**

```bash
gh issue create --repo KucharczykL/timetracker \
  --title "Global window.onerror/unhandledrejection → reportClientError" \
  --body "Extend the #232 client-error seam to a global handler (window.onerror + unhandledrejection → reportClientError). Needs its own decisions: rate-limiting so a render loop can't hammer /api/client-error, noise-filtering (browser-extension / third-party errors), and whether arbitrary errors should toast. Refs #232."

gh issue create --repo KucharczykL/timetracker \
  --title "Route toast.ts / htmx-redirect-toast JSON parse failures through the client-error seam" \
  --body "toast.ts and htmx-redirect-toast.ts JSON.parse sites were excluded from #232 because reporting-about-toast is circular (a failed toast parse can't rely on the toast). Decide a non-circular path (e.g. reportClientError with the toast suppressed there). Refs #232."
```

- [ ] **Step 5: Push + open PR**

```bash
git push -u origin issue-232-client-error-seam
gh pr create --repo KucharczykL/timetracker --fill
```

---

## Self-Review

- **Spec coverage:** §1 endpoint → Task 1; §1b logger → Task 1 Step 4; §2 client seam (`reportClientError`, CSRF extract, dedupe key) → Tasks 2+3; §3 helpers (`parseJSONWithReport` element-optional, `readJSONProp`, literal Tailwind class, toast wording) → Task 3; §4 migration table (all 7 rows, incl. `parseFieldMeta` no-element, quick-bar substring retention, leaf-hydration Error stringify) → Task 4; §5 tests (vitest + pytest incl. CRLF, 422, 401, caplog) → Tasks 1+3; §6 follow-ups → Task 5 Step 4. Signal-guarantees framing → module docstring + Global Constraints.
- **Placeholder scan:** none — every code step shows full code.
- **Type consistency:** `reportClientError(context, detail): string`, `parseJSONWithReport<T>(raw, fallback, context, element?)`, `readJSONProp<T>(element, attr, fallback)` used identically across Tasks 3 and 4. `ModelFieldBundleJson` (filter-group) vs `ModelBundleJson` (filter-summary) are the two files' own existing types — matched to each.
