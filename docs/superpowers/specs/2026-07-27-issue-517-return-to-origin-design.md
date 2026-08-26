# Return-to-origin redirects (issue #517)

Date: 2026-07-27
Issue: https://github.com/KucharczykL/timetracker/issues/517

Revised after adversarial review; the review's findings are merged in below
rather than listed separately.

## Problem

After a mutating action (edit, delete, add), the app decides where to send you
by four unrelated mechanisms, none of which knows where you came from:

1. **`use_custom_redirect`** (`games/views/general.py:93`) — redirects any
   decorated view to `request.session["return_path"]`. That key is written by
   three unrelated views (`view_game`, `stats`, `stats_alltime`), always as
   `request.path`, and is never cleared. View a game, navigate away, edit a
   platform — you land back on the game. Query strings cannot survive it, so it
   can never return you to the list you were actually looking at.
2. **`HTTP_REFERER`** (`games/views/playevent.py:309`) — `delete_playevent`
   redirects to the raw, unvalidated referrer, falling back to `/`.
3. **Hardcoded canonical targets** — most views. Several are simply wrong:
   `edit_game`, `delete_game` and `edit_purchase` all redirect to the
   **sessions** list.
4. **Dead code** — `redirect_to` and `add_next_param_to_url`
   (`common/utils.py:156`) implement a `?next=` scheme with zero callers.

Consequence: no filter, sort, page or per-page state survives any mutation, and
some flows land on an arbitrary stale page.

## Goals

- After any mutating action, return to the exact URL the action was launched
  from, query string intact.
- One mechanism, no server-side state, no per-view exceptions to remember.
- A call site that forgets to carry the origin fails type checking or tests,
  not silently in production.
- No mutating route reachable by GET.

## Non-goals

- No navigation history stack; one hop of origin, not a breadcrumb trail.
- No scroll-position restoration.
- The refund and split confirmations keep their htmx modals. Their post-action
  semantics are an in-place row swap, which a full page would change; only the
  delete flows move to confirmation pages.

## Design

### 1. The origin lives in the URL, and only in the URL

Two modules. `common/returns.py` holds the mechanism and knows nothing about
this app's routes:

```python
type OriginUrl = str  # "/tracker/game/list?filter=%7B%22status%22%3A%5B%22p%22%5D%7D"
type UrlName = str    # "games:edit_game"

ORIGIN_PARAM = "origin"

def action_url(viewname: UrlName, *args: Any, origin: OriginUrl | None, **kwargs: Any) -> str
def parse_origin(request, *, returnable: Container[UrlName], reject: str | None = None) -> OriginUrl | None
```

`games/views/returns.py` binds it to this app's route table and is what views
and the layout import:

```python
def origin_from(request, *, reject: str | None = None) -> OriginUrl | None
def return_url(request, *, fallback: UrlName, fallback_args=(), reject=None) -> str
```

The parameter is **`origin`, not `next`**. Django's own auth views use `next` as
their `redirect_field_name`, so a mutating view reading `next` cannot tell
"where to go after login" from "where to go after this mutation" — both are
root-relative, both resolve. A distinct name removes the whole class.

`action_url` is `reverse()` plus `?origin=<urlencoded origin>`. The `origin`
argument is keyword-only with **no default**, so mypy rejects a call site that
omits it; it is nullable only so a caller can forward "no origin" explicitly, in
which case the parameter is left off the URL entirely. Note the limit of that
guarantee: `OriginUrl` is a transparent alias for `str`, so omission is caught
but passing the *wrong* string is not.

Validation, in order — a candidate must pass all of them:

1. `url_has_allowed_host_and_scheme(candidate, allowed_hosts=None)` — only
   root-relative URLs survive, which also rejects `//evil.example` and any
   scheme.
2. The resolved route's url name must be in `READ_ONLY` (below). A bare
   `resolve()` check is not enough: it admits `/logout/` (POST-only, so a 405
   after a successful mutation), `/api/games/search` (JSON), and — the real
   danger — any *mutating* route, which would let a crafted link launder a
   user's confirming POST into a server-issued GET redirect that mutates again.
3. `reject`, when given, must not equal the candidate's path.

What survives validation is the **parsed** candidate, not the raw string:
`url_has_allowed_host_and_scheme` strips whitespace before validating, so
`?origin=%0A/tracker/game/list` would otherwise pass validation and then blow up
in `redirect()` with `BadHeaderError` *after* the mutation had committed.

This does **not** guarantee the target still exists. `resolve()` proves the
route exists, not the object: a cascade delete (a `Purchase` whose last `Game`
goes away), or another tab deleting the object you are returning to, can still
land on a 404. `reject` covers the one case the view knows about — the object it
just deleted.

### 2. Crossing the GET → POST boundary

No hidden form field. `AddForm`'s `<form>` carries no `action`
(`common/components/primitives.py:1538`), so the browser POSTs to the current
full path and `?origin=` survives for free. Verified against the alternatives:
there is no global `hx-boost`, no submit interception in `ts/`, and the only
`sync_url` URL rewriter (`ts/elements/search-select.ts`) is disabled at every
call site. Modal forms `hx_post` to an explicit URL, which they build with
`action_url`. One rule everywhere: the origin rides the query string, never a
form body, never the session — so `origin_from` reads `request.GET` even when
handling a POST.

