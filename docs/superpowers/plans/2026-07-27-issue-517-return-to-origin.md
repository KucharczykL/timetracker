# Return-to-origin redirects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After any mutating action, return the user to the exact page it was launched from — query string intact — instead of a session-remembered stale page or a hardcoded wrong list.

**Architecture:** The origin URL travels in the query string (`?next=<urlencoded full path>`) and nowhere else. `action_url()` stamps it onto every link to a mutating view; `return_url()` validates and consumes it, falling back to a per-view canonical list. Delete views become GET-confirm / POST-delete on a single URL, so the origin rides through the confirmation for free.

**Tech Stack:** Django 6 (function-based views), the project's Python component system (`common/components/`), pytest + pytest-django, Playwright for e2e.

Spec: `docs/superpowers/specs/2026-07-27-issue-517-return-to-origin-design.md`
Issue: https://github.com/KucharczykL/timetracker/issues/517

## Global Constraints

- **Everything runs through `make`.** Never `uv run` / `pytest` / `pnpm` directly. Focused runs: `make test ARGS="tests/test_returns.py -x"`.
- **`make check` is the gate** before declaring any task done — it runs lint, format-check, mypy, ts-check, vitest and the whole pytest suite including `e2e/`. Never gate on a subset.
- **Python 3.14 only.** A `SyntaxError` in an `except A, B:` line means the environment is on the wrong interpreter, not that the code is broken.
- **Build UI with the Python components** in `common.components` (`Div()`, `Ul()`, `ControlButton()`…), never raw HTML strings or Django templates. Full-page responses use `render_page()` from `common.layout`, never Django's `render()`.
- **Name variables with complete words** — `element` not `el`, `template` not `tpl`, `origin_url` not `orig`.
- **Comments explain non-obvious intent only.** No references to issues, PRs, or "this used to be…" history.
- **Name compound and primitive roles** with PEP 695 aliases (`type OriginUrl = str`) and add a trailing comment showing an example value.
- The app is mounted under `/tracker`, so `reverse("games:list_games")` yields `/tracker/game/list`.

---

## File Structure

**Created:**
- `common/returns.py` — the origin primitive: `action_url`, `origin_from`, `return_url`. No Django-app knowledge, no view imports.
- `games/views/returns.py` — the app-level classification of mutating routes (`ORIGIN_AWARE`, `CONFIRMATION`, `IN_PLACE`).
- `games/views/deletion.py` — `confirm_and_delete()`, the one delete flow every entity shares.
- `tests/test_returns.py` — unit tests for the primitive.
- `tests/test_action_origin_parity.py` — the backstop: every mutating link on every rendered page carries its page's own path as `next`.
- `tests/test_view_authentication.py` — every `games.urls` view requires login.
- `tests/test_deletion_confirmation.py` — GET confirms, POST deletes, origin round-trips.
- `e2e/test_return_to_origin_e2e.py` — filtered-list round trips in a real browser.

**Modified:** `games/views/{game,purchase,session,playevent,platform,device,statuschange,general}.py`, `common/components/{primitives,domain}.py`, `common/utils.py`, `games/urls.py`.

---

### Task 1: Close the unauthenticated playevent endpoints

`edit_playevent` and `delete_playevent` carry no `@login_required`, and the project has no `LoginRequiredMiddleware`. Anyone can edit or delete any play event. Independent of the redirect work and shipped first.

**Files:**
- Modify: `games/views/playevent.py:282`, `games/views/playevent.py:306`
- Test: `tests/test_view_authentication.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Create `tests/test_view_authentication.py`:

```python
"""Every view routed from games/urls.py must require authentication."""

import pytest
from django.conf import settings
from django.urls import reverse

from games import urls as games_urls
from games.models import Game, GameStatusChange, Platform, PlayEvent, Purchase, Session


def _sample_arguments(db_objects: dict[str, int]) -> dict[str, int]:
    return {
        "game_id": db_objects["game"],
        "playevent_id": db_objects["playevent"],
        "purchase_id": db_objects["purchase"],
        "session_id": db_objects["session"],
        "statuschange_id": db_objects["statuschange"],
        "pk": db_objects["statuschange"],
        "device_id": db_objects["device"],
        "platform_id": db_objects["platform"],
        "year": 2024,
        "model": "game",
        "key": "DEFAULT_CURRENCY",
    }


@pytest.fixture
def world(db):
    from datetime import date, datetime, timezone

    from games.models import Device

    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Test Game", platform=platform)
    purchase = Purchase.objects.create(
        date_purchased=date(2024, 6, 1), type=Purchase.GAME
    )
    purchase.games.set([game])
    session = Session.objects.create(
        game=game, timestamp_start=datetime(2024, 6, 1, 12, tzinfo=timezone.utc)
    )
    playevent = PlayEvent.objects.create(game=game)
    statuschange = GameStatusChange.objects.create(game=game, new_status="p")
    device = Device.objects.create(name="Desk")
    return {
        "game": game.id,
        "purchase": purchase.id,
        "session": session.id,
        "playevent": playevent.id,
        "statuschange": statuschange.id,
        "device": device.id,
        "platform": platform.id,
    }


