# Client-error seam for malformed JSON props (issue #232)

Date: 2026-07-07
Issue: https://github.com/KucharczykL/timetracker/issues/232

## Problem

Malformed JSON in a widget prop (server/client version skew, stale cached page)
degrades filter widgets silently: `console.warn` + empty fallback, no
user-facing signal, nothing production observability can see. The pattern is
hand-rolled at several seams:

- `parseJSONAttr` in `ts/elements/filter-widgets.ts` (callers: pill lists
  `data-included`/`data-excluded` in the same file, `data-path` in
  `quick-filter-bar.ts`)
- `filter-group.ts` — `filter` prop (~289), `models` prop (~322)
- `filter-summary.ts` — `models` prop (~76)
- `filter-tree/operations.ts` — `parseFieldMeta` `data-meta` blob (~71)
- `quick-filter-bar.ts` preset-load parse (already toasts; no server signal)
- `filter-group.ts` leaf-hydration catch (~1073) — not JSON, same silent
  disease

## Decisions (interview outcomes)

1. **Scope:** consolidate all the sites above onto one shared seam.
2. **Sink:** new `POST /api/client-error` endpoint → Django logger → container
   logs. No third-party (no Sentry).
3. **UX:** error toast with error ID **plus** inline mark on the failed widget —
   both best-effort (see Signal guarantees). The **guaranteed** signal is the
   server log line.
4. **Global `window.onerror` hook:** deferred — follow-up issue.

## Signal guarantees (adversarial-review outcome)

The three signals are not equally reliable; the design must not overclaim.

- **Server log line — GUARANTEED.** This is the issue's actual ask ("a real
  logged error production observability can see"). Always fires (subject only to
  the endpoint being reachable).
- **Toast — BEST-EFFORT.** The `show-toast` listener is registered inside
  `alpine:init` (`ts/toast.ts:25→105`), but a custom element's
  `connectedCallback` runs during HTML parse, *before* `alpine:init`. The
  defense-in-depth failure case (stale cached page / server-client version skew)
  is precisely an initial-load parse, so a toast dispatched then has no listener
  and is dropped. Acceptable — we still get the log line and the mark. Do NOT
  rely on the toast for the initial-load path.
- **Inline mark — BEST-EFFORT.** Set widgets (`data-included`/`data-excluded`)
  and overflow-menu facets sit inside *closed* dropdown panels; a `ring` on a
  hidden element shows nothing until the user opens the panel. Still worth
  adding (visible once opened, and on always-visible widgets), but not the
  primary signal.

## Design

### 1. Server sink — `POST /api/client-error`

In `games/api.py`, new `client_error_router`, mounted with
`api.add_router("/client-error", client_error_router)` (matching the existing
routers).

- Request schema: `error_id: str`, `context: str` (e.g.
  `"quick-filter-bar[filter]"`), `detail: str`, `url: str`. All fields
  length-capped via the Schema (`error_id` 16, `context`/`url` 200, `detail`
  500) so a bad client cannot log-spam. On over-length, ninja 1.6.2 / pydantic
  2.13 returns 422.
- Handler: single `logging.getLogger("client_errors").error(...)` line carrying
  all fields + `request.user`. **Log-injection guard:** strip `\r`/`\n` from
  every client-supplied field before it enters the log line (CRLF could forge
  log entries). Declared `response={204: None}`, `return Status(204, None)`
  (the `partial_update_game` / playevent-delete precedent, `api.py:100,136`).
- Auth inherited from `NinjaAPI(auth=django_auth)`; CSRF enforced.

### 1b. Logging config — `timetracker/settings.py`

Add a `client_errors` logger to the existing `LOGGING["loggers"]` block:
`{"handlers": ["console"], "level": "ERROR", "propagate": False}`. Without it,
`getLogger("client_errors")` propagates to a root logger that has **no
handlers**, falling to Python's `lastResort` (bare stderr) instead of the app's
`console` handler — works by accident, not by design.

### 2. Client seam — new `ts/client-errors.ts`

