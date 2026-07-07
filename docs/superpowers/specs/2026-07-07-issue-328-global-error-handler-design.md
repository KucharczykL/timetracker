# Global window.onerror / unhandledrejection → reportClientError (issue #328)

Date: 2026-07-07
Issue: https://github.com/KucharczykL/timetracker/issues/328
Refs: #232 (the client-error seam this extends), PR #330 (the seam's merge — the
`client_errors` logger, `POST /api/client-error/`, and `ClientErrorIn` schema all
already landed there; this issue needs **no** server change).

## Problem

The #232 seam (`ts/client-errors.ts` → `POST /api/client-error/` → `client_errors`
logger) catches only the failures a widget explicitly routes through it
(malformed JSON props). An uncaught error anywhere else — a throw inside an event
handler, a rejected promise with no `.catch`, a TypeError in third-party JS —
still dies in the browser console, invisible to production observability.

#328 extends the seam to a page-global net: `window` `error` +
`unhandledrejection` listeners that funnel uncaught failures into the same
`reportClientError` sink. A global net has risks the per-widget seam never faced,
each an explicit design decision below: a render/error loop hammering the
endpoint, browser-extension / third-party noise drowning the signal, toast-spam
from non-actionable errors, and — because the handler itself reports — the danger
of the reporting path throwing and re-entering its own listener.

## Decisions (interview outcomes)

1. **Toast policy — no toast.** The global handler logs to server + console only.
   The seam's existing toast (`"Filter failed to load … reload the page"`) is
   filter-specific and wrong for an arbitrary uncaught error; most global errors
   are not user-actionable, and toasting on every extension/third-party error is
   noise. Toast stays exclusively on the per-widget callers that opt into it.
2. **Rate-limit — dedup + hard cap per page load.** Keep the seam's existing
   `context+"|"+detail` dedup `Set`, and add a hard ceiling of **25** distinct
   reports per page load. Past the ceiling, stop POSTing (one `"suppressed"`
   console line, no further network/toast). **This bounds endpoint load, not page
   CPU** — a synchronous throw-loop still hangs the page; the cap only stops us
   from *amplifying* it with network traffic. Dedup alone handles the common case
   (a loop throwing the *same* error collapses to one report); the cap is the
   backstop for a loop whose message text *varies* (distinct stack line numbers,
   an incrementing counter in the message) and so evades dedup.
3. **Noise filter — drop cross-origin + extension.** Skip reporting when the
   error originates in a browser-extension URL or is the opaque cross-origin
   case. The extension check inspects **both** `filename` **and** the first stack
   frame (extension throws often surface with a page `filename` but an extension
   URL in the stack), so it also covers `unhandledrejection` (no `filename`, but a
   `reason.stack`). Keep same-origin, inline, and eval errors.
4. **Payload — message + source:line:col + first stack frame.** Enough to
   diagnose without widening the API. Fits the existing `ClientErrorIn` schema
   unchanged.

## Architecture

### New module: `ts/global-error-handler.ts` (repo root, NOT `ts/elements/`)

Placed at the `ts/` root alongside `toast.ts` and `htmx-redirect-toast.ts` — its
true siblings: page-global furniture, **not** a custom element (no host tag, no
server-rendered markup), so the `register_element` / `gen_element_types` / Props
`TypedDict` machinery (CLAUDE.md) genuinely does not apply, and it is loaded
directly by `Page()`, never collected via `collect_media`.

Location matters for the build: `tsconfig.json` has `rootDir: "ts"`,
`outDir: "games/static/js/dist"`, preserving subtree structure. `ts/foo.ts` →
`dist/foo.js`; `ts/elements/foo.ts` → `dist/elements/foo.js`. Root placement gives
the load path `js/dist/global-error-handler.js`.

It exports an idempotent `installGlobalErrorHandler()` that registers the two
listeners once (guarded by a module-level `installed` flag), and calls it on
import. Off-browser (`typeof window === "undefined"`) the install call no-ops,
mirroring the seam's node-env guards, so a vitest node import is safe.

### Handlers — never throw

Both listeners wrap their entire body in `try { … } catch { /* swallow */ }`.
A throw inside a `window` `error` listener re-fires the `error` event and would
re-enter the handler — an infinite loop. The swallow is the architectural
enforcement of "handlers must never throw"; the stated guarantee is not left to
the reporting path being incidentally safe.

- **`error` (ErrorEvent):** read `message`, `filename`, `lineno`, `colno`,
  `error?.stack`. Registered with `{ capture: true }` so resource-load errors
  (a `<script src>` 404) — which fire on the element and do **not** bubble to
  `window` — are also seen; a same-origin bad asset is worth a log line.
- **`unhandledrejection` (PromiseRejectionEvent):** read `reason`. If `reason`
  is an `Error`, use its `message` + `stack`; otherwise derive a message via
  `safeStringify` (below). No `filename`, so location is omitted; the extension
  filter still applies via the stack.