def test_every_route_requires_login(client, world):
    arguments = _sample_arguments(world)
    unprotected = []
    for pattern in games_urls.urlpatterns:
        name = pattern.name
        if name is None:
            continue
        needed = pattern.pattern.regex.groupindex.keys()
        try:
            url = reverse(
                f"games:{name}", kwargs={key: arguments[key] for key in needed}
            )
        except KeyError:
            pytest.fail(f"add a sample argument for {name}: {sorted(needed)}")
        response = client.get(url)
        if response.status_code != 302 or settings.LOGIN_URL not in response["Location"]:
            unprotected.append(f"{name} -> {response.status_code}")
    assert unprotected == []
```

- [ ] **Step 2: Run it and watch it fail**

```bash
make test ARGS="tests/test_view_authentication.py -x"
```

Expected: FAIL, listing `edit_playevent -> 200` and `delete_playevent -> 302` (the latter redirecting to the referrer fallback `/`, not to the login page).

- [ ] **Step 3: Add the decorators**

In `games/views/playevent.py`, add `@login_required` above `def edit_playevent` (line 282) and above `def delete_playevent` (line 306), matching `add_playevent` at line 211:

```python
@login_required
def edit_playevent(request: HttpRequest, playevent_id: int) -> HttpResponse:
```

```python
@login_required
def delete_playevent(request: HttpRequest, playevent_id: int) -> HttpResponse:
```

- [ ] **Step 4: Run the test again**

```bash
make test ARGS="tests/test_view_authentication.py -x"
```

Expected: PASS.

- [ ] **Step 5: Full gate**

```bash
make check
```

- [ ] **Step 6: Commit**

```bash
git add games/views/playevent.py tests/test_view_authentication.py
git commit -m "fix(auth): require login to edit and delete play events"
```

---

### Task 2: The origin primitive

**Files:**
- Create: `common/returns.py`
- Test: `tests/test_returns.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces, for every later task:
  - `NEXT_PARAM: str` — the query-parameter name, `"next"`.
  - `type OriginUrl = str`, `type UrlName = str`.
  - `action_url(viewname: UrlName, *args: Any, origin: OriginUrl | None, **kwargs: Any) -> str`
  - `origin_from(request: HttpRequest, *, reject: str | None = None) -> OriginUrl | None`
  - `return_url(request: HttpRequest, *, fallback: UrlName, fallback_args: Sequence[Any] = (), reject: str | None = None) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_returns.py`:

```python
"""The origin primitive: what may travel in ?next=, and what must not."""

import pytest
from django.urls import reverse

from common.returns import NEXT_PARAM, action_url, origin_from, return_url

LIST_URL = "/tracker/game/list?page=3"


def _request(request_factory, next_value=None):
    query = {NEXT_PARAM: next_value} if next_value is not None else {}
    return request_factory.get("/tracker/game/1/edit", query)


def test_action_url_appends_the_encoded_origin(db):
    url = action_url("games:edit_game", 1, origin=LIST_URL)
    assert url == (
        reverse("games:edit_game", args=[1])
        + "?next=%2Ftracker%2Fgame%2Flist%3Fpage%3D3"
    )


def test_action_url_without_an_origin_is_the_bare_url(db):
    assert action_url("games:edit_game", 1, origin=None) == reverse(
        "games:edit_game", args=[1]
    )


def test_valid_origin_survives(rf, db):
    assert origin_from(_request(rf, LIST_URL)) == LIST_URL


def test_absent_origin_is_none(rf, db):
    assert origin_from(_request(rf)) is None


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
    assert origin_from(_request(rf, candidate)) is None


def test_rejected_path_is_dropped(rf, db):
    detail = reverse("games:view_game", args=[1])
    assert origin_from(_request(rf, detail), reject=detail) is None
    assert origin_from(_request(rf, detail)) == detail


def test_return_url_prefers_the_origin(rf, db):
    assert return_url(_request(rf, LIST_URL), fallback="games:list_games") == LIST_URL


def test_return_url_falls_back(rf, db):
    assert return_url(_request(rf), fallback="games:list_games") == reverse(
        "games:list_games"
    )


def test_return_url_fallback_takes_arguments(rf, db):
    assert return_url(
        _request(rf), fallback="games:view_game", fallback_args=[7]
    ) == reverse("games:view_game", args=[7])
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
"""

from collections.abc import Sequence
from typing import Any
from urllib.parse import urlencode, urlparse

from django.http import HttpRequest
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

type OriginUrl = str  # "/tracker/game/list?filter=%7B%22status%22%3A%5B%22p%22%5D%7D"
type UrlName = str  # "games:edit_game"

NEXT_PARAM = "next"


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
    return f"{url}?{urlencode({NEXT_PARAM: origin})}"


def origin_from(
    request: HttpRequest, *, reject: str | None = None
) -> OriginUrl | None:
    """The origin this request carries, or None if absent or untrustworthy.

    ``reject`` drops an origin naming a page that is about to stop existing —
    a delete view passes the detail URL of the object it is deleting.
    """
    candidate = request.GET.get(NEXT_PARAM)
    if not candidate:
        return None
    # allowed_hosts=None admits root-relative URLs only, which also turns away
    # "//evil.example" and every non-http scheme.
    if not url_has_allowed_host_and_scheme(candidate, allowed_hosts=None):
        return None
    path = urlparse(candidate).path
    if reject is not None and path == reject:
        return None
    try:
        # An origin that no longer routes would turn a successful mutation into
        # a 404; a fabricated one would be an open redirect within the site.
        resolve(path)
    except Resolver404:
        return None
    return candidate


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

- [ ] **Step 4: Run the tests**

```bash
make test ARGS="tests/test_returns.py -v"
```

Expected: 13 PASS (the unsafe-origin case is parametrized five ways).

- [ ] **Step 5: Full gate**

```bash
make check
```

- [ ] **Step 6: Commit**

```bash
git add common/returns.py tests/test_returns.py
git commit -m "feat(returns): add the return-to-origin primitive"
```

---

### Task 3: Every redirecting view consumes the origin

Wire `return_url` into every mutating view, classify the routes, fix the wrong canonical fallbacks, and delete the three superseded mechanisms. After this task nothing *stamps* an origin yet, so behaviour is fallback-only — correct, just not yet origin-aware.

**Files:**
- Create: `games/views/returns.py`
- Modify: `games/views/general.py` (drop `use_custom_redirect`, drop two session writes), `games/views/game.py`, `games/views/purchase.py`, `games/views/session.py`, `games/views/playevent.py`, `games/views/platform.py`, `games/views/device.py`, `games/views/statuschange.py`, `common/utils.py`
- Test: `tests/test_returns_classification.py` (create), `tests/test_returns.py` (extend)

**Interfaces:**
- Consumes: `common.returns.{action_url, origin_from, return_url, UrlName}` from Task 2.
- Produces: `games.views.returns.{ORIGIN_AWARE, CONFIRMATION, IN_PLACE}` — three `frozenset[UrlName]` of `games:`-prefixed url names, used by Task 4's parity test.

- [ ] **Step 1: Write the failing classification test**

Create `tests/test_returns_classification.py`:

```python
"""Every mutating route is classified, and every classification names a route."""

