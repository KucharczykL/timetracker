# Session JSON Read API — design

**Date:** 2026-06-24
**Status:** Approved (design)
**Adversarial review:** 3 parallel forks (Ninja/Django correctness, API contract, security/blast-radius). Findings folded in below.

## Context & goal

Long-term direction: a pure-JavaScript frontend talking to a Django JSON API.
The committed middle step is to **build up the JSON API** so UI can be
reconstructed in JS later, accepting per-slice frontend duplication as a
stepping stone — with the discipline that **each converted feature deletes its
Python render in the same PR** (never accumulate parallel implementations beyond
the slices currently in flight).

This spec is the **first slice**: two authenticated, resource-shaped **read**
endpoints for `Session`. No rendering work here — this is the data layer the
(currently paused) finish/reset enhancement and a future JS list view will
consume.

The finish/reset progressive-enhancement feature is **explicitly paused** behind
this; it resumes as a later slice that renders a row in TS from this API.

## Decisions (locked)

- **Resource-shaped JSON** (raw data), not presentation-shaped. ISO-8601 UTC
  timestamps, durations in seconds, nested id-bearing summary objects. All
  formatting/locale/timezone/"now"/marks are the client's job. Rationale: a
  pure-JS frontend formats per the user's browser locale+timezone, caches
  entities by id, and renders live values ("now", ticking timers) client-side —
  presentation-shaped strings fight every one of those.
- **Full filter/sort/pagination parity** with the HTML list, by reusing the
  existing helpers and the same `?filter=`/`?sort=`/`?page=` query vocabulary.
- **`auth=django_auth` API-wide** — closes the pre-existing open-API hole.
- **Pagination envelope uses `items`** (aligns with Ninja's built-in `@paginate`
  key), plus page metadata. One pagination convention across the whole API.
- **Client owns routing** — ship ids, never `reverse()`-derived hrefs.
- **Single-user assumption** — endpoints are intentionally unscoped by user.

## Endpoints

On the existing `session_router` (mounted at `/api/session`):

- `GET /api/session/` — list. Query params:
  - `filter` — structured filter JSON (same as HTML list; `parse_session_filter`)
  - `sort` — sort key (same as HTML list; confirmed param name is `sort`)
  - `page` — 1-based page number
  - Client `?limit` is **not** honored; `page_size` is fixed server-side.
  Returns the list envelope.
- `GET /api/session/{id}` — detail. Single `SessionOut`; `404` if absent.

## Schemas (resource-shaped)

```python
class PlatformOut(Schema):
    name: str
    icon: str

class GameOut(Schema):
    id: int
    name: str
    platform: PlatformOut | None = None   # FK nullable; sentinel usually present

class DeviceOut(Schema):
    id: int
    name: str
    type: str                              # raw code (PC/Console/Handheld/…)

class SessionOut(Schema):
    id: int
    game: GameOut | None = None            # FK nullable; resolvers must not assume
    device: DeviceOut | None = None        # usually the "Unknown" sentinel, rarely null
    timestamp_start: datetime              # ISO-8601 UTC ("…Z")
    timestamp_end: datetime | None = None  # null while session is open
    duration_manual_seconds: int           # resolver; null timedelta → 0
    is_manual: bool                        # resolver = session.is_manual()
    note: str
    emulated: bool
    created_at: datetime
    modified_at: datetime                  # NB: Session field is modified_at, not updated_at

class SessionListOut(Schema):
    items: list[SessionOut]
    count: int
    page: int
    page_size: int
    num_pages: int
```

### Resolvers (required — these do NOT auto-serialize)

- `duration_manual_seconds`: model attr is `duration_manual: timedelta` (and
  `null=True`). Needs
  `@staticmethod def resolve_duration_manual_seconds(obj): return int(obj.duration_manual.total_seconds()) if obj.duration_manual else 0`.
- `is_manual`: ship `session.is_manual()` directly. It **cannot** be re-derived
  on the client: `duration_manual` is `null=True` and
  `is_manual = not (duration_manual == timedelta(0))`, so a **null** value reads
  as manual-True and **negative** values break any `> 0` test. Shipping the
  boolean is the only way the client mark matches the server.

### Explicitly NOT in the schema (and why)

- **`duration_total_seconds`** — dropped. While a session is open
  `duration_calculated = Coalesce(end − start, 0) = 0`, so `duration_total` is
  manual-only, not live elapsed — misleading. It's also derivable client-side
  from `timestamp_start`/`timestamp_end` + `duration_manual_seconds`. The client
  owns elapsed/"now" math.
- **Action/link hrefs** (`view_game`, `edit_session`, `delete_session`,
  `reset_session_start`, `end_session`) — the client owns routing; it builds URLs
  from ids. Not shipped.
- **Full Game/Device fields** (`sort_name`, `year_released`, `status`, …) —
  nested objects are id-bearing *summaries* for the entity cache, not the
  canonical resources.