### 3. Every route is classified

`games/views/returns.py` sorts **all** routed url names into exactly four
buckets:

```python
READ_ONLY: frozenset[UrlName]  # renders a page; the only valid origins
ORIGIN_AWARE: frozenset[UrlName]  # mutates, then redirects; consumes an origin
CONFIRMATION: frozenset[UrlName]  # GET; renders a confirm modal, forwards the origin
IN_PLACE: frozenset[UrlName]  # mutates, answers with a partial swap
```

The guard test asserts the union covers every routed name. An earlier draft
guarded with a `^(add|edit|delete|…)_` name prefix; that shape does not hold —
the two session-clone routes are named for where they are launched from, so they
had to be hand-listed, and any future `clone_*`, `reset_*` or `archive_*` route
would pass silently. Completeness against the actual route table has no such
hole, and it yields `READ_ONLY` — the origin allow-list — as a by-product.

Response shapes:

- **`ORIGIN_AWARE`** ends with `redirect(return_url(request, fallback=...))`.
  Includes `split_purchase`, which sets an `HX-Redirect` header.
- **`CONFIRMATION`** views do not mutate; they forward the origin they were
  given into the modal form's post URL via `action_url`. Both surviving members
  (`refund_purchase_confirmation`, `split_purchase_confirmation`) need this
  wiring, which they lack today — without it `split_purchase` can never see an
  origin and the row `refund_purchase` swaps back in loses the stamps its
  neighbours have.
- **`IN_PLACE`** is `refund_purchase` alone. Note that
  `docs/superpowers/plans/2026-07-26-table-widths-phase-2.md` records a pending
  decision under #523 to retire that row-fragment endpoint and have refund
  reload the list; when that lands, `refund_purchase` moves to `ORIGIN_AWARE`.

Fallbacks stay literal at each `return_url` call, not in a central table,
because several are dynamic — the statuschange views fall back to
`games:view_game` with the affected game's id.

### 4. No mutating route answers a GET

Three routes mutate on GET today and are not delete flows:

- `drop_purchase` and `finish_purchase` (`games/views/purchase.py:467`, `:608`)
  set every linked game's status on a plain GET. Neither is linked from
  anywhere — the only references in the tree are their own definitions and
  `games/urls.py`. **Both are deleted**, views and routes.
- `view_game_start_session_from_session` clones a session on GET and, likewise,
  has no caller at all. **Deleted.**
- `list_sessions_start_session_from_session` clones a session on GET and *is*
  reachable — from the navbar's resume dropdown on every page
  (`common/layout.py:400`). It becomes POST-only, rendered with the existing
  `DropdownPostItem` rather than `DropdownLinkItem`. Its `HX-Refresh` branch is
  dead code (the only caller is a plain link) and goes with it.

### 5. Chained forms forward the origin

`add_purchase` with `submit_and_redirect`, and `add_game` with
`submit_and_create_session` / `submit_and_redirect`, send you on to another
form. That is a chain, not a return: the second form is built with
`action_url(..., origin=origin_from(request))`, so the original origin survives
the hop and the eventual save lands where the user started.

### 6. Stamping call sites

Each list and detail view computes `origin = request.get_full_path()` once, then
builds every action through `action_url`. Every row builder in the chain takes a
required keyword-only `origin`.

The navbar is part of this. `Page()` renders it into every response, and it
carries seven mutating links: six entity `add_*` items and the Log button
(`common/layout.py:239`, `:391`). They are stamped too, so "Add session" from a
filtered games list returns to that list. `Page()` supplies the origin **only
when the current route is itself `READ_ONLY`** — on a form or confirmation page
there is nothing meaningful to come back to, and stamping one would produce an
origin that validation rejects anyway.