import re

from games import urls as games_urls
from games.views.returns import CONFIRMATION, IN_PLACE, ORIGIN_AWARE

MUTATING_NAME = re.compile(r"^(add|edit|delete|drop|finish|refund|split)_")


def _routed_names() -> set[str]:
    return {
        f"games:{pattern.name}"
        for pattern in games_urls.urlpatterns
        if pattern.name is not None
    }


def test_every_mutating_route_is_classified():
    classified = ORIGIN_AWARE | CONFIRMATION | IN_PLACE
    unclassified = {
        name
        for name in _routed_names()
        if MUTATING_NAME.match(name.removeprefix("games:")) and name not in classified
    }
    assert unclassified == set()


def test_no_classification_names_a_missing_route():
    assert (ORIGIN_AWARE | CONFIRMATION | IN_PLACE) - _routed_names() == set()


def test_the_classifications_do_not_overlap():
    assert ORIGIN_AWARE & CONFIRMATION == set()
    assert ORIGIN_AWARE & IN_PLACE == set()
    assert CONFIRMATION & IN_PLACE == set()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
make test ARGS="tests/test_returns_classification.py -x"
```

Expected: FAIL with `ModuleNotFoundError: No module named 'games.views.returns'`.

- [ ] **Step 3: Write the classification**

Create `games/views/returns.py`:

```python
"""Which routes mutate, and how each one answers when it is done.

The parity test in tests/test_action_origin_parity.py reads these sets to know
which links must carry an origin, and tests/test_returns_classification.py fails
until a newly added mutating route appears in exactly one of them.
"""

from common.returns import UrlName

# Redirects (or sends HX-Redirect) once finished, so it consumes an origin.
ORIGIN_AWARE: frozenset[UrlName] = frozenset(
    {
        "games:add_device",
        "games:delete_device",
        "games:edit_device",
        "games:add_game",
        "games:edit_game",
        "games:delete_game",
        "games:add_platform",
        "games:edit_platform",
        "games:delete_platform",
        "games:add_playevent",
        "games:add_playevent_for_game",
        "games:edit_playevent",
        "games:delete_playevent",
        "games:add_purchase",
        "games:add_purchase_for_game",
        "games:edit_purchase",
        "games:drop_purchase",
        "games:delete_purchase",
        "games:finish_purchase",
        "games:split_purchase",
        "games:add_session",
        "games:add_session_for_game",
        "games:edit_session",
        "games:delete_session",
        "games:add_statuschange",
        "games:edit_statuschange",
        "games:delete_statuschange",
        # Session cloning: named for where it is launched from rather than what
        # it does, so the mutating-name guard cannot see it.
        "games:view_game_start_session_from_session",
        "games:list_sessions_start_session_from_session",
    }
)

# GET-only; renders a confirmation and forwards the origin to the form it draws.
CONFIRMATION: frozenset[UrlName] = frozenset(
    {
        "games:delete_game_confirmation",
        "games:refund_purchase_confirmation",
        "games:split_purchase_confirmation",
    }
)

# Answers with a partial swap and leaves the user where they are.
IN_PLACE: frozenset[UrlName] = frozenset({"games:refund_purchase"})
```

- [ ] **Step 4: Run the classification test**

```bash
make test ARGS="tests/test_returns_classification.py -v"
```

Expected: 3 PASS.

- [ ] **Step 5: Write the failing fallback tests**

Append to `tests/test_returns.py`:

```python
def test_edit_game_falls_back_to_the_games_list(client, django_user_model, db):
    from games.models import Game

    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    game = Game.objects.create(name="Test Game")
    response = client.post(
        reverse("games:edit_game", args=[game.id]), {"name": "Renamed"}
    )
    assert response["Location"] == reverse("games:list_games")


