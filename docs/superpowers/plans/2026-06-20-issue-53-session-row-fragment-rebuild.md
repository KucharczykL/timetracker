# Issue #53 — Rebuild session row fragment via shared builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the htmx session-row fragment reuse the same row builder as the list table, and give the finish/reset actions a real in-place row swap with the navbar playtime totals kept correct via an out-of-band swap.

**Architecture:** Extract the session row's content into one `session_row_data()` dict builder used by both `list_sessions` and a thin `session_row()` Node wrapper (`TableRow(session_row_data(...))`). The navbar's playtime `<li>` becomes a `NavbarPlaytime` component with a stable id so endpoints can return it `hx-swap-oob`. `end_session`/`reset_session_start` return `Fragment(row, NavbarPlaytime(oob=True))`; clone keeps `HX-Refresh`.

**Tech Stack:** Django 6, the in-house Python component system (`common/components`), HTMX, pytest / pytest-django, Playwright (e2e).

## Global Constraints

- Build UI with Python components from `common.components`; never raw HTML strings or Django templates. Builders return `Node`; stringify only at the `HttpResponse` boundary (Django str-encodes content). Do **not** return `SafeText`/`mark_safe` from row builders.
- Never write to `GeneratedField`s (`duration_calculated`, `duration_total`, `days_to_finish`).
- Name variables with complete words (`device_list`, `csrf_token`, `session`, not abbreviations).
- Name compound types explicitly: the row dict is a `TypedDict` (`SessionRowData`).
- Signals handle playtime recalculation — do not recompute `Game.playtime` by hand.
- Run tests with `uv run --with pytest-django pytest`. A bare `pytest` also collects `e2e/` (needs a browser); scope unit/view runs to `tests/...` paths.
- Spec: `docs/superpowers/specs/2026-06-20-issue-53-session-row-fragment-rebuild-design.md`.

---

## File Structure

- `games/views/session.py` — add `SessionRowData` (TypedDict), `session_row_data()`, `session_row()`; refactor `list_sessions` to use them; delete `_session_row_fragment()`; rewire `end_session`, `reset_session_start`, `new_session_from_existing_session`.
- `common/layout.py` — add `NavbarPlaytime()`; embed it inside `Navbar()`.
- `tests/test_session_row.py` — new: unit tests for `session_row_data` / `session_row`.
- `tests/test_navbar_playtime.py` — new: unit tests for `NavbarPlaytime`.
- `tests/test_session_endpoints.py` — new: view tests for the three rewired endpoints.
- `e2e/test_session_inplace_swap_e2e.py` — new: in-place finish swap + navbar update.

---

### Task 1: Extract `session_row_data` + `session_row` (canonical row builder)

**Files:**
- Modify: `games/views/session.py` (the `data["rows"]` comprehension at ~line 126-190, and the `list_sessions` body)
- Test: `tests/test_session_row.py` (create)

**Interfaces:**
- Produces:
  - `class SessionRowData(TypedDict)` with keys `row_id: str`, `hx_trigger: str`, `hx_get: str`, `hx_select: str`, `hx_swap: str`, `cell_data: list[Node]`.
  - `session_row_data(session: Session, device_list, csrf_token: str) -> SessionRowData` — the 6-cell row dict (Name, Date, Duration, Device, Created, Actions) with `row_id="session-row-{pk}"` and the device-change self-refresh hx attrs. For a running session (`timestamp_end is None`) the Actions `ButtonGroup` includes Finish and Reset buttons wired for htmx row swap (`hx_get` to the end/reset URL, `hx_target=f"#session-row-{pk}"`, `hx_swap="outerHTML"`).
  - `session_row(session: Session, device_list, csrf_token: str) -> Node` — `TableRow(session_row_data(...))`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_row.py
import pytest
from django.utils import timezone

from games.models import Device, Game, Platform, Session
from games.views.session import session_row, session_row_data


