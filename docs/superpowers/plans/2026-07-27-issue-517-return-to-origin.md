# Return-to-origin redirects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After any mutating action, return the user to the exact page it was launched from — query string intact — instead of a session-remembered stale page or a hardcoded wrong list. No mutating route answers a GET.

**Architecture:** The origin URL travels in the query string (`?origin=<urlencoded full path>`) and nowhere else. `action_url()` stamps it onto every link to a mutating view; `return_url()` validates and consumes it, falling back to a per-view canonical list. Validation accepts only paths resolving to a route in the `READ_ONLY` bucket, so an origin can never launder a second mutation. Delete views become GET-confirm / POST-delete on a single URL, so the origin rides through the confirmation for free.

**Tech Stack:** Django 6 (function-based views), the project's Python component system (`common/components/`), pytest + pytest-django, Playwright for e2e.

Spec: `docs/superpowers/specs/2026-07-27-issue-517-return-to-origin-design.md`
Issue: https://github.com/KucharczykL/timetracker/issues/517

## Global Constraints

- **Everything runs through `make`.** Never `uv run` / `pytest` / `pnpm` directly. Focused runs: `make test ARGS="tests/test_returns.py -x"`. `ARGS` does **not** scope `make test-e2e` — it appends to `pytest e2e/`, so the whole e2e suite runs.
- **`make check` is the gate** before declaring any task done — lint, format-check, mypy, ts-check, vitest and the whole pytest suite including `e2e/`. Never gate on a subset.
- **Python 3.14 only.** A `SyntaxError` in an `except A, B:` line means the environment is on the wrong interpreter, not that the code is broken.
- **Build UI with the Python components** in `common.components`, never raw HTML strings or Django templates. Full-page responses use `render_page()` from `common.layout`, never Django's `render()`.
- **Never run e2e while `make dev` is up** — its watchers rewrite the served assets mid-run and produce mass phantom failures.
- **Name variables with complete words** — `element` not `el`, `origin_url` not `orig`.
- **Comments explain non-obvious intent only.** No references to issues, PRs, or "this used to be…" history.
- **Ruff fails on unused imports.** Every deletion step in this plan must also drop the imports it orphans; the specific ones are named where known.
- The app is mounted under `/tracker`, so `reverse("games:list_games")` yields `/tracker/game/list`.
- **`GameForm` requires `status`.** Any test POSTing to `add_game` / `edit_game` must include `"status": "u"` or the form is invalid, the view returns 200, and `response["Location"]` raises `KeyError`. See `tests/test_rendered_pages.py:262`.

---

## File Structure

**Created:**
- `common/returns.py` — the mechanism: `action_url`, `parse_origin`. Knows nothing about this app's routes.
- `games/views/returns.py` — the four-bucket route classification plus the bound `origin_from` / `return_url` that views and the layout import.
- `games/views/deletion.py` — `confirm_and_delete()`, the one delete flow every entity shares.
- `tests/test_returns.py`, `tests/test_returns_classification.py`, `tests/test_action_origin_parity.py`, `tests/test_view_authentication.py`, `tests/test_deletion_confirmation.py`, `e2e/test_return_to_origin_e2e.py`.

**Modified:** `games/views/{game,purchase,session,playevent,platform,device,statuschange,general}.py`, `common/layout.py`, `common/components/{primitives,domain}.py`, `common/utils.py`, `games/urls.py`, `CLAUDE.md`.

---

### Task 1: Close the unauthenticated playevent endpoints

`edit_playevent` and `delete_playevent` carry no `@login_required`, and there is no `LoginRequiredMiddleware`. Anyone can edit or delete any play event. Independent of the redirect work and shipped first.

**Files:**
- Modify: `games/views/playevent.py:282`, `games/views/playevent.py:306`
- Test: `tests/test_view_authentication.py` (create)

**Interfaces:**
- Consumes: nothing. Produces: nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_view_authentication.py`:

```python
"""Every view routed from games/urls.py must require authentication.

The Ninja API is covered separately by ``NinjaAPI(auth=django_auth)``
(games/api.py:52) and is not routed from games/urls.py.
"""

from datetime import date, datetime, timezone

import pytest
from django.conf import settings
from django.urls import reverse

from games import urls as games_urls
from games.models import (
    Device,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    Session,
)