def test_edit_game_returns_to_the_carried_origin(client, django_user_model, db):
    from games.models import Game

    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    game = Game.objects.create(name="Test Game")
    origin = f"{reverse('games:list_games')}?page=3"
    response = client.post(
        action_url("games:edit_game", game.id, origin=origin), {"name": "Renamed"}
    )
    assert response["Location"] == origin


def test_a_chained_form_forwards_the_origin(client, django_user_model, db):
    """Add game -> "and add a session" hands the origin to the next form."""
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    origin = f"{reverse('games:list_games')}?page=3"
    response = client.post(
        action_url("games:add_game", origin=origin),
        {"name": "Chained", "submit_and_create_session": "1"},
    )
    assert response["Location"].startswith(
        reverse("games:add_session_for_game", kwargs={"game_id": Game.objects.get(name="Chained").id})
    )
    assert "next=%2Ftracker%2Fgame%2Flist%3Fpage%3D3" in response["Location"]


def test_the_origin_survives_the_login_redirect(client, django_user_model, db):
    """Logged out, the origin ends up nested inside Django's own ?next=."""
    from games.models import Game

    game = Game.objects.create(name="Test Game")
    origin = f"{reverse('games:list_games')}?page=3"
    target = action_url("games:edit_game", game.id, origin=origin)
    response = client.get(target)
    assert response.status_code == 302
    login_url = response["Location"]

    django_user_model.objects.create_user(username="u", password="p")
    client.post(login_url, {"username": "u", "password": "p"})
    edit_page = client.get(target)
    assert edit_page.status_code == 200
    saved = client.post(target, {"name": "Renamed"})
    assert saved["Location"] == origin
```

`Game` is already imported at the top of the chained-form test via the local
`from games.models import Game` in the earlier fallback test; hoist that import to
module level so all four tests share it.

- [ ] **Step 6: Run them and watch them fail**

```bash
make test ARGS="tests/test_returns.py -k 'edit_game or chained or login_redirect' -x"
```

Expected: FAIL — the fallback test asserts `/tracker/game/list` but gets `/tracker/session/list`, and the origin, chained and login tests are all ignored by the current views.

- [ ] **Step 7: Convert every redirecting view**

Each view below ends with `return redirect(return_url(request, fallback=..., ...))`. Import in each module:

```python
from common.returns import origin_from, return_url
```

`games/views/game.py`:

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

(The `@use_custom_redirect` decorator goes; so does the misnamed local `purchase = get_object_or_404(Game, ...)`, renamed to `game` as above.)

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

Also in `games/views/game.py`: delete the `request.session["return_path"] = request.path` line in `view_game` (line 745) and the `use_custom_redirect` import (line 68).

`games/views/purchase.py` — drop the `use_custom_redirect` import and decorator, then:

- `add_purchase`: the `pricing_mode == "per_game"` branch and the plain branch become `return redirect(return_url(request, fallback="games:list_purchases"))`; the `submit_and_redirect` branch becomes `return redirect(action_url("games:add_session_for_game", game_id=purchase.first_game.id, origin=origin_from(request)))`.
- `edit_purchase`: `return redirect(return_url(request, fallback="games:list_purchases"))`.
- `drop_purchase` and `finish_purchase`: same fallback.
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

- `split_purchase` keeps its `HX-Redirect` shape; the source purchase is deleted, so its detail URL is rejected:

```python
    response = HttpResponse(status=204)
    response["HX-Redirect"] = return_url(
        request,
        fallback="games:list_purchases",
        reject=reverse("games:view_purchase", args=[purchase_id]),
    )
    return response