Backstop test, in the style of the existing `stats_links` parity tests: render
every page, walk each `href`, `hx-get`, `hx-post` and `<form action=>`, resolve
the path, and assert that any URL naming an `ORIGIN_AWARE` or `CONFIRMATION`
view carries an origin equal to the rendering page's own full path. `<form
action=>` matters most of all — it is the delete-confirmation POST target.

The backstop's reach is real but bounded, and the bound is structural: it cannot
see htmx-swapped fragments (where "the rendering page's path" is the wrong
expectation anyway), standalone modal endpoints, or URLs built in TypeScript.
Those need the per-flow tests below.

## Delete hardening

Row deletes are currently plain GET `href`s that destroy on click — no
confirmation, and any prefetcher or crawler that follows one deletes data. Only
the game detail page confirms.

The project already has the right primitive: `ConfirmPage`
(`common/components/primitives.py:1657`) renders a full-page prompt with a POST
form and a cancel link, and `delete_statuschange` is already built on it —
GET renders the confirmation, POST performs the delete, both on the same URL.
Generalise that pattern instead of adding a modal:

- Every delete view answers GET with a `ConfirmPage` and POST with the delete.
  One URL, so `?origin=` rides through the confirmation into the POST with no
  extra plumbing, and the cancel link is simply the origin.
- Extract `confirm_and_delete()` into `games/views/deletion.py`, since all six
  deletes are "render the prompt, then `instance.delete()`". Per-entity views
  supply only the copy and the fallback.
- `ConfirmPage` gains an optional `details` block slot for the associated-data
  counts the game modal shows today. They cannot go in `message`, which renders
  inside a `<p>`, and a `<ul>` there is invalid HTML. (An earlier draft claimed
  `tests/test_html_validity.py` would catch that; it would not — that suite
  checks interactive-element nesting and duplicate ids only. The new
  confirmation pages should be added to its URL list regardless, since nothing
  else covers their markup.)
- Its `action_url` parameter is renamed `post_url` to avoid reading as a call to
  the new `action_url()` helper.
- The bespoke `_delete_game_confirmation_modal`, its view and its
  `game/<id>/delete/confirm` route are deleted.
- Row delete buttons stay plain links — they now lead to a confirmation page
  rather than destroying on click, so the no-JS path survives and no prefetcher
  can delete anything.

## Authentication hole found while classifying

`edit_playevent` and `delete_playevent` carry no `@login_required`, and the
project has no `LoginRequiredMiddleware`. An unauthenticated request can edit or
delete any play event. Verified by walking every `games.urls` callback; all
other views are protected, and the Ninja API is protected wholesale by
`NinjaAPI(auth=django_auth)` (`games/api.py:51`).

Fixed here in its own commit, with a test that asserts every view reachable from
`games.urls` requires authentication, so the next omission fails the suite.

## Removals

- `use_custom_redirect` and its three `session["return_path"]` writes
  (`games/views/game.py:745`, `games/views/general.py:113`, `:128`).
- The `HTTP_REFERER` redirect in `delete_playevent`.
- The dead `redirect_to` and `add_next_param_to_url` in `common/utils.py`.
- `drop_purchase`, `finish_purchase`, `view_game_start_session_from_session`.
- The wrong canonical fallbacks: game flows now fall back to the games list,
  purchase flows to the purchases list, and so on.

## Testing

- **Unit**: `action_url` and `parse_origin` against a foreign host,
  `//evil.example`, a `javascript:` scheme, an embedded newline, a non-resolving
  path, a path resolving to a *mutating* route, a path resolving to the API, a
  rejected origin, an absent parameter, and a valid filtered list URL.
- **Classification guard**: the four buckets cover every routed name exactly
  once.
- **Origin parity**: every mutating link and form action on every rendered page
  carries the page's own path.
- **Auth sweep**: every `games.urls` view redirects an anonymous request to
  login.
- **Login interaction**: hitting an origin-carrying mutating URL while logged
  out nests it inside Django's own `?next=`; assert the round trip lands on the
  original list.
- **Per-flow**: the refund row swap and the split redirect both honour an
  origin — neither is reachable by the parity backstop.
- **E2E**: filter the games list, edit a game, save, assert the browser is back
  on the filtered URL *and* that the filter is still applied (a different row
  set than unfiltered); delete a game from its detail page, assert it lands on
  the games list rather than a 404.

## Commit sequence

Each commit leaves the tree green and shippable.

1. `fix(auth)`: `@login_required` on the two playevent views, plus the auth
   sweep test.
2. `feat(returns)`: `common/returns.py` and its unit tests. No callers.
3. `feat(returns)`: the four-bucket classification, the bound `origin_from` /
   `return_url`, and the completeness guard. No callers.
4. `refactor(views)`: every redirecting view consumes `return_url` with a
   correct fallback; the GET-mutating routes are deleted or made POST-only;
   `use_custom_redirect`, the session writes, the referrer redirect and the dead
   helpers go. Behaviour after this commit is fallback-only — correct, just not
   yet origin-aware.
5. `feat(links)`: stamp origins at every call site including the navbar; add the
   parity test.
6. `refactor(components)`: `ConfirmPage` gains `details`; `action_url` renamed
   to `post_url`; the game delete modal, view and route are replaced by a
   confirmation page.
7. `feat(deletes)`: `confirm_and_delete()` and GET-confirm/POST-delete for
   purchase, session, playevent, platform and device.
8. `test(e2e)`: the filtered round trips.
9. `docs`: CLAUDE.md's view-layer and component sections.

## Risks

- **URL length.** A filtered list URL nested inside an edit URL reaches roughly
  1–2 KB with a large filter. Browsers and Django both accept well beyond that,
  and the alternative — a server-side token table — reintroduces exactly the
  stale state that caused this issue.
- **Ugly URLs.** Accepted deliberately in exchange for statelessness:
  bookmarkable, shareable, correct across multiple tabs.
- **Sub-path deployments.** `request.get_full_path()` returns
  `SCRIPT_NAME + PATH_INFO` while `resolve()` expects `PATH_INFO`. They coincide
  here because the `/tracker` prefix comes from the urlconf rather than
  `FORCE_SCRIPT_NAME`; a future sub-path deployment would silently reject every
  origin. Worth a comment at the validation site.
