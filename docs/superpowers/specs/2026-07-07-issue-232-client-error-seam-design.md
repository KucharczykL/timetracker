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
3. **UX:** error toast with error ID **plus** inline mark on the failed widget.
4. **Global `window.onerror` hook:** deferred — follow-up issue.

## Design

### 1. Server sink — `POST /api/client-error`

In `games/api.py`, new `client_error_router` mounted at `/client-error`.

- Request schema: `error_id: str`, `context: str` (e.g.
  `"quick-filter-bar[filter]"`), `detail: str`, `url: str`. All fields
  length-capped via the Schema (`error_id` 16, `context`/`url` 200, `detail`
  500) so a bad client cannot log-spam.
- Handler: single `logging.getLogger("client_errors").error(...)` line carrying
  all fields + `request.user`; returns 204 No Content.
- Auth inherited from `NinjaAPI(auth=django_auth)`; CSRF enforced.

### 2. Client seam — new `ts/client-errors.ts`

- `reportClientError(context: string, detail: string): string`
  - generates an 8-char error ID (`crypto.randomUUID()` slice),
  - `console.error` with ID + context + detail,
  - fire-and-forget `fetch` POST with `X-CSRFToken` (CSRF-token lookup as in
    `presets.ts`); any network/HTTP failure is swallowed — reporting must never
    break the page,
  - returns the ID.
- Module-level `Set<string>` dedupes by context: one server report and one
  toast per context per page load.

### 3. JSON helpers (same module)

- `parseJSONWithReport<T>(raw: string | null | undefined, fallback: T,
  context: string, element?: HTMLElement): T` — value-level, for dataset/string
  sites.
- `readJSONProp<T>(element: Element, attr: string, fallback: T): T` — attribute
  wrapper; context auto-derived as `tag[attr]`.
- On parse failure: `reportClientError`, toast
  `"Filter failed to load (error {id}) — reload the page"` (type `error`,
  deduped), inline mark on the element (`data-degraded="json-parse"`, classes
  `ring-2 ring-red-500`, `title="Failed to load (error {id})"`), then return
  the fallback — today's degraded behavior is preserved, just no longer silent.

### 4. Migrations

| Site | Change |
|------|--------|
| `filter-widgets.ts` `parseJSONAttr` | deleted; callers use `readJSONProp` |
| `filter-group.ts` filter prop | `parseJSONWithReport` |
| `filter-group.ts` models prop | `parseJSONWithReport` |
| `filter-summary.ts` models prop | `parseJSONWithReport` |
| `operations.ts` `parseFieldMeta` | `parseJSONWithReport` (empty-string case stays a silent `null` — normal, not an error) |
| `quick-filter-bar.ts` preset load | keeps its own toast text and the `"preset load failed"` console substring (e2e crash-guard constraint); adds `reportClientError` |
| `filter-group.ts` leaf hydration | `console.warn` → `reportClientError`; no toast (blank widget is already visible) |

`toast.ts` / `htmx-redirect-toast.ts` JSON parses are excluded
(toast-about-toast is circular) — follow-up issue.

### 5. Tests

- vitest `ts/client-errors.test.ts`: parse ok passes through; malformed →
  fallback + inline mark + exactly one toast + one POST; dedupe across repeated
  failures in one context; fetch rejection never throws.
- pytest: endpoint returns 204 and emits the log record (`caplog`); 401 when
  unauthenticated; over-length payload rejected (422).
- Gate: full `direnv exec . make check` (incl. e2e) before push.

### 6. Follow-up issues to file

1. Global `window.onerror`/`unhandledrejection` → `reportClientError`
   (needs rate-limit + noise-filter decisions).
2. `toast.ts`/`htmx-redirect-toast.ts` parse sites — decide non-circular
   reporting.