```

`games/views/session.py`: `add_session`, `edit_session` and `delete_session` all use `return redirect(return_url(request, fallback="games:list_sessions"))`. In `new_session_from_existing_session` only the non-htmx tail changes to the same call; the `HX-Refresh` branch already leaves the user in place.

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

`edit_playevent` uses `fallback_args=[playevent.game.id]`. `delete_playevent` loses the `HTTP_REFERER` redirect entirely:

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

- [ ] **Step 8: Delete the superseded mechanisms**

In `games/views/general.py`, delete the whole `use_custom_redirect` function (lines 93–110) and the `request.session["return_path"] = request.path` lines in `stats_alltime` (113) and `stats` (128). Remove the now-unused `HttpResponseRedirect` import if nothing else in the module uses it.

In `common/utils.py`, delete `redirect_to` (lines 156–182) and `add_next_param_to_url` (185–186), plus the now-unused `redirect` and `urlencode` imports.

- [ ] **Step 9: Prove the dead code is gone**

```bash
grep -rn "use_custom_redirect\|return_path\|redirect_to\|add_next_param_to_url\|HTTP_REFERER" games/ common/ tests/ e2e/
```

Expected: no output.

- [ ] **Step 10: Run the tests**

```bash
make test ARGS="tests/test_returns.py tests/test_returns_classification.py -v"
```

Expected: all PASS.

- [ ] **Step 11: Full gate**

```bash
make check
```

Expected: green. If `tests/test_paths_return_200.py` or `tests/test_rendered_pages.py` fail, they are asserting an old wrong redirect target — update the assertion to the new canonical list and note it in the commit body.

- [ ] **Step 12: Commit**

```bash
git add games/views common/utils.py tests/test_returns.py tests/test_returns_classification.py
git commit -m "refactor(views): resolve mutating redirects from the request, not the session"
```

---

### Task 4: Stamp the origin on every mutating link

**Files:**
- Modify: `games/views/game.py` (list rows ~line 128, `_game_action_buttons` ~395, purchases/sessions/playevents sections, statuschange links ~445), `games/views/purchase.py` (`_render_purchase_buttons` 67, `_render_purchase_row` 128), `games/views/platform.py:74`, `games/views/device.py:72`, `games/views/playevent.py:98`, `common/components/domain.py:338` (`SessionActions`)
- Test: `tests/test_action_origin_parity.py` (create)

**Interfaces:**
- Consumes: `common.returns.action_url`, `games.views.returns.{ORIGIN_AWARE, CONFIRMATION}`.
- Produces: `SessionActions(session, csrf_token: str, origin: OriginUrl | None) -> Node`, `_render_purchase_buttons(purchase_id, is_refunded, can_split=False, *, origin)`, `_render_purchase_row(purchase, presentation, *, origin)`, `create_playevent_tabledata(..., *, origin)` — every row builder gains a required keyword-only `origin`.

- [ ] **Step 1: Write the failing parity test**

Create `tests/test_action_origin_parity.py`:

```python
"""Every link to a mutating view carries the page it was rendered on.

A row's Edit button must come back to the filtered, sorted, paginated list the
user was actually looking at, which only works if the list stamped its own full
path onto the link.
"""

import html
import re
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import Resolver404, resolve, reverse

from games.models import Device, Game, Platform, PlayEvent, Purchase, Session
from games.views.returns import CONFIRMATION, ORIGIN_AWARE

LINK_ATTRIBUTE = re.compile(r'\b(?:href|hx-get|hx-post)="([^"]*)"')
MUST_CARRY_ORIGIN = ORIGIN_AWARE | CONFIRMATION


@pytest.fixture
def world(db):
    from datetime import date, datetime, timezone

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
        carried = parse_qs(parsed.query).get("next", [])
        if carried != [page_path]:
            failures.append(f"{name} carried {carried!r}, expected [{page_path!r}]")
    return failures


@pytest.mark.parametrize(
    "url_name,arguments",
    [
        ("games:list_games", []),
        ("games:list_sessions", []),
        ("games:list_purchases", []),
        ("games:list_playevents", []),
        ("games:list_platforms", []),
        ("games:list_devices", []),
    ],
)
def test_list_pages_stamp_their_own_path(
    client, django_user_model, world, url_name, arguments
):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    page_path = reverse(url_name, args=arguments) + "?page=1"
    response = client.get(page_path)
    assert response.status_code == 200
    assert _missing_origin(response.content.decode(), page_path) == []


def test_game_detail_stamps_its_own_path(client, django_user_model, world):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    page_path = reverse("games:view_game", args=[world.id])
    response = client.get(page_path)
    assert response.status_code == 200
    assert _missing_origin(response.content.decode(), page_path) == []
```

- [ ] **Step 2: Run it and watch it fail**

```bash
make test ARGS="tests/test_action_origin_parity.py -x"
```

Expected: FAIL listing `games:edit_game carried [], expected ['/tracker/game/list?page=1']` and siblings.

- [ ] **Step 3: Stamp the list-view rows**

Every module touched in this task imports:

```python
from common.returns import OriginUrl, action_url
```

In each list view, take the origin once at the top of the row loop and build every action through `action_url`. `games/views/game.py`, in `list_games`:

```python
    origin = request.get_full_path()
    ...
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

Apply the identical shape to `games/views/platform.py:74` (`edit_platform`, `delete_platform`), `games/views/device.py:72` (`edit_device`, `delete_device`) and `games/views/playevent.py:98` (`edit_playevent`, `delete_playevent`), each taking `origin = request.get_full_path()` in the enclosing view.

- [ ] **Step 4: Thread the origin through the shared row builders**

`games/views/purchase.py`:

```python
def _render_purchase_buttons(
    purchase_id, is_refunded, can_split=False, *, origin: OriginUrl | None
):
    """Return button group HTML for a purchase row."""
    return ButtonGroup(
        [
            {
                "href": "#",
                "hx_get": action_url(
                    "games:refund_purchase_confirmation", purchase_id, origin=origin
                ),
                "hx_target": "#global-modal-container",
                "slot": Icon("refund", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Mark as refunded",
            }
            if not is_refunded
            else {},
            {
                "href": "#",
                "hx_get": action_url(
                    "games:split_purchase_confirmation", purchase_id, origin=origin
                ),
                "hx_target": "#global-modal-container",
                "slot": Icon("split", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Split into per-game purchases",
                "color": "gray",
            }
            if can_split
            else {},
            {
                "href": action_url("games:edit_purchase", purchase_id, origin=origin),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Edit",
                "color": "gray",
            },
            {
                "href": action_url("games:delete_purchase", purchase_id, origin=origin),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Delete",
                "color": "red",
            },
        ]
    )
```

