# Return-to-origin redirects (issue #517)

Date: 2026-07-27
Issue: https://github.com/KucharczykL/timetracker/issues/517

## Problem

After a mutating action (edit, delete, add), the app decides where to send you
by four unrelated mechanisms, none of which knows where you came from:

1. **`use_custom_redirect`** (`games/views/general.py:93`) — redirects any
   decorated view to `request.session["return_path"]`. That key is written by
   three unrelated views (`view_game`, `stats`, `stats_alltime`), always as
   `request.path`, and is never cleared. View a game, navigate away, edit a
   platform — you land back on the game. Query strings cannot survive it, so it
   can never return you to the list you were actually looking at.
2. **`HTTP_REFERER`** (`games/views/playevent.py:308`) — `delete_playevent`
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

## Non-goals

- No navigation history stack; one hop of origin, not a breadcrumb trail.
- No scroll-position restoration.
- Not converting confirmation modals into dedicated pages. That belongs to the
  HTMX-removal work, and this design does not preempt it.

## Design

### 1. The origin lives in the URL, and only in the URL

New module `common/returns.py`:

```python
type OriginUrl = str  # "/game/list?filter=%7B%22status%22%3A...%7D&page=3"
type UrlName = str    # "games:edit_game"

NEXT_PARAM = "next"

def action_url(viewname: UrlName, *args: Any, origin: OriginUrl | None, **kwargs: Any) -> str
def origin_from(request: HttpRequest, *, reject: str | None = None) -> OriginUrl | None
def return_url(
    request: HttpRequest,
    *,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    reject: str | None = None,
) -> str
```

`action_url` is `reverse()` plus `?next=<urlencoded origin>`. `origin` is
keyword-only with **no default**, so mypy rejects a call site that omits it; it
is nullable only so a chained view can forward "no origin" explicitly, in which
case the parameter is left off the URL entirely. Reversed URLs never carry a
query string of their own, so appending `?` is unconditional.

`origin_from` reads and validates `request.GET[NEXT_PARAM]`, returning `None`
when absent or rejected. `return_url` is `origin_from(...)` or
`reverse(fallback, args=fallback_args)`.

Validation, in order — a candidate must pass all of them:

1. `url_has_allowed_host_and_scheme(candidate, allowed_hosts=None)` — only
   root-relative URLs survive, which also rejects `//evil.com` and any scheme.
2. `resolve(urlparse(candidate).path)` must not raise `Resolver404` — kills
   injected garbage and stale bookmarks pointing at removed routes, so a
   successful mutation can never redirect into a 404.
3. `reject`, when given, must not equal `urlparse(candidate).path`.

### 2. Crossing the GET → POST boundary

No hidden form field. `AddForm`'s `<form>` carries no `action`
(`common/components/primitives.py:1538`), so the browser POSTs to the current
full path and `?next=` survives for free. Modal forms `hx_post` to an explicit
URL, which they build with `action_url`. One rule everywhere: the origin rides
the query string, never a form body, never the session — so `origin_from` reads
`request.GET` even when handling a POST.

### 3. Response shapes

Three kinds of mutating view, classified explicitly in `games/views/returns.py`:

```python
ORIGIN_AWARE: frozenset[UrlName]   # redirects (or sends HX-Redirect) when done
CONFIRMATION: frozenset[UrlName]   # GET; renders a confirm modal
IN_PLACE: frozenset[UrlName]       # answers with a partial swap; never redirects
```

- **`ORIGIN_AWARE`** ends with `redirect(return_url(request, fallback=...))`.
  Includes `split_purchase`, which sets an `HX-Redirect` header, and the two
  session-clone routes, whose htmx branch returns `HX-Refresh` (already stays
  put) but whose non-htmx branch redirects.
- **`CONFIRMATION`** views do not mutate; they forward the origin they were
  given into the modal form's post URL via `action_url`.
- **`IN_PLACE`** is `refund_purchase` alone: it swaps the table row and closes
  the modal out-of-band, so there is nothing to redirect.

Fallbacks stay literal at each `return_url` call, not in a central table,
because several are dynamic — the statuschange views fall back to
`games:view_game` with the affected game's id.

Guard test: every url name in `games.urls` matching
`^(add|edit|delete|drop|finish|refund|split)_` must appear in exactly one of the
three sets. A new mutating view fails the suite until it is classified.

### 4. Chained forms forward the origin

`add_purchase` with `submit_and_redirect` sends you on to
`add_session_for_game`. That is a chain, not a return: the second form is built
with `action_url(..., origin=origin_from(request))`, so the original origin
survives the hop and the eventual save lands where the user started.

### 5. Dead origins