## List implementation (reuse, with corrections)

Reuse, do not reimplement:

1. `parse_session_filter(request.GET.get("filter", ""))` → apply `.to_q()` if not
   None. The API supports **only** the structured `filter` param; the HTML list's
   free-text `search_string` fallback is presentation-era and is **not** carried
   into the API (a JS client builds structured filters).
2. Sorting threads a `FindFilter` first:
   `apply_sort(qs, parse_find_filter(request), SESSION_SORTS, SESSION_DEFAULT_SORT)`.
   `apply_sort` takes a `FindFilter`, **not** the request. `SortResult.unknown`
   keys are silently ignored in JSON (the HTML path's `messages.warning` is
   presentation; omit it here).
3. `select_related("game", "game__platform", "device")` (already done by the HTML
   view) — no N+1.
4. Pagination: `paginate(request, qs)` with the fixed `per_page`. **Guard**
   `page_obj is None` (returned when `limit=0`); since the API ignores client
   `?limit` this won't normally trigger, but build the envelope defensively.
   Envelope from `page_obj.paginator`:
   `count = paginator.count`, `num_pages = paginator.num_pages`,
   `page_size = paginator.per_page`, `page = page_obj.number`.

## Auth

`NinjaAPI(auth=django_auth)` — `django_auth` is `SessionAuth` (`csrf=True`).

- GET reads are CSRF-safe → pass with the session cookie; anonymous → `401`.
- Unsafe methods (existing PATCH/POST/DELETE) now require the `csrftoken` cookie
  to match the `X-CSRFToken` header. **All current browser callers already send
  it** (`select.ts`, `play-event-row.ts`, `filter-bar.ts`) → no functional break.
- `/api/docs` and `/api/openapi.json` become auth-gated when logged out
  (DEBUG-only, acceptable).

### Blast-radius notes (verified)

- No anonymous `/api/` consumer exists — every caller lives on a `@login_required`
  page; the login page makes zero API calls.
- e2e synthetic-page tests use an `@override_settings(ROOT_URLCONF=…)` that does
  not mount `/api/`, so they are unaffected.
- **Watch note:** `tests/test_paths_return_200.py` hits `/api/platforms/groups`
  and only stays green because `setUp` calls `force_login`. Do not remove that
  login.

## Security / IDOR

`Session` has **no owner/user FK** — single-user app, all data shared, so
`get_object_or_404(Session, id=…)` is correct (no IDOR). **If multi-user is ever
introduced, every read endpoint here leaks** and must gain `.filter(user=…)`.
This assumption is load-bearing; keep it visible.

## File changes

- `games/api.py`:
  - `NinjaAPI(auth=django_auth)` (import `django_auth` from `ninja.security`).
  - Add `PlatformOut`, `GameOut`, `DeviceOut`, `SessionOut`, `SessionListOut`
    schemas + resolvers.
  - Add the two GET handlers on `session_router`, reusing
    `parse_session_filter` / `parse_find_filter` / `apply_sort` / `paginate`.
  - Small local `seconds(td) -> int` helper for timedelta→int (or inline).
- No model, template, or TS changes in this slice.

## Testing

`tests/test_api.py` (new or extended):

- **Detail**: full shape; nested `game`/`platform`/`device`; null `timestamp_end`;
  durations in seconds; ISO-UTC timestamps; `modified_at` present; `404` for a
  missing id.
- **`is_manual` matrix**: `duration_manual` null → True; `timedelta(0)` → False;
  positive → True; negative → True. (Locks the non-derivable behavior.)
- **List**: envelope keys (`items`/`count`/`page`/`page_size`/`num_pages`);
  `?sort=` parity vs the HTML list; one structured `?filter=` parity case;
  pagination across pages (`page`, `num_pages`).
- **Auth (mandatory)**: anonymous → `401` on both new endpoints **and** one
  existing endpoint; logged-in → `200`/`204`.

`e2e/` (mandatory — the test `Client` is CSRF-exempt, so only a real browser
catches a CSRF regression):

- Logged-in browser changes a session device via the dropdown → PATCH returns
  `200`, **not** `403`, after `csrf=True` is enabled.

## Out of scope (named)

- Finish/reset enhancement and any TS row renderer (resumes as a later slice).
- Write/PATCH session endpoints beyond what already exists.
- JSON list endpoints for other entities (games, purchases, …).
- Removing any Python row render (nothing is converted in this slice).
- Fixing the latent `is_manual`-on-null behavior — this slice **replicates**
  current behavior, it does not change it.

## Verification

1. `make test` — new API tests + existing suites pass.
2. `make check` — lint + mypy + ts-check + drift gates.
3. `make test-e2e` — device-PATCH-still-200 assertion.
4. Manual: `GET /api/session/` and `/api/session/{id}` while logged in return the
   documented shapes; logged out → `401`.