@pytest.fixture
def running_session(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Celeste", platform=platform)
    device = Device.objects.create(name="Desktop")
    return Session.objects.create(
        game=game, device=device, timestamp_start=timezone.now()
    )


def test_session_row_data_shape(running_session):
    device_list = Device.objects.order_by("name")
    data = session_row_data(running_session, device_list, "tok")
    assert data["row_id"] == f"session-row-{running_session.pk}"
    assert len(data["cell_data"]) == 6
    assert data["hx_select"] == f"#session-row-{running_session.pk}"


def test_session_row_renders_id_and_six_cells(running_session):
    device_list = Device.objects.order_by("name")
    html = str(session_row(running_session, device_list, "tok"))
    assert f'id="session-row-{running_session.pk}"' in html
    assert html.count("<td") + html.count("<th") == 6


def test_running_session_finish_button_targets_row(running_session):
    device_list = Device.objects.order_by("name")
    html = str(session_row(running_session, device_list, "tok"))
    assert f'hx-target="#session-row-{running_session.pk}"' in html
    assert 'hx-swap="outerHTML"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_session_row.py -v`
Expected: FAIL with `ImportError: cannot import name 'session_row'` (and `session_row_data`).

- [ ] **Step 3: Write minimal implementation**

In `games/views/session.py`, add `TypedDict` to the `typing` import (`from typing import Any, TypedDict`) and add `from common.components import Fragment` is already present. Add the type + builders above `list_sessions`:

```python
class SessionRowData(TypedDict):
    row_id: str
    hx_trigger: str
    hx_get: str
    hx_select: str
    hx_swap: str
    cell_data: list[Node]


def session_row_data(
    session: Session, device_list, csrf_token: str
) -> SessionRowData:
    """Canonical session-list row. Single source of truth shared by
    list_sessions and the htmx finish/reset fragments."""
    row_selector = f"#session-row-{session.pk}"
    end_url = reverse("games:list_sessions_end_session", args=[session.pk])
    reset_url = reverse(
        "games:list_sessions_reset_session_start", args=[session.pk]
    )
    actions = ButtonGroup(
        [
            {
                "href": end_url,
                "hx_get": end_url,
                "hx_target": row_selector,
                "hx_swap": "outerHTML",
                "slot": Icon("end"),
                "title": "Finish session now",
                "color": "green",
            }
            if session.timestamp_end is None
            else {},
            {
                "href": reset_url,
                "hx_get": reset_url,
                "hx_target": row_selector,
                "hx_swap": "outerHTML",
                "hx_confirm": "Reset this session's start time to now?",
                "slot": Icon("reset"),
                "title": "Reset start to now",
                "color": "gray",
            }
            if session.timestamp_end is None
            else {},
            {
                "href": reverse("games:edit_session", args=[session.pk]),
                "slot": Icon("edit"),
                "title": "Edit",
            },
            {
                "href": reverse("games:delete_session", args=[session.pk]),
                "slot": Icon("delete"),
                "title": "Delete",
                "color": "red",
            },
        ]
    )
    return SessionRowData(
        row_id=f"session-row-{session.pk}",
        hx_trigger="device-changed from:body",
        hx_get="",
        hx_select=row_selector,
        hx_swap="outerHTML",
        cell_data=[
            NameWithIcon(session=session),
            f"{local_strftime(session.timestamp_start)}"
            f"{f' — {local_strftime(session.timestamp_end, timeformat)}' if session.timestamp_end else ''}",
            session.duration_formatted_with_mark(),
            SessionDeviceSelector(session, device_list, csrf_token),
            session.created_at.strftime(dateformat),
            actions,
        ],
    )


def session_row(session: Session, device_list, csrf_token: str) -> Node:
    """The single-session <tr> node, rendered through the same TableRow
    path the list table uses."""
    return TableRow(session_row_data(session, device_list, csrf_token))
```

Add `TableRow` to the `from common.components import (...)` block (it currently imports `paginated_table_content` but not `TableRow`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest-django pytest tests/test_session_row.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Refactor `list_sessions` to consume the builder**

Replace the inline `"rows": [ {...} for session in sessions]` in the `data` dict with the builder call. First compute the token once near the top of `list_sessions` (after `device_list`): add `csrf_token = get_token(request)`. Then:

```python
        "rows": [
            session_row_data(session, device_list, csrf_token)
            for session in sessions
        ],
```

Delete the now-removed inline row dict (the whole `{ "row_id": ..., ... }` comprehension body, ~line 127-189). Leave `header_action`/`columns` untouched.

- [ ] **Step 6: Run the broader suite to confirm no regression**

Run: `uv run --with pytest-django pytest tests/test_session_row.py tests/test_paths_return_200.py tests/test_rendered_pages.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add games/views/session.py tests/test_session_row.py
git commit -m "refactor(session): extract canonical session_row_data builder

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `NavbarPlaytime` component (OOB-swappable)

**Files:**
- Modify: `common/layout.py` (`Navbar()` at ~line 190-231)
- Test: `tests/test_navbar_playtime.py` (create)

**Interfaces:**
- Produces: `NavbarPlaytime(today_played: str, last_7_played: str, *, oob: bool = False) -> Node` — an `<li id="navbar-playtime">` with the "Today · Last 7 days" label and values; when `oob=True` it carries `hx-swap-oob="true"`. `Navbar()` embeds `NavbarPlaytime(today_played, last_7_played)` in place of the inline `<li>`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_navbar_playtime.py
from common.layout import NavbarPlaytime


def test_navbar_playtime_has_stable_id_and_values():
    html = str(NavbarPlaytime("1 h 00 m", "7 h 00 m"))
    assert 'id="navbar-playtime"' in html
    assert "1 h 00 m" in html
    assert "7 h 00 m" in html
    assert "hx-swap-oob" not in html


def test_navbar_playtime_oob_flag():
    html = str(NavbarPlaytime("1 h 00 m", "7 h 00 m", oob=True))
    assert 'id="navbar-playtime"' in html
    assert 'hx-swap-oob="true"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_navbar_playtime.py -v`
Expected: FAIL with `ImportError: cannot import name 'NavbarPlaytime'`.

- [ ] **Step 3: Write minimal implementation**

In `common/layout.py`, add above `Navbar()`:

```python
def NavbarPlaytime(
    today_played: str, last_7_played: str, *, oob: bool = False
) -> "Node":
    """The navbar 'Today · Last 7 days' totals. Carries a stable id so
    htmx endpoints can refresh it out-of-band after a session change."""
    from common.components import Safe

    oob_attr = ' hx-swap-oob="true"' if oob else ""
    return Safe(
        f'<li id="navbar-playtime"{oob_attr} '
        'class="dark:text-white flex flex-col items-center text-xs">'
        '<span class="flex uppercase gap-1">Today'
        '<span class="dark:text-gray-400">·</span>Last 7 days</span>'
        '<span class="flex items-center gap-1">'
        f'{today_played}<span class="dark:text-gray-400">·</span>'
        f"{last_7_played}</span></li>"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest-django pytest tests/test_navbar_playtime.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Embed it inside `Navbar()`**

In the `Navbar()` `Safe(f"""...""")` markup, replace the inline `<li>` block:

```html
                <li class="dark:text-white flex flex-col items-center text-xs">
                    <span class="flex uppercase gap-1">Today<span class="dark:text-gray-400">·</span>Last 7 days</span>
                    <span class="flex items-center gap-1">{today_played}<span class="dark:text-gray-400">·</span>{last_7_played}</span>
                </li>
```

with:

```python
                {NavbarPlaytime(today_played, last_7_played)}
```

(The surrounding string is already an f-string, so the `{NavbarPlaytime(...)}` call interpolates its rendered HTML.)

- [ ] **Step 6: Run pages tests to confirm navbar still renders**

Run: `uv run --with pytest-django pytest tests/test_navbar_playtime.py tests/test_rendered_pages.py tests/test_paths_return_200.py -v`
Expected: PASS. The navbar still shows the totals (now via the component).

- [ ] **Step 7: Commit**

```bash
git add common/layout.py tests/test_navbar_playtime.py
git commit -m "feat(layout): extract NavbarPlaytime as OOB-swappable component

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Rewire endpoints (in-place swap for end/reset, HX-Refresh for clone)

**Files:**
- Modify: `games/views/session.py` (`_session_row_fragment` delete; `end_session`, `reset_session_start`, `new_session_from_existing_session`)
- Test: `tests/test_session_endpoints.py` (create)

**Interfaces:**
- Consumes: `session_row` (Task 1), `NavbarPlaytime` (Task 2), `model_counts` (`games/views/general.py`).
- Produces: rewired views. `end_session`/`reset_session_start` htmx → `HttpResponse(str(Fragment(session_row(...), NavbarPlaytime(..., oob=True))))`; `new_session_from_existing_session` htmx → `HttpResponse(status=204)` with `HX-Refresh: true`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_endpoints.py
import pytest
from django.urls import reverse
from django.utils import timezone

from games.models import Device, Game, Platform, Session


@pytest.fixture
def auth_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


@pytest.fixture
def running_session(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Hades", platform=platform)
    device = Device.objects.create(name="Deck")
    return Session.objects.create(
        game=game, device=device, timestamp_start=timezone.now()
    )


def test_end_session_htmx_returns_row_and_oob_navbar(auth_client, running_session):
    url = reverse("games:list_sessions_end_session", args=[running_session.pk])
    response = auth_client.get(url, HTTP_HX_REQUEST="true")
    body = response.content.decode()
    assert response.status_code == 200
    assert f'id="session-row-{running_session.pk}"' in body
    assert 'id="navbar-playtime"' in body
    assert 'hx-swap-oob="true"' in body
    running_session.refresh_from_db()
    assert running_session.timestamp_end is not None


def test_reset_session_start_htmx_returns_row_no_refresh_header(
    auth_client, running_session
):
    original_start = running_session.timestamp_start
    url = reverse(
        "games:list_sessions_reset_session_start", args=[running_session.pk]
    )
    response = auth_client.get(url, HTTP_HX_REQUEST="true")
    body = response.content.decode()
    assert response.status_code == 200
    assert f'id="session-row-{running_session.pk}"' in body
    assert 'id="navbar-playtime"' in body
    assert "HX-Refresh" not in response.headers
    running_session.refresh_from_db()
    assert running_session.timestamp_start > original_start


def test_clone_htmx_returns_hx_refresh(auth_client, running_session):
    url = reverse(
        "games:list_sessions_start_session_from_session",
        args=[running_session.pk],
    )
    before = Session.objects.count()
    response = auth_client.get(url, HTTP_HX_REQUEST="true")
    assert response.status_code == 204
    assert response.headers.get("HX-Refresh") == "true"
    assert Session.objects.count() == before + 1


def test_end_session_non_htmx_redirects(auth_client, running_session):
    url = reverse("games:list_sessions_end_session", args=[running_session.pk])
    response = auth_client.get(url)
    assert response.status_code == 302
    assert response.url == reverse("games:list_sessions")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_session_endpoints.py -v`
Expected: FAIL — `end`/`reset` currently return the old fragment / `204+HX-Refresh`; clone returns the old fragment (200, not 204).

- [ ] **Step 3: Delete `_session_row_fragment` and rewire the views**

In `games/views/session.py`:

1. Delete the entire `_session_row_fragment(session)` function (the hand-built 4-column `Tr`).
2. Add imports: at top, `from games.views.general import model_counts`. Ensure `Fragment` and `Node` are imported from `common.components` (they already are). Add `from common.layout import NavbarPlaytime` (the file already imports `render_page` from `common.layout`).
3. Add a small helper near the endpoints:

```python
def _row_with_navbar(request: HttpRequest, session: Session) -> HttpResponse:
    device_list = Device.objects.order_by("name")
    counts = model_counts(request)
    fragment = Fragment(
        session_row(session, device_list, get_token(request)),
        NavbarPlaytime(
            counts["today_played"], counts["last_7_played"], oob=True
        ),
    )
    return HttpResponse(str(fragment))
```

4. Rewrite the endpoints:

```python
@login_required
def new_session_from_existing_session(
    request: HttpRequest, session_id: int
) -> HttpResponse:
    clone_session_by_id(session_id)
    if request.htmx:
        # Clone adds a new row whose position depends on sort + pagination,
        # which a single-row swap cannot place — refresh the list instead.
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    return redirect("games:list_sessions")


@login_required
def end_session(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.timestamp_end = timezone.now()
    session.save()
    if request.htmx:
        return _row_with_navbar(request, session)
    return redirect("games:list_sessions")


@login_required
def reset_session_start(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.timestamp_start = timezone.now()
    session.save()
    if request.htmx:
        return _row_with_navbar(request, session)
    return redirect("games:list_sessions")
```

Note: `clone_session_by_id` already returns the clone; we drop the unused local. Check for an import cycle when adding `from games.views.general import model_counts` at module top — if `general.py` imports from `session.py` it will cycle; in that case import `model_counts` lazily inside `_row_with_navbar` instead.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest-django pytest tests/test_session_endpoints.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Switch the game-detail "Finish" button off the htmx path it never used**

Confirm `games/views/game.py` `_sessions_section` still uses plain `href` for its end button (it does, and it stays full-nav per spec / #55). No change needed — just verify by reading; if it has any `hx_get` to `view_game_end_session`, leave it, since `end_session` still redirects for non-list contexts. (The game-detail button is `href`-only, so it triggers the non-htmx redirect branch.)

- [ ] **Step 6: Run the full unit/view suite**

Run: `uv run --with pytest-django pytest tests/ -v`
Expected: PASS (no regressions; old fragment tests, if any, are gone with the function).

- [ ] **Step 7: Commit**

```bash
git add games/views/session.py tests/test_session_endpoints.py
git commit -m "feat(session): in-place row swap for finish/reset with OOB navbar

Delete stale _session_row_fragment; end_session and reset_session_start
return the canonical row plus an OOB navbar-playtime fragment. Clone keeps
HX-Refresh since it changes row count. Fixes #53.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: E2E — in-place finish swap + navbar update

**Files:**
- Test: `e2e/test_session_inplace_swap_e2e.py` (create)

**Interfaces:**
- Consumes: the rewired list UI (Tasks 1-3). No production code changes.

- [ ] **Step 1: Write the test**

Follow the existing `e2e/` patterns (`live_server`, login helper, Playwright `page`). Inspect `e2e/conftest.py` and an existing test (e.g. `e2e/test_widgets_e2e.py`) for the project's login fixture and `page.goto(live_server.url + ...)` style, and mirror them.

```python
# e2e/test_session_inplace_swap_e2e.py
from django.urls import reverse
from django.utils import timezone

from games.models import Device, Game, Platform, Session


def test_finish_session_swaps_row_in_place(live_server, page, logged_in):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Tunic", platform=platform)
    device = Device.objects.create(name="Desktop")
    session = Session.objects.create(
        game=game, device=device, timestamp_start=timezone.now()
    )

    page.goto(live_server.url + reverse("games:list_sessions"))
    row = page.locator(f"#session-row-{session.pk}")
    row.get_by_title("Finish session now").click()

    # Row updates in place (still present, now shows an end time → em dash).
    page.wait_for_selector(f"#session-row-{session.pk}")
    assert "—" in page.locator(f"#session-row-{session.pk}").inner_text()
    session.refresh_from_db()
    assert session.timestamp_end is not None
```

If the repo has no shared `logged_in` fixture, replicate the login step used by the other e2e tests inline (they all authenticate the same way — copy that fixture/usage).

- [ ] **Step 2: Build TS assets (custom elements served fresh) and run the test**

Run:
```bash
make ts
uv run --with pytest-django --with pytest-playwright pytest e2e/test_session_inplace_swap_e2e.py -v
```
Expected: PASS. (Requires a Chromium; `e2e/conftest.py` prefers a system Chrome, else run `uv run playwright install chromium` once.)

- [ ] **Step 3: Commit**

```bash
git add e2e/test_session_inplace_swap_e2e.py
git commit -m "test(e2e): in-place session-row finish swap

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Full check + cleanup

**Files:** none (verification).

- [ ] **Step 1: Lint + format + tests aggregate**

Run: `make check`
Expected: PASS (ruff lint, format check, ts-check, tests). Fix any unused imports left in `session.py` — particularly `SafeText`, `mark_safe`, `date_filter`, `Span`, `Tr`, `Td` if the deleted `_session_row_fragment` was their only user. Verify with `make lint` and remove the dead imports.

- [ ] **Step 2: Manual smoke (optional but recommended)**

Run `make dev`, open the session list, finish a running session: the row should update in place (end time appears, duration fills) and the navbar "Today · Last 7 days" totals change, with no full-page reload. Reset start on a running session: start time jumps to now, duration resets, navbar updates. Clone ("play" button): list reloads.

- [ ] **Step 3: Commit any cleanup**

```bash
git add -A
git commit -m "chore(session): drop imports orphaned by fragment removal

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Canonical builder (`session_row_data` + `session_row`, both Node) → Task 1. ✓
- `NavbarPlaytime` OOB component → Task 2. ✓
- end/reset in-place swap + OOB navbar; reset drops 204+HX-Refresh → Task 3. ✓
- clone stays HX-Refresh → Task 3 (with documented reason). ✓
- Return `Node`, stringify at HttpResponse boundary → Tasks 1/3 (`HttpResponse(str(Fragment(...)))`). ✓
- List buttons switch to htmx row swap → Task 1 (Finish/Reset in `session_row_data`). ✓
- Delete dead `_session_row_fragment` + old Tr → Task 3. ✓
- game-detail out of scope (#55) → Task 3 Step 5 (verify, no change). ✓
- Tests: unit (row, navbar), view (endpoints), e2e (in-place swap) → Tasks 1-4. ✓

**Placeholder scan:** No TBD/TODO; all steps carry concrete code or commands. The one judgement call (import-cycle on `model_counts`) is given an explicit fallback (lazy import). ✓

**Type consistency:** `session_row_data(session, device_list, csrf_token) -> SessionRowData` and `session_row(session, device_list, csrf_token) -> Node` used identically in Task 1, Task 3, and tests. `NavbarPlaytime(today_played, last_7_played, *, oob=False)` used consistently in Task 2 and Task 3. `_row_with_navbar(request, session) -> HttpResponse` used in both end/reset. ✓