A delete whose origin names the object being deleted would redirect into a 404.
Each delete view passes its own detail URL as `reject`, e.g.
`return_url(request, fallback="games:list_games", reject=reverse("games:view_game", args=[game_id]))`.
The view knows exactly what it destroyed, so this needs no guessing.

### 6. Stamping call sites

Each list and detail view computes `origin = request.get_full_path()` once, then
builds every action href through `action_url`. Row-button helpers
(`_render_purchase_buttons`, the game and platform `ButtonGroup` blocks,
`_game_action_buttons`) take a required `origin` parameter.

Backstop test, in the style of the existing `stats_links` parity tests: render
every list and detail page, walk each `href`, `hx-get` and `hx-post` attribute,
`resolve()` the path, and assert that any URL naming an `ORIGIN_AWARE` or
`CONFIRMATION` view carries a `next` equal to the rendering page's own full path.

## Delete hardening

Row deletes are currently plain GET `href`s that destroy on click — no
confirmation, and any prefetcher or crawler that follows one deletes data. Only
the game detail page confirms.

- Extract a generic `ConfirmationModal(*, title, body, post_url, confirm_label,
  request)` into `common/components/primitives.py`, beside the existing `Modal`,
  and port the three bespoke modals onto it (`_delete_game_confirmation_modal`,
  `_refund_confirmation_modal`, `_split_confirmation_modal`).
- Add confirmation views and `<entity>/<id>/delete/confirm` routes for the
  entities that lack them: purchase, session, playevent, platform, device,
  statuschange. Per-entity views remain, because the body copy differs
  (associated-data counts); only the markup is shared.
- Every delete view gains `@require_POST`. Row buttons become
  `hx_get=action_url("games:delete_X_confirmation", pk, origin=origin)` with
  `hx_target="#global-modal-container"`.

This drops the no-JS delete path. Acceptable: the modal flow is already the
detail-page pattern, and the project's direction treats JS as mandatory.

## Authentication hole found while classifying

`edit_playevent` and `delete_playevent` carry no `@login_required`, and the
project has no `LoginRequiredMiddleware`. An unauthenticated request can edit or
delete any play event. Verified by walking every `games.urls` callback; all
other views are protected.

Fixed here in its own commit, with a test that asserts every view reachable from
`games.urls` requires authentication, so the next omission fails the suite.

## Removals

- `use_custom_redirect` and its three `session["return_path"]` writes
  (`games/views/game.py:745`, `games/views/general.py:113`, `:128`).
- The `HTTP_REFERER` redirect in `delete_playevent`.
- The dead `redirect_to` and `add_next_param_to_url` in `common/utils.py`.
- The wrong canonical fallbacks: game flows now fall back to the games list,
  purchase flows to the purchases list, and so on.

## Testing

- **Unit** (`tests/test_returns.py`): `origin_from` and `return_url` against a
  foreign host, `//evil.com`, a `javascript:` scheme, a non-resolving path, a
  rejected origin, an absent parameter, and a valid filtered list URL.
- **Classification guard**: every mutating url name is in exactly one set.
- **Href parity**: every mutating link on every rendered page carries a correct
  `next`.
- **Auth sweep**: every `games.urls` view redirects an anonymous request to
  login.
- **Login interaction**: hitting an origin-carrying mutating URL while logged
  out double-nests `next` through Django's login redirect; assert the round trip
  lands on the original list.
- **E2E**: filter the games list, edit a game, save, assert the browser is back
  on the filtered URL with the filter intact; delete a game from its detail
  page, assert it lands on the games list rather than a 404.

## Commit sequence

Each commit leaves the tree green and shippable.

1. `fix(auth)`: `@login_required` on the two playevent views, plus the auth
   sweep test.
2. `feat(returns)`: `common/returns.py` and its unit tests. No callers yet.
3. `refactor(views)`: classification sets; every redirecting view consumes
   `return_url` with a correct fallback; delete `use_custom_redirect`, the
   session writes, the referrer redirect and the dead helpers. Behaviour after
   this commit is fallback-only — correct, just not yet origin-aware.
4. `feat(links)`: stamp origins at every call site via `action_url`; add the
   href parity test.
5. `refactor(components)`: extract `ConfirmationModal`; port the three existing
   modals.
6. `feat(deletes)`: confirmation views and POST-only deletes for the remaining
   entities.
7. `test(e2e)`: the filtered round trips.

## Risks

- **URL length.** A filtered list URL nested inside an edit URL reaches roughly
  1–2 KB with a large filter. Browsers and Django both accept well beyond that,
  and the alternative — a server-side token table — reintroduces exactly the
  stale state that caused this issue.
- **Ugly URLs.** Accepted deliberately in exchange for statelessness:
  bookmarkable, shareable, correct across multiple tabs.