@pytest.fixture
def world(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Test Game", platform=platform)
    purchase = Purchase.objects.create(
        date_purchased=date(2024, 6, 1), type=Purchase.GAME
    )
    purchase.games.set([game])
    return {
        "game_id": game.id,
        "purchase_id": purchase.id,
        "session_id": Session.objects.create(
            game=game, timestamp_start=datetime(2024, 6, 1, 12, tzinfo=timezone.utc)
        ).id,
        "playevent_id": PlayEvent.objects.create(game=game).id,
        "statuschange_id": GameStatusChange.objects.create(
            game=game, new_status="p"
        ).id,
        "device_id": Device.objects.create(name="Desk").id,
        "platform_id": platform.id,
        "year": 2024,
        "model": "game",
        "key": "DEFAULT_CURRENCY",
    }


def test_every_route_requires_login(client, world):
    world["pk"] = world["statuschange_id"]
    unprotected = []
    for pattern in games_urls.urlpatterns:
        if pattern.name is None:
            continue
        needed = pattern.pattern.regex.groupindex.keys()
        missing = [key for key in needed if key not in world]
        assert not missing, f"add a sample argument for {pattern.name}: {missing}"
        url = reverse(f"games:{pattern.name}", kwargs={k: world[k] for k in needed})
        response = client.get(url)
        redirects_to_login = response.status_code == 302 and settings.LOGIN_URL in (
            response["Location"]
        )
        if not redirects_to_login:
            unprotected.append(f"{pattern.name} -> {response.status_code}")
    assert unprotected == []
```

Note on coverage: `games/urls.py` appends the `settings_kit_preview*` routes only when `DEBUG` is true **at module import**, which under pytest is false. This test therefore covers the 49 production routes, not the two preview ones.

- [ ] **Step 2: Run it and watch it fail**

```bash
make test ARGS="tests/test_view_authentication.py -x"
```

Expected: FAIL listing `edit_playevent -> 200` and `delete_playevent -> 302` (the latter redirecting to the referrer fallback `/`, not to login).

- [ ] **Step 3: Add the decorators**

In `games/views/playevent.py`, add `@login_required` above `def edit_playevent` (line 282) and `def delete_playevent` (line 306), matching `add_playevent` at line 211.

- [ ] **Step 4: Run the test again**

```bash
make test ARGS="tests/test_view_authentication.py -x"
```

Expected: PASS.

- [ ] **Step 5: Full gate, then commit**

```bash
make check
```

```bash
git add games/views/playevent.py tests/test_view_authentication.py
git commit -m "fix(auth): require login to edit and delete play events"
```

---

### Task 2: The origin mechanism

**Files:**
- Create: `common/returns.py`
- Test: `tests/test_returns.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ORIGIN_PARAM: str` — `"origin"`.
  - `type OriginUrl = str`, `type UrlName = str`.
  - `action_url(viewname: UrlName, *args: Any, origin: OriginUrl | None, **kwargs: Any) -> str`
  - `parse_origin(request: HttpRequest, *, returnable: Container[UrlName], reject: str | None = None) -> OriginUrl | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_returns.py`:

```python
"""The origin mechanism: what may travel in ?origin=, and what must not."""

import pytest
from django.urls import reverse

from common.returns import ORIGIN_PARAM, action_url, parse_origin

RETURNABLE = frozenset({"games:list_games", "games:view_game"})
LIST_URL = "/tracker/game/list?page=3"


def _request(request_factory, origin_value=None):
    query = {ORIGIN_PARAM: origin_value} if origin_value is not None else {}
    return request_factory.get("/tracker/game/1/edit", query)


def test_action_url_appends_the_encoded_origin(db):
    assert action_url("games:edit_game", 1, origin=LIST_URL) == (
        reverse("games:edit_game", args=[1])
        + "?origin=%2Ftracker%2Fgame%2Flist%3Fpage%3D3"
    )


def test_action_url_without_an_origin_is_the_bare_url(db):
    assert action_url("games:edit_game", 1, origin=None) == reverse(
        "games:edit_game", args=[1]
    )


def test_valid_origin_survives(rf, db):
    assert parse_origin(_request(rf, LIST_URL), returnable=RETURNABLE) == LIST_URL


def test_absent_origin_is_none(rf, db):
    assert parse_origin(_request(rf), returnable=RETURNABLE) is None


@pytest.mark.parametrize(
    "candidate",
    [
        "https://evil.example/steal",
        "//evil.example/steal",
        "javascript:alert(1)",
        "/tracker/no-such-route",
        "",
    ],
)
def test_unsafe_or_unroutable_origins_are_rejected(rf, db, candidate):
    assert parse_origin(_request(rf, candidate), returnable=RETURNABLE) is None


@pytest.mark.parametrize(
    "candidate",
    ["/tracker/game/1/delete", "/api/games/search", "/logout/"],
)
def test_origins_outside_the_returnable_set_are_rejected(rf, db, candidate):
    """A resolving path is not enough: a mutating target would let a crafted
    link launder the user's confirming POST into a second mutation."""
    assert parse_origin(_request(rf, candidate), returnable=RETURNABLE) is None


def test_an_embedded_newline_is_stripped_not_passed_through(rf, db):
    """Django validates the stripped URL; returning the raw one would raise
    BadHeaderError in redirect() after the mutation had already committed."""
    parsed = parse_origin(_request(rf, "\n" + LIST_URL), returnable=RETURNABLE)
    assert parsed == LIST_URL


def test_rejected_path_is_dropped(rf, db):
    detail = reverse("games:view_game", args=[1])
    assert parse_origin(_request(rf, detail), returnable=RETURNABLE, reject=detail) is None
    assert parse_origin(_request(rf, detail), returnable=RETURNABLE) == detail
```

- [ ] **Step 2: Run them and watch them fail**

```bash
make test ARGS="tests/test_returns.py -x"
```

Expected: FAIL with `ModuleNotFoundError: No module named 'common.returns'`.

- [ ] **Step 3: Write the module**

Create `common/returns.py`:

```python
"""Carrying the page a mutating action was launched from, and coming back to it.

The origin rides the query string and nowhere else — not the session, not a
form body — so it survives GET->POST (forms without an ``action`` re-post to the
current full path), multiple tabs, and bookmarking.

The parameter is ``origin`` rather than ``next`` because Django's auth views own
``next``: on /login/ it means "where to go after authenticating", and a mutating
view has no way to tell that apart from "where to go after this mutation".
"""

from collections.abc import Container, Sequence
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

from django.http import HttpRequest
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

type OriginUrl = str  # "/tracker/game/list?filter=%7B%22status%22%3A%5B%22p%22%5D%7D"
type UrlName = str  # "games:edit_game"

ORIGIN_PARAM = "origin"


def action_url(
    viewname: UrlName, *args: Any, origin: OriginUrl | None, **kwargs: Any
) -> str:
    """Link to a mutating view, carrying the page it is launched from.

    ``origin`` is keyword-only and has no default so a call site cannot drop it
    by accident; pass ``None`` only where there is genuinely nowhere to return.
    """
    url = reverse(viewname, args=args, kwargs=kwargs)
    if not origin:
        return url
    # reverse() never yields a query string, so "?" is unconditional.
    return f"{url}?{urlencode({ORIGIN_PARAM: origin})}"


def parse_origin(
    request: HttpRequest,
    *,
    returnable: Container[UrlName],
    reject: str | None = None,
) -> OriginUrl | None:
    """The origin this request carries, or None if absent or untrustworthy.

    ``returnable`` is the set of url names a user may be sent back to — read-only
    pages. Accepting any resolvable path instead would let a crafted origin turn
    the user's confirming POST into a server-issued GET redirect that mutates
    again, and would happily redirect a finished mutation at a JSON endpoint or
    the POST-only logout route.

    ``reject`` drops an origin naming a page that is about to stop existing — a
    delete view passes the detail URL of the object it is deleting. This narrows
    the 404-after-delete window but cannot close it: resolve() proves the route
    exists, never the object.
    """
    candidate = request.GET.get(ORIGIN_PARAM)
    if not candidate:
        return None
    # allowed_hosts=None admits root-relative URLs only, which also turns away
    # "//evil.example" and every non-http scheme.
    if not url_has_allowed_host_and_scheme(candidate, allowed_hosts=None):
        return None
    # Django validated the stripped form; anything else would smuggle control
    # characters into a Location header and 500 after the mutation committed.
    parts = urlparse(candidate.strip())
    # PATH_INFO, which is what resolve() wants. Identical to get_full_path()'s
    # path here because the /tracker prefix comes from the urlconf rather than
    # FORCE_SCRIPT_NAME; a sub-path deployment would need to strip SCRIPT_NAME.
    try:
        match = resolve(parts.path)
    except Resolver404:
        return None
    if f"{match.app_name}:{match.url_name}" not in returnable:
        return None
    if reject is not None and parts.path == reject:
        return None
    return urlunparse(parts)
```

- [ ] **Step 4: Run the tests**

```bash
make test ARGS="tests/test_returns.py -v"
```

Expected: 16 PASS (two parametrized cases expand to five and three).

- [ ] **Step 5: Full gate, then commit**

```bash
make check
```

```bash
git add common/returns.py tests/test_returns.py
git commit -m "feat(returns): add the origin-carrying URL mechanism"
```

---

### Task 3: Classify every route

**Files:**
- Create: `games/views/returns.py`
- Test: `tests/test_returns_classification.py` (create)

**Interfaces:**
- Consumes: `common.returns.{OriginUrl, UrlName, parse_origin}`.
- Produces:
  - `READ_ONLY`, `ORIGIN_AWARE`, `CONFIRMATION`, `IN_PLACE`, `DEBUG_ONLY` — `frozenset[UrlName]`.
  - `origin_from(request, *, reject: str | None = None) -> OriginUrl | None`
  - `return_url(request, *, fallback: UrlName, fallback_args: Sequence[Any] = (), reject: str | None = None) -> str`

- [ ] **Step 1: Write the failing guard test**

Create `tests/test_returns_classification.py`:

```python
"""Every routed name is classified exactly once.

Guarding on a name prefix (add_/edit_/delete_/…) does not hold: the session
clone route is named for where it is launched from, and a future clone_/reset_/
archive_ route would pass silently. Completeness against the real route table
has no such hole, and READ_ONLY doubles as the origin allow-list.
"""

from games import urls as games_urls
from games.views.returns import (
    CONFIRMATION,
    DEBUG_ONLY,
    IN_PLACE,
    ORIGIN_AWARE,
    READ_ONLY,
)

BUCKETS = {
    "READ_ONLY": READ_ONLY,
    "ORIGIN_AWARE": ORIGIN_AWARE,
    "CONFIRMATION": CONFIRMATION,
    "IN_PLACE": IN_PLACE,
}


def _routed_names() -> set[str]:
    return {
        f"games:{pattern.name}"
        for pattern in games_urls.urlpatterns
        if pattern.name is not None
    }


def test_every_routed_name_is_classified():
    classified = set().union(*BUCKETS.values())
    assert _routed_names() - classified == set()


def test_classifications_name_only_real_routes():
    classified = set().union(*BUCKETS.values())
    # The settings-kit preview routes exist only when DEBUG was true at import.
    assert classified - _routed_names() <= DEBUG_ONLY


def test_no_name_is_in_two_buckets():
    seen: dict[str, str] = {}
    for bucket_name, names in BUCKETS.items():
        for name in names:
            assert name not in seen, f"{name} in {seen.get(name)} and {bucket_name}"
            seen[name] = bucket_name
```

- [ ] **Step 2: Run it and watch it fail**

```bash
make test ARGS="tests/test_returns_classification.py -x"
```

Expected: FAIL with `ModuleNotFoundError: No module named 'games.views.returns'`.

- [ ] **Step 3: Write the classification**

Create `games/views/returns.py`. The four sets below are the route table as it stands **before** Task 4's deletions; Task 4 removes `drop_purchase`, `finish_purchase` and `view_game_start_session_from_session`, and Task 6 removes `delete_game_confirmation`. Each of those tasks deletes the corresponding entry here in the same commit.

```python
"""Which routes mutate, how each answers when it is done, and where a user may
be sent back to.

tests/test_returns_classification.py fails until a newly routed name appears in
exactly one bucket, so a new view cannot slip in unclassified.
"""

from collections.abc import Sequence
from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from common.returns import OriginUrl, UrlName, parse_origin

# Renders a page and changes nothing. The only URLs a mutation may return to.
READ_ONLY: frozenset[UrlName] = frozenset(
    {
        "games:admin_settings",
        "games:export_admin_settings_ini",
        "games:filter_builder",
        "games:index",
        "games:list_devices",
        "games:list_games",
        "games:list_platforms",
        "games:list_playevents",
        "games:list_purchases",
        "games:list_sessions",
        "games:list_statuschanges",
        "games:settings",
        "games:settings_kit_preview",
        "games:stats_alltime",
        "games:stats_by_year",
        "games:view_game",
        "games:view_purchase",
    }
)

# Mutates, then redirects (or sends HX-Redirect); consumes an origin.
ORIGIN_AWARE: frozenset[UrlName] = frozenset(
    {
        "games:add_device",
        "games:add_game",
        "games:add_platform",
        "games:add_playevent",
        "games:add_playevent_for_game",
        "games:add_purchase",
        "games:add_purchase_for_game",
        "games:add_session",
        "games:add_session_for_game",
        "games:add_statuschange",
        "games:delete_device",
        "games:delete_game",
        "games:delete_platform",
        "games:delete_playevent",
        "games:delete_purchase",
        "games:delete_session",
        "games:delete_statuschange",
        "games:edit_device",
        "games:edit_game",
        "games:edit_platform",
        "games:edit_playevent",
        "games:edit_purchase",
        "games:edit_session",
        "games:edit_statuschange",
        "games:list_sessions_start_session_from_session",
        "games:split_purchase",
        # Deleted in Task 4 (GET-mutating, no callers anywhere):
        "games:drop_purchase",
        "games:finish_purchase",
        "games:view_game_start_session_from_session",
    }
)

# GET only: renders a confirmation and forwards the origin to the form it draws.
CONFIRMATION: frozenset[UrlName] = frozenset(
    {
        "games:refund_purchase_confirmation",
        "games:split_purchase_confirmation",
        # Deleted in Task 6, replaced by a confirmation page:
        "games:delete_game_confirmation",
    }
)

# Mutates and answers with a partial swap, leaving the user where they are.
IN_PLACE: frozenset[UrlName] = frozenset(
    {
        "games:refund_purchase",
        "games:settings_kit_preview_patch",
    }
)

# Routed only when DEBUG was true at games/urls.py import time.
DEBUG_ONLY: frozenset[UrlName] = frozenset(
    {"games:settings_kit_preview", "games:settings_kit_preview_patch"}
)


def origin_from(
    request: HttpRequest, *, reject: str | None = None
) -> OriginUrl | None:
    """The read-only page this request was launched from, if it carries one."""
    return parse_origin(request, returnable=READ_ONLY, reject=reject)


def return_url(
    request: HttpRequest,
    *,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    reject: str | None = None,
) -> str:
    """Where a finished mutation should send the user."""
    return origin_from(request, reject=reject) or reverse(
        fallback, args=list(fallback_args)
    )
```

- [ ] **Step 4: Run the guard**

```bash
make test ARGS="tests/test_returns_classification.py -v"
```

Expected: 3 PASS.

- [ ] **Step 5: Full gate, then commit**

```bash
make check
```

```bash
git add games/views/returns.py tests/test_returns_classification.py
git commit -m "feat(returns): classify every route and bind the origin allow-list"
```

---

### Task 4: Views consume the origin; GET-mutating routes go

After this task nothing *stamps* an origin yet, so behaviour is fallback-only — correct, just not yet origin-aware.

**Files:**
- Modify: `games/views/general.py` (drop `use_custom_redirect`, two session writes), `games/views/game.py`, `games/views/purchase.py`, `games/views/session.py`, `games/views/playevent.py`, `games/views/platform.py`, `games/views/device.py`, `games/views/statuschange.py`, `games/views/returns.py`, `games/urls.py`, `common/utils.py`, `common/layout.py:399`
- Test: `tests/test_returns_views.py` (create)

**Interfaces:**
- Consumes: `common.returns.action_url`, `games.views.returns.{origin_from, return_url}`.
- Produces: nothing new; every `ORIGIN_AWARE` view now honours an origin.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_returns_views.py`:

```python
"""Mutating views honour a carried origin and fall back correctly."""

import pytest
from django.urls import reverse

from common.returns import action_url
from games.models import Game

GAME_FORM = {"name": "Renamed", "status": "u"}


@pytest.fixture
def logged_in(client, django_user_model, db):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


@pytest.fixture
def game(db):
    return Game.objects.create(name="Test Game")


def test_edit_game_falls_back_to_the_games_list(logged_in, game):
    response = logged_in.post(reverse("games:edit_game", args=[game.id]), GAME_FORM)
    assert response["Location"] == reverse("games:list_games")


def test_edit_game_returns_to_the_carried_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=3"
    response = logged_in.post(
        action_url("games:edit_game", game.id, origin=origin), GAME_FORM
    )
    assert response["Location"] == origin


def test_a_chained_form_forwards_the_origin(logged_in, db):
    origin = f"{reverse('games:list_games')}?page=3"
    response = logged_in.post(
        action_url("games:add_game", origin=origin),
        {"name": "Chained", "status": "u", "submit_and_create_session": "1"},
    )
    created = Game.objects.get(name="Chained")
    assert response["Location"] == action_url(
        "games:add_session_for_game", game_id=created.id, origin=origin
    )


def test_the_origin_survives_the_login_redirect(client, django_user_model, game):
    origin = f"{reverse('games:list_games')}?page=3"
    target = action_url("games:edit_game", game.id, origin=origin)
    anonymous = client.get(target)
    assert anonymous.status_code == 302
    login_url = anonymous["Location"]

    django_user_model.objects.create_user(username="u", password="p")
    client.post(login_url, {"username": "u", "password": "p"})
    assert client.get(target).status_code == 200
    assert client.post(target, GAME_FORM)["Location"] == origin


@pytest.mark.parametrize(
    "url_name", ["games:drop_purchase", "games:finish_purchase",
                 "games:view_game_start_session_from_session"]
)
def test_the_get_mutating_routes_are_gone(url_name):
    from django.urls import NoReverseMatch

    with pytest.raises(NoReverseMatch):
        reverse(url_name, args=[1])
```

- [ ] **Step 2: Run them and watch them fail**

```bash
make test ARGS="tests/test_returns_views.py -x"
```

Expected: FAIL — `edit_game` redirects to the sessions list, the origin is ignored, and the three doomed routes still reverse.

- [ ] **Step 3: Convert every redirecting view**

Every module below adds:

```python
from common.returns import action_url
from games.views.returns import origin_from, return_url
```

`action_url` is needed in `game.py` and `purchase.py` in this task (the chained branches); the other modules need only the two from `games.views.returns`.

`games/views/game.py` — drop the `use_custom_redirect` import (line 68) and decorator:

```python
@login_required
def edit_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = get_object_or_404(Game, id=game_id)
    form = GameForm(request.POST or None, instance=game)
    if form.is_valid():
        form.save()
        return redirect(return_url(request, fallback="games:list_games"))
    ...
```

(The local was misnamed `purchase = get_object_or_404(Game, ...)`; rename it `game` as above.)

```python
@login_required
def delete_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = get_object_or_404(Game, id=game_id)
    detail_url = reverse("games:view_game", args=[game_id])
    game.delete()
    return redirect(
        return_url(request, fallback="games:list_games", reject=detail_url)
    )
```

```python
@login_required
def add_game(request: HttpRequest) -> HttpResponse:
    form = GameForm(request.POST or None)
    if form.is_valid():
        game = form.save()
        origin = origin_from(request)
        if "submit_and_redirect" in request.POST:
            return redirect(
                action_url("games:add_purchase_for_game", game_id=game.id, origin=origin)
            )
        elif "submit_and_create_session" in request.POST:
            return redirect(
                action_url("games:add_session_for_game", game_id=game.id, origin=origin)
            )
        return redirect(return_url(request, fallback="games:list_games"))
    ...
```

Also delete the `request.session["return_path"] = request.path` line in `view_game` (line 745).

`games/views/purchase.py` — drop the `use_custom_redirect` import and decorator, then:

- `add_purchase`: the `pricing_mode == "per_game"` branch and the plain branch become `return redirect(return_url(request, fallback="games:list_purchases"))`; the `submit_and_redirect` branch becomes `return redirect(action_url("games:add_session_for_game", game_id=purchase.first_game.id, origin=origin_from(request)))`.
- `edit_purchase`: `return redirect(return_url(request, fallback="games:list_purchases"))`.
- `delete_purchase`:

```python
@login_required
def delete_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    detail_url = reverse("games:view_purchase", args=[purchase_id])
    purchase.delete()
    return redirect(
        return_url(request, fallback="games:list_purchases", reject=detail_url)
    )
```

- `split_purchase` keeps its `HX-Redirect` shape. Reject the source detail URL **only when the split actually happened** — the view guards on `if count > 1`, and an unsplit purchase's detail page still exists:

```python
    response = HttpResponse(status=204)
    response["HX-Redirect"] = return_url(
        request,
        fallback="games:list_purchases",
        reject=reverse("games:view_purchase", args=[purchase_id]) if count > 1 else None,
    )
    return response
```

- Delete `drop_purchase` (lines 466–472) and `finish_purchase` (lines 607–613) entirely.

`games/views/session.py`: `add_session`, `edit_session` and `delete_session` use `return redirect(return_url(request, fallback="games:list_sessions"))`. Replace `new_session_from_existing_session` with a POST-only view and drop its dead `HX-Refresh` branch (its only caller is a plain navbar link, so `request.htmx` is never true):

```python
@login_required
@require_POST
def new_session_from_existing_session(
    request: HttpRequest, session_id: int
) -> HttpResponse:
    clone_session_by_id(session_id)
    return redirect(return_url(request, fallback="games:list_sessions"))
```

`games/views/playevent.py`:

```python
    if form.is_valid():
        form.save()
        if not game_id:
            game_id = form.instance.game.id
        return redirect(
            return_url(request, fallback="games:view_game", fallback_args=[game_id])
        )
```

`edit_playevent` uses `fallback_args=[playevent.game.id]`. `delete_playevent` loses the `HTTP_REFERER` redirect at line 309:

```python
@login_required
def delete_playevent(request: HttpRequest, playevent_id: int) -> HttpResponse:
    playevent = get_object_or_404(PlayEvent, id=playevent_id)
    game_id = playevent.game.id
    playevent.delete()
    return redirect(
        return_url(request, fallback="games:view_game", fallback_args=[game_id])
    )
```

`games/views/platform.py`: drop the `use_custom_redirect` import and decorator; `add_platform`, `edit_platform` and `delete_platform` all fall back to `games:list_platforms` (`add_platform` previously went to `games:index`).

`games/views/device.py`: `add_device`, `edit_device` and `delete_device` all fall back to `games:list_devices` (previously `games:index` and `games:list_sessions`).

`games/views/statuschange.py`: `add_statuschange` and `edit_statuschange` use `fallback="games:view_game"` with `fallback_args=[obj.game.id]` / `[saved.game.id]`; the POST branch of `delete_statuschange` uses `fallback_args=[game_id]`.

- [ ] **Step 4: Make the navbar resume item a POST**

In `common/layout.py:399`, the resume dropdown item becomes a `DropdownPostItem` (`common/components/custom_elements.py:841`), which renders a CSRF-protected POST form. `NavbarLogButton` already receives `csrf_token` through `NavbarMenu`; thread it in if the signature lacks it.

- [ ] **Step 5: Delete the routes and the superseded mechanisms**

In `games/urls.py`, remove the `drop_purchase`, `finish_purchase` and `view_game_start_session_from_session` routes. In `games/views/returns.py`, remove those three names from `ORIGIN_AWARE`.

In `games/views/general.py`, delete the whole `use_custom_redirect` function (lines **93–108**) and the `request.session["return_path"] = request.path` lines in `stats_alltime` (113) and `stats` (128). `Callable` (imported at line 3) is then unused — remove it. `HttpResponseRedirect` is still used at lines 123 and 127; keep it.

In `common/utils.py`, delete `redirect_to` (lines 156–182) and `add_next_param_to_url` (185–186). `wraps` (line 3), `redirect` and `urlencode` become unused — remove all three.

- [ ] **Step 6: Prove the dead code is gone**

```bash
grep -rn "use_custom_redirect\|return_path\|redirect_to\|add_next_param_to_url\|drop_purchase\|finish_purchase" games/ common/ tests/ e2e/
```

Expected: no output.

```bash
grep -rn "HTTP_REFERER" games/ common/ e2e/
```

Expected: no output. (`tests/test_config.py:279` also matches `HTTP_REFERER` but is an unrelated CSRF/`APP_URL` test — hence excluding `tests/` from this second grep.)

- [ ] **Step 7: Run the tests**

```bash
make test ARGS="tests/test_returns_views.py tests/test_returns_classification.py -v"
```

Expected: all PASS.

- [ ] **Step 8: Full gate, then commit**

```bash
make check
```

Known casualty: `tests/test_purchase_separate_orders.py:102` asserts split's `HX-Redirect` equals the bare purchases list — it passes unchanged, since that request carries no origin. If any other test asserts a post-mutation `Location`, update it to the new canonical target and note it in the commit body.

```bash
git add games common/utils.py common/layout.py tests/test_returns_views.py
git commit -m "refactor(views): resolve mutating redirects from the request, not the session"
```

---

### Task 5: Stamp the origin on every mutating link

**Files:**
- Modify: `common/layout.py` (`Page`, `Navbar`, `NavbarMenu`, `entity_submenu`, `NavbarLogButton`), `common/components/domain.py:338` (`SessionActions`), `games/views/session.py:48` (`session_row_data`), `games/views/game.py` (list rows, `_game_header`, `_played_row`, `_game_action_buttons`, `_purchases_section`, `_playevents_section`, `_history_section`), `games/views/purchase.py` (`_render_purchase_buttons`, `_render_purchase_row`, the two confirmation modals and their views), `games/views/platform.py:74`, `games/views/device.py:72`, `games/views/playevent.py:98`
- Test: `tests/test_action_origin_parity.py` (create), `tests/test_origin_partials.py` (create)

**Interfaces:**
- Consumes: `common.returns.{OriginUrl, action_url}`, `games.views.returns.{CONFIRMATION, ORIGIN_AWARE, READ_ONLY, origin_from}`.
- Produces: every row builder gains a required keyword-only `origin: OriginUrl | None` — `SessionActions(session, csrf_token, origin)`, `session_row_data(..., *, origin)`, `_render_purchase_buttons(..., *, origin)`, `_render_purchase_row(..., *, origin)`, `create_playevent_tabledata(..., *, origin)`, `_game_action_buttons(game, origin)`, `_played_row(..., origin)`.

- [ ] **Step 1: Write the failing parity test**

Create `tests/test_action_origin_parity.py`:

```python
"""Every link to a mutating view carries the page it was rendered on.

A row's Edit button must come back to the filtered, sorted, paginated list the
user was actually looking at, which only works if the page stamped its own full
path onto the link. Form actions count: the delete-confirmation POST target is
the single most important URL in the mechanism.
"""

import html
import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import Resolver404, resolve, reverse

from games.models import Device, Game, Platform, PlayEvent, Purchase, Session
from games.views.returns import CONFIRMATION, ORIGIN_AWARE

LINK_ATTRIBUTE = re.compile(r'\b(?:href|hx-get|hx-post|action)="([^"]*)"')
MUST_CARRY_ORIGIN = ORIGIN_AWARE | CONFIRMATION


@pytest.fixture
def world(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Test Game", platform=platform)
    purchase = Purchase.objects.create(
        date_purchased=date(2024, 6, 1), type=Purchase.GAME
    )
    purchase.games.set([game])
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2024, 6, 1, 12, tzinfo=timezone.utc),
        device=Device.objects.create(name="Desk"),
    )
    PlayEvent.objects.create(game=game)
    return game


def _missing_origin(body: str, page_path: str) -> list[str]:
    failures = []
    for raw in LINK_ATTRIBUTE.findall(body):
        url = html.unescape(raw)
        if not url.startswith("/"):
            continue
        parsed = urlparse(url)
        try:
            match = resolve(parsed.path)
        except Resolver404:
            continue
        name = f"{match.app_name}:{match.url_name}"
        if name not in MUST_CARRY_ORIGIN:
            continue
        carried = parse_qs(parsed.query).get("origin", [])
        if carried != [page_path]:
            failures.append(f"{name} carried {carried!r}, expected [{page_path!r}]")
    return failures


@pytest.mark.parametrize(
    "url_name",
    [
        "games:list_games",
        "games:list_sessions",
        "games:list_purchases",
        "games:list_playevents",
        "games:list_platforms",
        "games:list_devices",
        "games:list_statuschanges",
    ],
)
def test_list_pages_stamp_their_own_path(client, django_user_model, world, url_name):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    page_path = reverse(url_name) + "?page=1"
    response = client.get(page_path)
    assert response.status_code == 200
    assert _missing_origin(response.content.decode(), page_path) == []


@pytest.mark.parametrize("url_name", ["games:view_game", "games:view_purchase"])
def test_detail_pages_stamp_their_own_path(
    client, django_user_model, world, url_name
):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    target = world if url_name == "games:view_game" else world.purchases.first()
    page_path = reverse(url_name, args=[target.id])
    response = client.get(page_path)
    assert response.status_code == 200
    assert _missing_origin(response.content.decode(), page_path) == []


def test_a_form_page_stamps_no_origin_on_its_navbar(client, django_user_model, world):
    """There is nothing to return to from a form, and an origin naming one would
    be refused by the READ_ONLY allow-list anyway."""
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    body = client.get(reverse("games:edit_game", args=[world.id])).content.decode()
    assert "origin=" not in body
```

- [ ] **Step 2: Run it and watch it fail**

```bash
make test ARGS="tests/test_action_origin_parity.py -x"
```

Expected: FAIL listing the six navbar `add_*` links plus the row actions, on every page.

- [ ] **Step 3: Stamp the navbar**

`Page()` (`common/layout.py:515`) already has the request. Compute the origin there and pass it down, stamping only on read-only pages:

```python
    from games.views.returns import READ_ONLY

    match = resolve(request.path)
    current_name = f"{match.app_name}:{match.url_name}"
    navbar_origin = request.get_full_path() if current_name in READ_ONLY else None
```

Thread `origin=navbar_origin` into `Navbar(...)`, which forwards it to `NavbarMenu` and `NavbarLogButton`. Inside `NavbarMenu`, `entity_submenu` stamps its add link:

```python
    def entity_submenu(label, slug, add_url, list_url):
        return DropdownSubmenu(
            label,
            id=f"navbarMenu{slug}",
            items=[
                DropdownLinkItem(
                    action_url(add_url, origin=origin), f"Add {label.lower()}"
                ),
                DropdownLinkItem(reverse(list_url), f"List {label.lower()}s"),
            ],
        )
```

and `NavbarLogButton`'s primary becomes `href=action_url("games:add_session", origin=origin)`. The resume items (now `DropdownPostItem` from Task 4) take `action_url("games:list_sessions_start_session_from_session", session.pk, origin=origin)`.

- [ ] **Step 4: Stamp the list-view rows**

Each list view takes `origin = request.get_full_path()` once and builds every action through `action_url`. `games/views/game.py`, in `list_games`:

```python
                ButtonGroup(
                    [
                        {
                            "href": action_url(
                                "games:edit_game", game.pk, origin=origin
                            ),
                            "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                            "color": "gray",
                        },
                        {
                            "href": action_url(
                                "games:delete_game", game.pk, origin=origin
                            ),
                            "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                            "color": "red",
                        },
                    ]
                ),
```

Apply the same transformation — swapping `reverse(...)` for `action_url(..., origin=origin)` and nothing else — at `games/views/platform.py:77,82` (note: those two members use bare `Icon("edit")` / `Icon("delete")` with no `size=`; leave the icons alone), `games/views/device.py:75,80`, and `games/views/playevent.py:101,106`.

- [ ] **Step 5: Thread the shared row builders**

`common/components/domain.py:338` — `SessionActions(session, csrf_token: str, origin: OriginUrl | None)`; its Edit and Delete members use `action_url`. Its only caller is `session_row_data` (`games/views/session.py:48`, calling at line 63), which gains `*, origin` and forwards it; `list_sessions` (line 106) supplies `request.get_full_path()`.

`games/views/purchase.py` — `_render_purchase_buttons(purchase_id, is_refunded, can_split=False, *, origin: OriginUrl | None)` stamps all four members, the two `hx_get` confirmation URLs included:

```python
            {
                "href": "#",
                "hx_get": action_url(
                    "games:refund_purchase_confirmation", purchase_id, origin=origin
                ),
                "hx_target": "#global-modal-container",
                "slot": Icon("refund", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Mark as refunded",
            }
```

`_render_purchase_row(purchase, presentation, *, origin)` forwards it. Its two callers are `list_purchases` (line 196, `request.get_full_path()`) and `refund_purchase` (line 524, `origin_from(request)`).

`games/views/playevent.py` — `create_playevent_tabledata(..., *, origin)`; callers are `list_playevents` (line 178) and `games/views/game.py:686`.

- [ ] **Step 6: Forward the origin through the two htmx confirmation modals**

Without this, `refund_purchase` and `split_purchase` never see an origin — the modal posts to a bare URL, so the row refund swaps back in loses the stamps its neighbours have and split always falls back.

`games/views/purchase.py:475` and `:534`, both modal builders gain `origin` and use it in the form's post target:

```python
def _refund_confirmation_modal(
    purchase_id: int, request: HttpRequest, origin: OriginUrl | None
) -> Node:
    form = Form(
        hx_post=action_url("games:refund_purchase", purchase_id, origin=origin),
        hx_target=f"#purchase-row-{purchase_id}",
        hx_swap="outerHTML",
    )[
```

Their views (`refund_purchase_confirmation` line 506, `split_purchase_confirmation` line 566) pass `origin_from(request)`.

- [ ] **Step 7: Stamp the game detail page**

`view_game` computes `origin = request.get_full_path()` once and passes it to the section builders. The real call graph, verified against the code:

- `_game_header` → `_game_action_buttons(game, origin)` (stamps `add_session_for_game`, `edit_game`, and the delete link) **and** `_played_row(..., origin)` (line 592), which stamps `games:add_playevent` at line 344 and `games:add_playevent_for_game` at line 358. `_played_row` was missing from an earlier draft of this plan.
- `_purchases_section` builds its **own** inline `ButtonGroup` at lines 619 and 624 — it does **not** call `_render_purchase_row`. Stamp those two `reverse()` calls directly.
- `_playevents_section` → `create_playevent_tabledata(..., origin=origin)`.
- `_history_section` → `_game_history(..., origin)`, whose statuschange links at lines 445–447 become:

```python
        edit = A(
            href=action_url("games:edit_statuschange", change.id, origin=origin)
        )["Edit"]
        delete = A(
            href=action_url("games:delete_statuschange", change.id, origin=origin)
        )["Delete"]
```

- `_sessions_section` renders **no** action buttons — Date, Duration and Device only — and `tests/test_game_detail_links.py:96` (`test_sessions_section_is_read_only`) asserts exactly that. Do **not** add `SessionActions` there; it needs no `origin`.

- [ ] **Step 8: Write the partial-flow tests the parity backstop cannot reach**

Create `tests/test_origin_partials.py`:

```python
"""Htmx partials carry the origin too — the parity backstop cannot see them,
because the page they render into is not the page they were requested from."""

from datetime import date

import pytest
from django.urls import reverse

from common.returns import action_url
from games.models import Game, Purchase

ORIGIN = "/tracker/purchase/list?page=2"


@pytest.fixture
def purchase(db):
    game = Game.objects.create(name="Bundled")
    other = Game.objects.create(name="Also bundled")
    purchase = Purchase.objects.create(
        date_purchased=date(2024, 6, 1), type=Purchase.GAME, price=10
    )
    purchase.games.set([game, other])
    return purchase


@pytest.fixture
def logged_in(client, django_user_model, db):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


def test_the_refund_modal_posts_with_the_origin(logged_in, purchase):
    body = logged_in.get(
        action_url("games:refund_purchase_confirmation", purchase.id, origin=ORIGIN)
    ).content.decode()
    assert "origin=%2Ftracker%2Fpurchase%2Flist%3Fpage%3D2" in body


def test_the_refunded_row_keeps_the_origin(logged_in, purchase):
    body = logged_in.post(
        action_url("games:refund_purchase", purchase.id, origin=ORIGIN)
    ).content.decode()
    assert "origin=%2Ftracker%2Fpurchase%2Flist%3Fpage%3D2" in body


def test_split_redirects_to_the_origin(logged_in, purchase):
    response = logged_in.post(
        action_url("games:split_purchase", purchase.id, origin=ORIGIN)
    )
    assert response["HX-Redirect"] == ORIGIN
```

- [ ] **Step 9: Run both test files**

```bash
make test ARGS="tests/test_action_origin_parity.py tests/test_origin_partials.py -v"
```

Expected: all PASS.

- [ ] **Step 10: Full gate, then commit**

```bash
make check
```

Known casualties, both from the new required `origin` argument:

- `tests/test_components.py:305` and `:324` call `SessionActions(self._session(), "tok123")` positionally — add a third argument (`None` is correct there).
- `tests/test_game_detail_links.py:90` asserts a bare `reverse("games:add_session_for_game", …)` string is present; it still passes because `?origin=` is a suffix. Leave it, but confirm rather than assume.

```bash
git add games common/layout.py common/components/domain.py tests
git commit -m "feat(links): carry the origin page on every mutating link"
```

---

### Task 6: Game delete becomes a confirmation page

**Files:**
- Create: `games/views/deletion.py`
- Modify: `common/components/primitives.py:1657` (`ConfirmPage`), `games/views/statuschange.py:90`, `games/views/game.py` (delete the modal, its view; rewrite `delete_game`), `games/urls.py` (lines **38–42**), `games/views/returns.py` (drop `delete_game_confirmation`), `tests/test_rendered_pages.py:437`, `tests/test_html_validity.py`
- Test: `tests/test_components.py` (extend), `tests/test_deletion_confirmation.py` (create)

**Interfaces:**
- Consumes: `common.returns.action_url`, `games.views.returns.return_url`.
- Produces:
  - `ConfirmPage(*, title, message, post_url, csrf_token, cancel_url, confirm_label="Confirm", confirm_color="red", details: Children = None) -> Node`
  - `confirm_and_delete(request, instance, *, title, message, fallback, fallback_args=(), details=None, detail_url=None) -> HttpResponse` — the shared flow, introduced here with its first caller so `delete_game` is not written twice.

- [ ] **Step 1: Write the failing component test**

Append to `tests/test_components.py`:

```python
def test_confirm_page_renders_details_outside_the_message_paragraph():
    from common.components import ConfirmPage, Li, Ul

    markup = str(
        ConfirmPage(
            title="Delete game",
            message="Permanently delete this game?",
            post_url="/tracker/game/1/delete?origin=%2Ftracker%2Fgame%2Flist",
            csrf_token="token",
            cancel_url="/tracker/game/list",
            confirm_label="Delete",
            details=Ul()[Li()["2 session(s)"]],
        )
    )
    assert 'action="/tracker/game/1/delete?origin=%2Ftracker%2Fgame%2Flist"' in markup
    # A <ul> inside the message <p> would be invalid HTML.
    before_list = markup.split("<ul")[0]
    assert "<p" in before_list and "</p>" in before_list
```

- [ ] **Step 2: Run it and watch it fail**

```bash
make test ARGS="tests/test_components.py -k confirm_page_renders_details -x"
```

Expected: FAIL with `TypeError: ConfirmPage() got an unexpected keyword argument 'post_url'`.

- [ ] **Step 3: Extend ConfirmPage**

In `common/components/primitives.py`, rename the `action_url` parameter to `post_url` (it would otherwise read as a call to the new helper) and add the block slot after the message paragraph:

```python
def ConfirmPage(
    *,
    title: str,
    message: Children,
    post_url: str,
    csrf_token: str,
    cancel_url: str,
    confirm_label: str = "Confirm",
    confirm_color: ButtonColor = "red",
    details: Children = None,
) -> Node:
    """Full-page confirmation: a prompt, a POST ``<form>`` (the confirm action)
    and a cancel link back to the origin. The no-JS replacement for the htmx
    confirmation modals — reusable across delete/refund/split/reset flows.

    ``details`` is block content rendered after the prompt (a list of the data a
    delete would take with it); it cannot live in ``message``, which renders
    inside a ``<p>``.
    """
    return Div(
        class_=f"mx-auto w-full {FORM_MAX_WIDTH_CLASS} p-5 @container",
    )[
        Form(method="post", action=post_url)[
            Safe(
                f'<input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">'
            ),
            DialogTitle(title),
            P(class_="text-heading text-center mt-5")[*as_children(message)],
            *(
                [Div(class_="text-heading text-center mt-3")[*as_children(details)]]
                if details
                else []
            ),
            Div(class_="flex flex-col gap-2 mt-6")[
                ControlButton(
                    color=confirm_color,
                    type="submit",
                )[confirm_label],
                ControlButton(href=cancel_url, color="gray")["Cancel"],
            ],
        ]
    ]
```

Update the one existing caller, `games/views/statuschange.py:90`, from `action_url=` to `post_url=`, and change its value from a bare `reverse()` to `request.get_full_path()` so the origin Task 5 stamped onto the history link survives the confirmation. Its `cancel_url` (line 92) becomes `return_url(request, fallback="games:view_game", fallback_args=[statuschange.game.id])`.

- [ ] **Step 4: Run the component test**

```bash
make test ARGS="tests/test_components.py -k confirm_page_renders_details -v"
```

Expected: PASS.

- [ ] **Step 5: Write the failing delete-flow test**

Create `tests/test_deletion_confirmation.py`:

```python
"""Deletes confirm on GET, act on POST, and return to where they started."""

from datetime import datetime, timezone

import pytest
from django.urls import reverse

from common.returns import action_url
from games.models import Game, Platform, Session


@pytest.fixture
def logged_in(client, django_user_model, db):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


@pytest.fixture
def game(db):
    game = Game.objects.create(
        name="Test Game", platform=Platform.objects.create(name="PC")
    )
    Session.objects.create(
        game=game, timestamp_start=datetime(2024, 6, 1, 12, tzinfo=timezone.utc)
    )
    return game


def test_get_confirms_without_deleting(logged_in, game):
    response = logged_in.get(reverse("games:delete_game", args=[game.id]))
    assert response.status_code == 200
    assert "Test Game" in response.content.decode()
    assert Game.objects.filter(id=game.id).exists()


def test_post_deletes_and_returns_to_the_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=2"
    response = logged_in.post(action_url("games:delete_game", game.id, origin=origin))
    assert response["Location"] == origin
    assert not Game.objects.filter(id=game.id).exists()


def test_post_drops_an_origin_naming_the_deleted_game(logged_in, game):
    origin = reverse("games:view_game", args=[game.id])
    response = logged_in.post(action_url("games:delete_game", game.id, origin=origin))
    assert response["Location"] == reverse("games:list_games")


def test_the_confirmation_form_keeps_the_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=2"
    body = logged_in.get(
        action_url("games:delete_game", game.id, origin=origin)
    ).content.decode()
    assert "origin=%2Ftracker%2Fgame%2Flist%3Fpage%3D2" in body
```

- [ ] **Step 6: Run it and watch it fail**

```bash
make test ARGS="tests/test_deletion_confirmation.py -x"
```

Expected: FAIL — the GET deletes the game instead of confirming.

- [ ] **Step 7: Write the shared delete flow and put game delete on it**

Create `games/views/deletion.py`:

```python
"""One delete flow: GET renders the confirmation, POST performs the delete.

Both live on the same URL, so the ``?origin=`` value rides through the
confirmation into the POST with nothing to thread by hand.
"""

from collections.abc import Sequence
from typing import Any

from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect

from common.components import ConfirmPage
from common.components.core import Children
from common.layout import render_page
from common.returns import UrlName
from games.views.returns import return_url


def confirm_and_delete(
    request: HttpRequest,
    instance: Model,
    *,
    title: str,
    message: str,
    fallback: UrlName,
    fallback_args: Sequence[Any] = (),
    details: Children = None,
    detail_url: str | None = None,
) -> HttpResponse:
    """Confirm on GET, delete on POST, then return to the origin.

    ``detail_url`` is the deleted object's own page: an origin naming it would
    turn a successful delete into a 404, so it is refused.
    """
    if request.method != "POST":
        return render_page(
            request,
            ConfirmPage(
                title=title,
                message=message,
                details=details,
                post_url=request.get_full_path(),
                csrf_token=get_token(request),
                cancel_url=return_url(
                    request, fallback=fallback, fallback_args=fallback_args
                ),
                confirm_label="Delete",
            ),
            title=title,
        )
    instance.delete()
    return redirect(
        return_url(
            request,
            fallback=fallback,
            fallback_args=fallback_args,
            reject=detail_url,
        )
    )
```

In `games/views/game.py`, add `ConfirmPage` to the `common.components` import block (lines 11–51 already bring in `Node`, `Ul`, `Li`; `get_token`, `render_page` and `reverse` are present). Replace `delete_game`, and delete `_delete_game_confirmation_modal` (lines **218–276**) and `delete_game_confirmation` (lines **279–292**, decorator included):

```python
@login_required
def delete_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = get_object_or_404(Game, id=game_id)
    return confirm_and_delete(
        request,
        game,
        title="Delete game",
        message=f"This will permanently delete {game.name} and all associated data:",
        details=_deleted_with_game(game),
        fallback="games:list_games",
        detail_url=reverse("games:view_game", args=[game_id]),
    )


def _deleted_with_game(game: Game) -> Node:
    counts = [
        (game.sessions.count(), "session"),
        (game.purchases.count(), "purchase"),
        (game.playevents.count(), "play event"),
    ]
    present = [Li()[f"{count} {label}(s)"] for count, label in counts if count]
    return Ul()[*(present or [Li()["No associated data"]])]
```

Remove the `game/<int:game_id>/delete/confirm` route from `games/urls.py` — it occupies lines **38–42** (line 37 is the `view_game` route; line 42 is the route's closing `),`). Drop `"games:delete_game_confirmation"` from `CONFIRMATION` in `games/views/returns.py`. In `_game_action_buttons`, the Delete member becomes a plain link:

```python
                {
                    "href": action_url("games:delete_game", game.id, origin=origin),
                    "slot": "Delete",
                    "color": "red",
                },
```

- [ ] **Step 8: Update the two tests that pin the old markup**

Replace `tests/test_rendered_pages.py:437` (`test_delete_game_confirmation_modal`) with:

```python
    def test_delete_game_confirmation_page(self):
        html = self.get("games:delete_game", self.game.id).content.decode()
        self.assertIn(self.game.name, html)
        self.assertIn("session(s)", html)  # seeded session
        self.assertIn("purchase(s)", html)  # seeded purchase
        self.assertIn('method="post"', html)
        self.assertNoEscapedTags(html)
```

Add `games:delete_game` to `tests/test_html_validity.py`'s `_urls()` list (line 142) so the new page gets duplicate-id and interactive-nesting coverage. Nothing else covers this markup — contrary to an earlier note, that suite has no `<p>`-content-model check.

- [ ] **Step 9: Run the delete-flow tests**

```bash
make test ARGS="tests/test_deletion_confirmation.py tests/test_rendered_pages.py -v"
```

Expected: all PASS.

- [ ] **Step 10: Full gate, then commit**

```bash
make check
```

```bash
git add common/components/primitives.py games tests
git commit -m "refactor(delete): confirm game deletion on a page instead of a modal"
```

---

### Task 7: The remaining deletes confirm too

**Files:**
- Modify: `games/views/{purchase,session,playevent,platform,device,statuschange}.py`, `tests/test_html_validity.py`
- Test: `tests/test_deletion_confirmation.py` (extend), `tests/test_rendered_pages.py:489`

**Interfaces:**
- Consumes: `games.views.deletion.confirm_and_delete` (created in Task 6, signature `confirm_and_delete(request, instance, *, title, message, fallback, fallback_args=(), details=None, detail_url=None) -> HttpResponse`); `delete_game` is already on it and is the worked example.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_deletion_confirmation.py`:

```python
@pytest.fixture
def deletables(db):
    from datetime import date

    from games.models import Device, Purchase

    platform = Platform.objects.create(name="Console")
    owned = Game.objects.create(name="Deletable", platform=platform)
    purchase = Purchase.objects.create(
        date_purchased=date(2024, 6, 1), type=Purchase.GAME
    )
    purchase.games.set([owned])
    return {
        "session": Session.objects.create(
            game=owned, timestamp_start=datetime(2024, 6, 1, 12, tzinfo=timezone.utc)
        ),
        "purchase": purchase,
        "platform": Platform.objects.create(name="Doomed"),
        "device": Device.objects.create(name="Doomed"),
    }


@pytest.mark.parametrize(
    "url_name,key,fallback",
    [
        ("games:delete_session", "session", "games:list_sessions"),
        ("games:delete_purchase", "purchase", "games:list_purchases"),
        ("games:delete_platform", "platform", "games:list_platforms"),
        ("games:delete_device", "device", "games:list_devices"),
    ],
)
def test_every_delete_confirms_first(logged_in, deletables, url_name, key, fallback):
    instance = deletables[key]
    url = reverse(url_name, args=[instance.pk])
    assert logged_in.get(url).status_code == 200
    assert type(instance).objects.filter(pk=instance.pk).exists()
    response = logged_in.post(url)
    assert response["Location"] == reverse(fallback)
    assert not type(instance).objects.filter(pk=instance.pk).exists()
```

- [ ] **Step 2: Run them and watch them fail**

```bash
make test ARGS="tests/test_deletion_confirmation.py -k every_delete -x"
```

Expected: FAIL — the GET deletes and returns a 302.

- [ ] **Step 3: Move every delete view onto it**

`games/views/purchase.py`:

```python
@login_required
def delete_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    return confirm_and_delete(
        request,
        purchase,
        title="Delete purchase",
        message=f"Permanently delete this purchase of {purchase.first_game}?",
        fallback="games:list_purchases",
        detail_url=reverse("games:view_purchase", args=[purchase_id]),
    )
```

`games/views/session.py`:

```python
@login_required
def delete_session(request: HttpRequest, session_id: int = 0) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    return confirm_and_delete(
        request,
        session,
        title="Delete session",
        message=f"Permanently delete this session of {session.game}?",
        fallback="games:list_sessions",
    )
```

`games/views/playevent.py`:

```python
@login_required
def delete_playevent(request: HttpRequest, playevent_id: int) -> HttpResponse:
    playevent = get_object_or_404(PlayEvent, id=playevent_id)
    return confirm_and_delete(
        request,
        playevent,
        title="Delete playthrough",
        message=f"Permanently delete this playthrough of {playevent.game}?",
        fallback="games:view_game",
        fallback_args=[playevent.game.id],
    )
```

`games/views/platform.py` — add `Li` and `Ul` to its `common.components` import (neither is imported today):

```python
@login_required
def delete_platform(request: HttpRequest, platform_id: int) -> HttpResponse:
    platform = get_object_or_404(Platform, id=platform_id)
    return confirm_and_delete(
        request,
        platform,
        title="Delete platform",
        message=f"Permanently delete {platform.name}?",
        details=Ul()[
            Li()[
                f"{platform.game_set.count()} game(s) and "
                f"{platform.purchase_set.count()} purchase(s) become platformless"
            ]
        ],
        fallback="games:list_platforms",
    )
```

`games/views/device.py` — same import addition:

```python
@login_required
def delete_device(request: HttpRequest, device_id: int) -> HttpResponse:
    device = get_object_or_404(Device, id=device_id)
    return confirm_and_delete(
        request,
        device,
        title="Delete device",
        message=f"Permanently delete {device.name}?",
        details=Ul()[Li()[f"{device.session_set.count()} session(s) lose their device"]],
        fallback="games:list_devices",
    )
```

`Game.platform`, `Purchase.platform` and `Session.device` declare no `related_name`, hence `game_set` / `purchase_set` / `session_set`; all three are `on_delete=SET_NULL`, so the rows survive — the copy above is accurate.

`games/views/statuschange.py`'s `delete_statuschange` does the same with `fallback="games:view_game"` and `fallback_args=[statuschange.game.id]`; its bespoke `_delete_statuschange_content` is deleted.

- [ ] **Step 4: Update the statuschange copy assertion**

`tests/test_rendered_pages.py:497` asserts the literal `"Are you sure you want to delete this status change?"`, which `_delete_statuschange_content` owned. Change the assertion to the new message (`"Permanently delete this status change?"`) and use that exact string in the view.

Add the five remaining delete URLs to `tests/test_html_validity.py`'s `_urls()`.

- [ ] **Step 5: Run the delete tests**

```bash
make test ARGS="tests/test_deletion_confirmation.py tests/test_rendered_pages.py tests/test_html_validity.py -v"
```

Expected: all PASS.

- [ ] **Step 6: Full gate, then commit**

```bash
make check
```

```bash
git add games/views tests
git commit -m "feat(delete): confirm every deletion on its own page"
```

---

### Task 8: Browser proof

**Files:**
- Create: `e2e/test_return_to_origin_e2e.py`

**Interfaces:** Consumes everything above. Produces nothing.

- [ ] **Step 1: Write the test**

Create `e2e/test_return_to_origin_e2e.py`. Two conventions matter here and are easy to get wrong:

- **Do not use the `db` fixture alongside `live_server`.** `live_server` pulls in `transactional_db`, and mixing them breaks the between-test flush, leaking a second `tester` user into the next test (`User.MultipleObjectsReturned` on login). `e2e/test_filter_count_e2e.py:93` documents this. Create data inside a fixture that depends on `live_server`.
- **Scope submit selectors.** The navbar renders a logout `<button type="submit">` on every page, so a bare `button[type="submit"]` matches two elements and Playwright's strict mode raises.

```python
"""A real browser edits from a filtered list and lands back on it."""

import json
import re
from urllib.parse import quote

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.models import Game, Platform


def _login(page: Page, live_server) -> None:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")


@pytest.fixture
def world(live_server, django_user_model):
    django_user_model.objects.create_user(username="tester", password="secret123")
    platform = Platform.objects.create(name="PC")
    played = Game.objects.create(
        name="Alpha", platform=platform, status=Game.Status.PLAYED
    )
    Game.objects.create(
        name="Zeta Unplayed", platform=platform, status=Game.Status.UNPLAYED
    )
    return played


@pytest.fixture
def authenticated_page(live_server, page: Page, world) -> Page:
    _login(page, live_server)
    return page


def _played_only_path() -> str:
    return (
        reverse("games:list_games")
        + "?filter="
        + quote(json.dumps({"status": {"modifier": "INCLUDES", "value": ["p"]}}))
    )


def test_editing_from_a_filtered_list_returns_to_it(
    authenticated_page, live_server, world
):
    list_path = _played_only_path()
    authenticated_page.goto(f"{live_server.url}{list_path}")
    # The filter is doing work: the unplayed game is absent.
    expect(authenticated_page.locator("table")).to_contain_text("Alpha")
    expect(authenticated_page.locator("table")).not_to_contain_text("Zeta Unplayed")

    authenticated_page.click('a[href*="/edit?origin="]')
    expect(authenticated_page).to_have_url(re.compile(re.escape("/edit?origin=")))
    authenticated_page.fill('input[name="name"]', "Alpha Renamed")
    authenticated_page.click('#add-form button[type="submit"]')

    expect(authenticated_page).to_have_url(f"{live_server.url}{list_path}")
    expect(authenticated_page.locator("table")).to_contain_text("Alpha Renamed")
    expect(authenticated_page.locator("table")).not_to_contain_text("Zeta Unplayed")


def test_deleting_a_game_from_its_detail_page_lands_on_the_list(
    authenticated_page, live_server, world
):
    authenticated_page.goto(
        f"{live_server.url}{reverse('games:view_game', args=[world.id])}"
    )
    authenticated_page.click('a:has-text("Delete")')
    authenticated_page.click('form button[type="submit"]:has-text("Delete")')
    expect(authenticated_page).to_have_url(
        f"{live_server.url}{reverse('games:list_games')}"
    )
    assert not Game.objects.filter(id=world.id).exists()
```

- [ ] **Step 2: Run the e2e suite**

```bash
make test-e2e
```

Expected: both new tests PASS and nothing else regresses. `e2e/test_purchase_e2e.py:150` (`test_split_purchase_action`) exercises the split redirect, which now carries an origin — its `wait_for_url` glob still matches, but confirm it rather than assume.

- [ ] **Step 3: Full gate, then commit**

```bash
make check
```

```bash
git add e2e/test_return_to_origin_e2e.py
git commit -m "test(e2e): prove mutations return to the filtered list"
```

---

### Task 9: Record the convention

The origin rule is a project-wide invariant enforced only by tests. CLAUDE.md is where this project records such rules, and it currently documents the mechanism being deleted.

**Files:**
- Modify: `CLAUDE.md:165`, `CLAUDE.md:184`, and the "Conventions for AI assistants" list

- [ ] **Step 1: Replace the stale entry**

`CLAUDE.md:184` lists `use_custom_redirect` under `general.py` as "redirects to `request.session["return_path"]` if set". Remove that clause and add `common/returns.py` and `games/views/returns.py` to the directory/view descriptions.

- [ ] **Step 2: Add ConfirmPage to the primitives inventory**

`CLAUDE.md:165` enumerates the `primitives.py` builders and omits `ConfirmPage`. Add it, noting the `details` slot and that it is the canonical delete affordance for every entity.

- [ ] **Step 3: Add the convention**

In "Conventions for AI assistants":

> - **Mutating links carry their origin** — build every link to a mutating view with `action_url(name, *args, origin=request.get_full_path())`, never a bare `reverse()`, and end every mutating view with `redirect(return_url(request, fallback=...))`. A new route must be classified in `games/views/returns.py` or the suite fails. The origin travels only in the `?origin=` query parameter — never the session, never a form body — and is validated against the `READ_ONLY` route set, so it can never name a mutating target.

- [ ] **Step 4: Full gate, then commit**

```bash
make check
```

```bash
git add CLAUDE.md
git commit -m "docs: record the return-to-origin convention"
```

---

## Verification

After Task 9, confirm the issue's symptoms are gone:

1. Visit a game detail, navigate to the platforms list, edit a platform, save — you land on the platforms list, not the game.
2. Filter the games list, page to 2, edit a game, save — you land on the filtered page 2.
3. `grep -rn "return_path" games/ common/` prints nothing.
4. No route mutates on GET: every delete answers GET with a confirmation, and `drop_purchase` / `finish_purchase` / `view_game_start_session_from_session` no longer exist.

Then close https://github.com/KucharczykL/timetracker/issues/517.