Neither handler calls `preventDefault` — the browser's own console logging is
preserved.

### `safeStringify(reason)` (module-private)

`String(reason)` is **not** safe for all rejection reasons — `String(Symbol())`
throws `TypeError`, violating never-throw. And `String({})` → `"[object Object]"`
is useless. Rule:

- `reason instanceof Error` → handled by the caller (message + stack), not here.
- object with a string `message` → use `` `${reason.name ?? "Error"}: ${reason.message}` ``.
- else attempt `String(reason)` inside `try/catch`; on throw (Symbol) or empty,
  fall back to the literal `"<unstringifiable rejection reason>"`.

### Noise filter (module-private `shouldReport`)

Returns `false` (drop) when either holds:

- **Extension origin:** `filename` **or** the first stack frame starts with one
  of `chrome-extension://`, `moz-extension://`, `safari-extension://`,
  `safari-web-extension://`. (Checking the stack frame closes the case where an
  extension error carries a page `filename`, and gives rejections — which have no
  `filename` — a noise filter at all.)
- **Opaque cross-origin:** `message.startsWith("Script error")` (no dependence on
  the trailing period, which varies by engine) **and** `filename` is empty **and**
  there is no stack. The no-stack conjunction guards against false-dropping a
  legitimate same-origin inline throw that happens to be named `"Script error."`.

Everything else reports.

### Payload assembly (module-private `buildDetail`)

`context` is the literal `"window.onerror"` or `"unhandledrejection"`.

`detail` is the non-empty parts of
`` `${message} @ ${filename}:${lineno}:${colno} | ${firstStackFrame}` `` joined,
where:

- the `@ filename:lineno:colno` clause is omitted when `filename` is empty; the
  `filename` itself is capped at 200 chars (`.slice(0, 200)`) so a giant `data:`
  or query-laden URL cannot bury the message/frame;
- `firstStackFrame` is the first non-empty stack line, **skipping line 0 only when
  it starts with / equals the `message`** — V8/Chrome prefixes the stack with the
  message line, Firefox does not, so an unconditional "skip line 0" would drop a
  real frame on Firefox. Omitted when there is no stack;
- **message comes first**, then the whole string is truncated to **500** chars
  (`.slice(0, 500)`) to match `ClientErrorIn.detail`'s `max_length` (verified
  `games/api.py:497`) so a long stack never 422s. Message-first ordering means a
  mid-frame truncation is acceptable; a pathological >500-char message loses the
  location/frame, which is fine.

### Seam changes: `ts/client-errors.ts`

Three additive changes. The direct `reportClientError(...)` call sites today are
**three** (`quick-filter-bar.ts`, and two in `filter-group.ts`); the other seam
users go through the `parseJSONWithReport` / `readJSONProp` wrappers. None pass an
`options` arg, so all keep working unchanged.

1. **Optional no-toast:** widen to
   `reportClientError(context, detail, options?: { toast?: boolean })`, `toast`
   defaulting to `true`. Guard the `window.toast?.(…)` call on `options.toast`.
   The global handler passes `{ toast: false }`.
2. **Hard cap:** a module-level `reportCount` and `MAX_REPORTS_PER_PAGE = 25`.
   Ordering is exact: **dedup check first** (a deduped repeat consumes no cap
   budget), then on a genuinely new report increment `reportCount`; when
   `reportCount > MAX_REPORTS_PER_PAGE` log one
   `"client error reporting suppressed (cap reached)"` line and return the id
   **without** POSTing or toasting. So reports 1–25 POST, #26 is the first
   suppressed. The cap lives in the shared seam (one choke point protecting the
   endpoint for every caller, including future ones), not in the handler.
3. **Test-only reset:** export `__resetClientErrorState()` that clears the dedup
   `Set` and zeroes `reportCount`. The existing `client-errors.test.ts` avoids
   cross-test contamination by using a distinct `context` per case (it cannot
   reset module state) — but the cap test *must* count from zero, so it needs a
   real reset. This export is the reset hook (name prefixed `__` to signal
   test-only); production never calls it.

### Loading: `common/layout.py`

Add one line to the `Page()` head script list **first**, before
`Script(src=static("js/htmx.min.js"))` (currently `common/layout.py:526`), so the
listeners register before any vendor or `dist/` script executes:

```python
Script(src=static("js/dist/global-error-handler.js")),
```

A plain classic `<script>` like its neighbors (no `defer` — earliest
registration; the compiled module runs `installGlobalErrorHandler()` on load).

**Coverage is early but not total, and the spec does not overclaim it.** Placing
first catches load-time throws in htmx/flowbite/redirect-toast/toast and all
runtime errors after. It does **not** catch: (a) errors in inline `<head>` scripts
that run *before* this one (the FOUC/theme script, the htmx-config inline block);
(b) errors before the script has fetched+executed. The `{ capture: true }`
registration recovers resource-load errors that would otherwise not bubble. This
is a defense-in-depth net, not a guarantee of catching every possible failure.