`_render_purchase_row` gains `*, origin: OriginUrl | None` and passes it down. Its callers: `list_purchases` and the game-detail purchases section pass `request.get_full_path()`; `refund_purchase`, which re-renders one row outside any list, passes `origin_from(request)` — the origin arrives on the modal's post URL.

`common/components/domain.py`, `SessionActions`:

```python
def SessionActions(session, csrf_token: str, origin: OriginUrl | None) -> Node:
```

with its two navigation members becoming:

```python
            {
                "href": action_url("games:edit_session", session.pk, origin=origin),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Edit",
            },
            {
                "href": action_url("games:delete_session", session.pk, origin=origin),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Delete",
                "color": "red",
            },
```

`games/views/playevent.py`'s `create_playevent_tabledata` gains `*, origin: OriginUrl | None`; both callers (`list_playevents` and `games/views/game.py:686`) pass `request.get_full_path()`.

- [ ] **Step 5: Stamp the game detail page**

`games/views/game.py`, `_game_action_buttons(game)` becomes `_game_action_buttons(game, origin)` and stamps `games:add_session_for_game`, `games:edit_game` and the delete link. The statuschange links at line 445:

```python
        edit = A(
            href=action_url("games:edit_statuschange", change.id, origin=origin)
        )["Edit"]
        delete = A(
            href=action_url("games:delete_statuschange", change.id, origin=origin)
        )["Delete"]
```

`view_game` computes `origin = request.get_full_path()` once and passes it to the five section builders it already calls — `_game_header`, `_purchases_section`, `_sessions_section`, `_playevents_section` and `_history_section` — each of which forwards it to the row builder it uses (`_game_action_buttons`, `_render_purchase_row`, `SessionActions`, `create_playevent_tabledata`, `_game_history` respectively). Each of those five gains an `origin: OriginUrl | None` parameter.

- [ ] **Step 6: Run the parity test**

```bash
make test ARGS="tests/test_action_origin_parity.py -v"
```

Expected: all 7 PASS.

- [ ] **Step 7: Full gate**

```bash
make check
```

Expected: green. `tests/test_game_detail_links.py` and `tests/test_session_row.py` may assert bare `reverse()` URLs — update those expectations to the stamped form.

- [ ] **Step 8: Commit**

```bash
git add games/views common/components/domain.py tests/test_action_origin_parity.py
git commit -m "feat(links): carry the origin page on every mutating link"
```

---

### Task 5: Game delete becomes a confirmation page

**Files:**
- Modify: `common/components/primitives.py:1657` (`ConfirmPage`), `games/views/statuschange.py:90` (the renamed keyword), `games/views/game.py` (delete the modal, its view and the route), `games/urls.py:37-42`
- Test: `tests/test_components.py` (extend), `tests/test_deletion_confirmation.py` (create)

**Interfaces:**
- Consumes: `common.returns.{action_url, return_url}`.
- Produces: `ConfirmPage(*, title, message, post_url, csrf_token, cancel_url, confirm_label="Confirm", confirm_color="red", details: Children = None) -> Node`.

- [ ] **Step 1: Write the failing component test**

Append to `tests/test_components.py`:

```python
def test_confirm_page_renders_details_outside_the_message_paragraph():
    from common.components import ConfirmPage, Li, Ul

    html = str(
        ConfirmPage(
            title="Delete game",
            message="Permanently delete this game?",
            post_url="/tracker/game/1/delete?next=%2Ftracker%2Fgame%2Flist",
            csrf_token="token",
            cancel_url="/tracker/game/list",
            confirm_label="Delete",
            details=Ul()[Li()["2 session(s)"]],
        )
    )
    assert 'action="/tracker/game/1/delete?next=%2Ftracker%2Fgame%2Flist"' in html
    # A <ul> inside the message <p> would be invalid HTML.
    assert "<p" in html.split("<ul")[0]
    assert "</p>" in html.split("<ul")[0]
```

- [ ] **Step 2: Run it and watch it fail**

```bash
make test ARGS="tests/test_components.py -k confirm_page_renders_details -x"
```

Expected: FAIL with `TypeError: ConfirmPage() got an unexpected keyword argument 'post_url'`.

- [ ] **Step 3: Extend ConfirmPage**

In `common/components/primitives.py`, rename the `action_url` parameter to `post_url` (it would otherwise read as a call to the new helper) and add the block slot:

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
                [
                    Div(class_="text-heading text-center mt-3")[*as_children(details)]
                ]
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

Update the one existing caller, `games/views/statuschange.py:90`, from `action_url=` to `post_url=`.

- [ ] **Step 4: Run the component test**

```bash
make test ARGS="tests/test_components.py -k confirm_page_renders_details -v"
```

Expected: PASS.

- [ ] **Step 5: Write the failing delete-flow test**

Create `tests/test_deletion_confirmation.py`:

```python
"""Deletes confirm on GET, act on POST, and return to where they started."""

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
    from datetime import datetime, timezone

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
    response = logged_in.post(
        action_url("games:delete_game", game.id, origin=origin)
    )
    assert response["Location"] == origin
    assert not Game.objects.filter(id=game.id).exists()


def test_post_drops_an_origin_naming_the_deleted_game(logged_in, game):
    origin = reverse("games:view_game", args=[game.id])
    response = logged_in.post(
        action_url("games:delete_game", game.id, origin=origin)
    )
    assert response["Location"] == reverse("games:list_games")


def test_the_confirmation_form_keeps_the_origin(logged_in, game):
    origin = f"{reverse('games:list_games')}?page=2"
    response = logged_in.get(action_url("games:delete_game", game.id, origin=origin))
    assert "next=%2Ftracker%2Fgame%2Flist%3Fpage%3D2" in response.content.decode()
```

- [ ] **Step 6: Run it and watch it fail**

```bash
make test ARGS="tests/test_deletion_confirmation.py -x"
```

Expected: FAIL — the GET deletes the game instead of confirming.

- [ ] **Step 7: Rewrite delete_game as confirm-then-delete**

In `games/views/game.py`, replace `delete_game` and delete `_delete_game_confirmation_modal` (lines 218–278) and `delete_game_confirmation` (280–292):

```python
@login_required
def delete_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = get_object_or_404(Game, id=game_id)
    detail_url = reverse("games:view_game", args=[game_id])
    if request.method != "POST":
        return render_page(
            request,
            ConfirmPage(
                title="Delete game",
                message=(
                    f"This will permanently delete {game.name} "
                    "and all associated data:"
                ),
                details=_deleted_with_game(game),
                post_url=request.get_full_path(),
                csrf_token=get_token(request),
                cancel_url=return_url(request, fallback="games:list_games"),
                confirm_label="Delete",
            ),
            title="Delete game",
        )
    game.delete()
    return redirect(
        return_url(request, fallback="games:list_games", reject=detail_url)
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

Remove the `game/<int:game_id>/delete/confirm` route from `games/urls.py` (lines 37–41) and drop `"games:delete_game_confirmation"` from `CONFIRMATION` in `games/views/returns.py`. In `_game_action_buttons`, the Delete member becomes a plain link:

```python
                {
                    "href": action_url("games:delete_game", game.id, origin=origin),
                    "slot": "Delete",
                    "color": "red",
                },
```

- [ ] **Step 8: Run the delete-flow tests**

```bash
make test ARGS="tests/test_deletion_confirmation.py -v"
```

Expected: 4 PASS.

- [ ] **Step 9: Full gate**

```bash
make check
```

Expected: green after one known edit — `tests/test_rendered_pages.py:437`
(`test_delete_game_confirmation_modal`) asserts the deleted fragment. Replace it
with a confirmation-page assertion:

```python
    def test_delete_game_confirmation_page(self):
        html = self.get("games:delete_game", self.game.id).content.decode()
        self.assertIn(self.game.name, html)
        self.assertIn("session(s)", html)  # seeded session
        self.assertIn("purchase(s)", html)  # seeded purchase
        self.assertIn('method="post"', html)
        self.assertNoEscapedTags(html)
```

`self.get` must be able to reach `games:delete_game`; it already reverses by
name with positional arguments, so no helper change is needed.

- [ ] **Step 10: Commit**

```bash
git add common/components/primitives.py games/views games/urls.py tests
git commit -m "refactor(delete): confirm game deletion on a page instead of a modal"
```

---

### Task 6: The remaining deletes confirm too

**Files:**
- Create: `games/views/deletion.py`
- Modify: `games/views/{purchase,session,playevent,platform,device,game,statuschange}.py`
- Test: `tests/test_deletion_confirmation.py` (extend)

**Interfaces:**
- Consumes: `common.returns.return_url`, `common.components.ConfirmPage`.
- Produces: `confirm_and_delete(request, instance, *, title, message, fallback, fallback_args=(), details=None, detail_url=None) -> HttpResponse`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_deletion_confirmation.py`:

```python
@pytest.mark.parametrize(
    "url_name,factory,fallback",
    [
        ("games:delete_session", "session", "games:list_sessions"),
        ("games:delete_purchase", "purchase", "games:list_purchases"),
        ("games:delete_platform", "platform", "games:list_platforms"),
        ("games:delete_device", "device", "games:list_devices"),
    ],
)
def test_every_delete_confirms_first(logged_in, deletables, url_name, factory, fallback):
    instance = deletables[factory]
    url = reverse(url_name, args=[instance.pk])
    assert logged_in.get(url).status_code == 200
    assert type(instance).objects.filter(pk=instance.pk).exists()
    response = logged_in.post(url)
    assert response["Location"] == reverse(fallback)
    assert not type(instance).objects.filter(pk=instance.pk).exists()


@pytest.fixture
def deletables(db):
    from datetime import date, datetime, timezone

    from games.models import Device, Purchase

    platform = Platform.objects.create(name="Console")
    game = Game.objects.create(name="Deletable", platform=platform)
    purchase = Purchase.objects.create(
        date_purchased=date(2024, 6, 1), type=Purchase.GAME
    )
    purchase.games.set([game])
    return {
        "session": Session.objects.create(
            game=game, timestamp_start=datetime(2024, 6, 1, 12, tzinfo=timezone.utc)
        ),
        "purchase": purchase,
        "platform": Platform.objects.create(name="Doomed"),
        "device": Device.objects.create(name="Doomed"),
    }
```