- `reportClientError(context: string, detail: string): string`
  - generates an 8-char error ID (`crypto.randomUUID()` slice),
  - `console.error` with ID + context + detail,
  - fire-and-forget `fetch` POST with `X-CSRFToken`; any network/HTTP failure is
    swallowed — reporting must never break the page,
  - returns the ID.
- **CSRF helper:** extract `getCsrfToken` (currently exported from
  `ts/elements/presets.ts:12`) into a shared `ts/csrf.ts` and import it from
  both. A utility module must not depend on an element module (inverted dep).
- Module-level `Set<string>` dedupes: one server report + one toast per **dedupe
  key** per page load. The key is NOT bare `context` — two same-tag/attr
  elements on one page (e.g. two `<search-select>`) would collide and suppress
  the second's distinct failure. Key on `context + "|" + detail` (detail carries
  the element-distinguishing info), so genuinely distinct failures each report
  once.

### 3. JSON helpers (same module)

- `parseJSONWithReport<T>(raw: string | null | undefined, fallback: T,
  context: string, element?: HTMLElement): T` — value-level, for dataset/string
  sites. `element` is optional; when absent (e.g. `parseFieldMeta`, which only
  has a raw string) the inline mark is skipped — report + toast only.
- `readJSONProp<T>(element: Element, attr: string, fallback: T): T` — attribute
  wrapper; passes `element` through so the mark can be applied.
- On parse failure: `reportClientError`, toast
  `"Filter failed to load (error {id}) — reload the page"` (type `error`,
  deduped — best-effort per Signal guarantees), inline mark on the element when
  supplied (`data-degraded="json-parse"`, `title="Failed to load (error {id})"`,
  plus the **literal** class string `"ring-2 ring-red-500"` — written verbatim,
  never concatenated, so Tailwind's `ts/` scan compiles it; `ring-red-500` is
  not currently in `base.css` and only appears once this literal exists), then
  return the fallback — today's degraded behavior is preserved, no longer
  silent. Run `make css` so the new class lands in `base.css`.

### 4. Migrations

| Site | Change |
|------|--------|
| `filter-widgets.ts` `parseJSONAttr` | deleted; callers use `readJSONProp` |
| `filter-group.ts` filter prop | `parseJSONWithReport` |
| `filter-group.ts` models prop | `parseJSONWithReport` |
| `filter-summary.ts` models prop | `parseJSONWithReport` |
| `operations.ts` `parseFieldMeta` | `parseJSONWithReport` with no `element` (raw-string site → no inline mark); empty-string case stays a silent `null` — normal, not an error |
| `quick-filter-bar.ts` preset load | keeps its own toast text and the `"preset load failed"` console substring (e2e crash-guard constraint); adds `reportClientError` |
| `filter-group.ts` leaf hydration | `console.warn` → `reportClientError`; detail = `String((error as Error)?.message ?? error)` (it's a thrown `Error`, not a JSON blob); no toast (blank widget is already visible) |

`toast.ts` / `htmx-redirect-toast.ts` JSON parses are excluded
(toast-about-toast is circular) — follow-up issue.

### 5. Tests

- vitest `ts/client-errors.test.ts`: parse ok passes through; malformed →
  fallback + inline mark (when element given) + exactly one toast + one POST;
  dedupe suppresses a repeated `context+detail`; two distinct `detail`s under
  one `context` each report once; `parseFieldMeta`-style (no element) skips the
  mark; fetch rejection never throws. Stub `window.toast`, `fetch`, and
  `crypto.randomUUID` (jsdom) — follow the `presets.test.ts` /
  `quick-filter-bar.test.ts` stubbing precedent.
- pytest: endpoint returns 204 and emits the log record (`caplog`); CRLF in a
  field is stripped from the log line; 401 when unauthenticated; over-length
  payload rejected (422).
- Gate: full `direnv exec . make check` (incl. e2e) before push. Existing e2e
  console guards are substring-specific (`"preset load failed"`), so the new
  `console.error` lines do not trip them — verified.

### 6. Follow-up issues to file

1. Global `window.onerror`/`unhandledrejection` → `reportClientError`
   (needs rate-limit + noise-filter decisions).
2. `toast.ts`/`htmx-redirect-toast.ts` parse sites — decide non-circular
   reporting.