## Data flow

```
uncaught throw / rejected promise
  └─ window "error" (capture) | "unhandledrejection" listener   [try/catch: never throws]
       └─ extract fields (safeStringify for non-Error reason)
            └─ shouldReport(...)  ── false ─▶ drop (return)
                  │ true
                  └─ buildDetail(...) → (context, detail≤500)
                        └─ reportClientError(context, detail, { toast: false })
                              ├─ dedup on context|detail  ── seen ─▶ return id (no cap spend)
                              ├─ reportCount++ ; if > 25 ─▶ log "suppressed", return id
                              ├─ console.error(...)
                              └─ POST /api/client-error/  (fire-and-forget, never throws)
```

## Error handling / robustness

- Handlers never throw: top-level `try/catch` swallow, `safeStringify` guards the
  `String(Symbol)` path, `reportClientError` already swallows fetch failure.
  The POST body is all strings (`error_id`, `context`, `detail`, `url`), so
  `JSON.stringify` cannot hit a circular/BigInt throw.
- `installGlobalErrorHandler()` is idempotent within a module instance
  (`installed` flag). A vitest `vi.resetModules()` re-import yields a fresh
  instance that re-registers — tests that dispatch on `window` must therefore
  either not reset modules, or track/remove listeners; the test plan pins one
  module instance per test file and uses `__resetClientErrorState()` for
  per-case isolation of the cap/dedup counters.

## Privacy / PII (accepted risk)

Error `message` text and `location.href` (whose query string can carry filter
JSON) already ship to the container log via #232 — but only from the one
malformed-JSON widget path. #328 fires on **any** uncaught error, materially
widening the surface of free-form user data that can reach logs. This is
**accepted**: the sink is the operator's own container log (no third party), the
app is self-hosted, and log-only (no toast) keeps it out of the UI. No redaction
or message allowlist is in scope; revisit only if a hosted/multi-tenant
deployment is ever targeted.

## Testing

New vitest `ts/global-error-handler.test.ts` (jsdom):

- `shouldReport`: drops each extension scheme in `filename`; drops an extension
  scheme appearing only in the **stack frame** with a page `filename`; drops
  `"Script error."` + empty filename + no stack; keeps same-origin `filename`;
  keeps inline (empty filename, real message, has stack); keeps a plain rejection.
- `safeStringify`: `Symbol()` → fallback string (no throw); `null`/`undefined` →
  fallback; `{ message: "x", name: "Y" }` → `"Y: x"`; `{}` → fallback (not
  `"[object Object]"`).
- `buildDetail`: full `message @ file:line:col | frame`; omits location when
  filename empty; omits frame when no stack; strips leading message line **only**
  when line 0 matches the message (a Firefox-style stack whose line 0 is a frame
  keeps it); caps a 300-char filename to 200; truncates the whole to 500.
- end-to-end via mocked `fetch`: dispatching a synthetic `ErrorEvent` /
  `PromiseRejectionEvent` on `window` yields exactly one POST with the expected
  body and **no** `window.toast` call.
- idempotent install: calling `installGlobalErrorHandler()` twice registers the
  listeners once (one dispatch → one report).

Extend `ts/client-errors.test.ts`:

- `{ toast: false }` suppresses `window.toast` but still POSTs.
- hard cap (with `__resetClientErrorState()` in `beforeEach`): 25 distinct
  reports POST; the 26th does not POST and logs the suppressed line once; a
  deduped repeat within the window does not consume cap budget.

No pytest / e2e changes — server side untouched. Gate is the full
`direnv exec . make check` (lint + format + mypy + ts-check + vitest + entire
pytest incl. e2e), green. The two new `.test.ts` files are emit-excluded by
`tsconfig.json` and type-checked via `tsconfig.check.json` (CLAUDE.md), both
exercised by `make ts-check` inside `make check`.

## Out of scope / non-goals

- No `stack_trace` schema field / full-stack capture (decision 4).
- No third-party sink (Sentry etc.) — as #232, the sink stays the container log.
- No time-window / token-bucket rate limiting — the per-page hard cap suffices
  for a page-lifetime net (decision 2).
- Toast for global errors — explicitly rejected (decision 1).
- **`rejectionhandled` tracking** (a promise rejected then handled late still
  fires `unhandledrejection` once → a possible false-positive report). Accepted
  as rare low-value noise, deduped/capped like any other; not worth the
  `event.promise` bookkeeping.
- **Same failure surfacing through both handlers** (an `await` in an event
  handler can produce either `error` or `unhandledrejection`) → at most two log
  lines with distinct `context`. Accepted as negligible.