- [ ] **Step 2: Run them and watch them fail**

```bash
make test ARGS="tests/test_deletion_confirmation.py -k every_delete -x"
```

Expected: FAIL — the GET deletes and returns a 302.

- [ ] **Step 3: Write the shared flow**

Create `games/views/deletion.py`:

```python
"""One delete flow: GET renders the confirmation, POST performs the delete.

Both live on the same URL, so the ``?next=`` origin rides through the
confirmation into the POST with nothing to thread by hand.
"""

from collections.abc import Sequence
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect

from common.components import ConfirmPage
from common.components.core import Children
from common.layout import render_page
from common.returns import UrlName, return_url


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

- [ ] **Step 4: Move every delete view onto it**

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

`games/views/platform.py`:

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

`games/views/device.py`:

```python
@login_required
def delete_device(request: HttpRequest, device_id: int) -> HttpResponse:
    device = get_object_or_404(Device, id=device_id)
    return confirm_and_delete(
        request,
        device,
        title="Delete device",
        message=f"Permanently delete {device.name}?",
        details=Ul()[
            Li()[f"{device.session_set.count()} session(s) lose their device"]
        ],
        fallback="games:list_devices",
    )
```

`games/views/game.py`'s `delete_game` (written in Task 5) collapses onto the helper as well:

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
```

`games/views/statuschange.py`'s `delete_statuschange` does the same, keeping its `games:view_game` fallback with `fallback_args=[statuschange.game.id]`, and its bespoke `_delete_statuschange_content` is deleted.

Verify the `SET_NULL` claims in the platform and device copy before shipping them: `Game.platform`, `Purchase.platform` and `Session.device` are all `on_delete=SET_NULL`, so the rows survive without the deleted object.

- [ ] **Step 5: Run the delete tests**

```bash
make test ARGS="tests/test_deletion_confirmation.py -v"
```

Expected: all PASS.

- [ ] **Step 6: Full gate**

```bash
make check
```

- [ ] **Step 7: Commit**

```bash
git add games/views tests/test_deletion_confirmation.py
git commit -m "feat(delete): confirm every deletion on its own page"
```

---

### Task 7: Browser proof

**Files:**
- Create: `e2e/test_return_to_origin_e2e.py`

**Interfaces:**
- Consumes: everything above. Produces nothing.

- [ ] **Step 1: Write the test**

Create `e2e/test_return_to_origin_e2e.py`:

```python
"""A real browser edits from a filtered list and lands back on it."""

import json
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
def authenticated_page(live_server, page: Page, django_user_model) -> Page:
    django_user_model.objects.create_user(username="tester", password="secret123")
    _login(page, live_server)
    return page


@pytest.fixture
def games(db):
    platform = Platform.objects.create(name="PC")
    return [
        Game.objects.create(name=name, platform=platform, status=Game.Status.PLAYED)
        for name in ("Alpha", "Beta")
    ]


def _filtered_list_path() -> str:
    return (
        reverse("games:list_games")
        + "?filter="
        + quote(json.dumps({"status": {"modifier": "INCLUDES", "value": ["p"]}}))
    )


def test_editing_from_a_filtered_list_returns_to_it(authenticated_page, live_server, games):
    list_path = _filtered_list_path()
    authenticated_page.goto(f"{live_server.url}{list_path}")
    authenticated_page.click('a[href*="/edit?next="]')
    expect(authenticated_page).to_have_url(re_escape_contains("/edit?next="))
    authenticated_page.fill('input[name="name"]', "Alpha Renamed")
    authenticated_page.click('button[type="submit"]')
    expect(authenticated_page).to_have_url(f"{live_server.url}{list_path}")


def test_deleting_a_game_from_its_detail_page_lands_on_the_list(
    authenticated_page, live_server, games
):
    game = games[0]
    authenticated_page.goto(
        f"{live_server.url}{reverse('games:view_game', args=[game.id])}"
    )
    authenticated_page.click('a:has-text("Delete")')
    authenticated_page.click('button:has-text("Delete")')
    expect(authenticated_page).to_have_url(
        f"{live_server.url}{reverse('games:list_games')}"
    )
    assert not Game.objects.filter(id=game.id).exists()


def re_escape_contains(fragment: str):
    import re

    return re.compile(re.escape(fragment))
```

- [ ] **Step 2: Run it**

```bash
make test-e2e
```

`ARGS` does not scope this target — it appends to `pytest e2e/`, so the whole e2e suite runs. Do not run it while `make dev` is up: the watchers rewrite the served assets mid-run and produce mass phantom failures.

Expected: both new tests PASS.

- [ ] **Step 3: Full gate**

```bash
make check
```

- [ ] **Step 4: Commit**

```bash
git add e2e/test_return_to_origin_e2e.py
git commit -m "test(e2e): prove mutations return to the filtered list"
```

---

## Verification

After Task 7, confirm the issue's three symptoms are gone:

1. Visit a game detail, navigate to the platforms list, edit a platform, save — you land on the platforms list, not the game.
2. Filter the games list, page to 2, edit a game, save — you land on the filtered page 2.
3. `grep -rn "return_path" games/ common/` prints nothing.

Then close https://github.com/KucharczykL/timetracker/issues/517.
