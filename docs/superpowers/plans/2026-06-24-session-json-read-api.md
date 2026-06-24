# Session JSON Read API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two authenticated, resource-shaped JSON read endpoints for `Session` (`GET /api/session/` list + `GET /api/session/{id}` detail) and turn on API-wide auth, as the first slice of the JSON-API foundation.

**Architecture:** Extend the existing django-ninja API (`games/api.py`). Flip `NinjaAPI` to `auth=django_auth` (session-cookie auth, closes the pre-existing open-API hole). Add resource-shaped Ninja `Schema`s with resolvers for the computed fields, reusing the HTML list's filter (`parse_session_filter`) and sort (`parse_find_filter` + `apply_sort`) helpers so the JSON list takes the same `?filter=`/`?sort=`/`?page=` vocabulary. Pagination via a direct `Paginator` at a fixed page size.

**Tech Stack:** Django 6, django-ninja, pytest-django, Playwright (e2e).

## Global Constraints

- **Resource-shaped JSON only** — raw fields, ISO-8601 UTC timestamps, durations in seconds, nested id-bearing summary objects. No formatted strings, no hrefs, no "now"/mark rendering. (Client owns presentation + routing.)
- **`auth=django_auth` is API-wide** — every endpoint requires a logged-in session; GET is CSRF-safe, unsafe methods need the existing `X-CSRFToken` header (already sent by all browser callers).
- **Single-user assumption** — endpoints are intentionally unscoped by user. If multi-user is ever added, every read endpoint here leaks without `.filter(user=…)`.
- **Pagination envelope key is `items`** (`{items, count, page, page_size, num_pages}`) — one convention across the whole API.
- **Session field is `modified_at`**, not `updated_at`.
- **Replicate current `is_manual` behavior; do not change it** — this slice ships data, not behavior fixes.
- Spec: `docs/superpowers/specs/2026-06-24-session-json-read-api-design.md`.

---

## File structure

- `games/api.py` — **modify**. Flip `NinjaAPI` auth; add schemas (`PlatformOut`, `GameOut`, `DeviceOut`, `SessionOut`, `SessionListOut`), a `PAGE_SIZE` constant, and the two GET handlers on the existing `session_router`.
- `tests/test_api.py` — **create**. Auth regression, detail shape + `is_manual` matrix + 404, list envelope + filter/sort/page parity.
- `e2e/test_api_csrf_e2e.py` — **create**. Real-browser device PATCH still returns 200 (not 403) after `csrf=True`.

No model, template, migration, or TS changes.

---

### Task 1: Turn on API-wide auth

**Files:**
- Modify: `games/api.py:8` (imports), `games/api.py:12` (`api = NinjaAPI()`)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: existing routers in `games/api.py`.
- Produces: `api` now rejects anonymous requests with `401`. All later endpoints inherit this auth.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api.py`:

```python
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


def test_existing_endpoint_requires_auth():
    # Anonymous client hits an existing GET endpoint -> 401 after API-wide auth.
    response = Client().get("/api/platforms/groups")
    assert response.status_code == 401


def test_existing_endpoint_allows_logged_in(auth_client):
    response = auth_client.get("/api/platforms/groups")
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_api.py::test_existing_endpoint_requires_auth -v`
Expected: FAIL — returns `200` (API currently open), not `401`.

- [ ] **Step 3: Make the minimal change**

In `games/api.py`, change the import line (currently line 8) to add `django_auth`, and the api construction (line 12):

```python
from ninja import Field, ModelSchema, NinjaAPI, Router, Schema, Status
from ninja.security import django_auth
```

```python
api = NinjaAPI(auth=django_auth)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest-django pytest tests/test_api.py -v`
Expected: PASS (both auth tests).

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `make test`
Expected: PASS. Existing API tests (`test_paths_return_200.py`, `test_middleware_integration.py`) already `force_login` in `setUp`, so they stay green. If `test_paths_return_200` fails, confirm its `setUp` still calls `force_login` — do **not** remove it (it is what keeps `/api/platforms/groups` green under auth).

- [ ] **Step 6: Commit**

```bash
git add games/api.py tests/test_api.py
git commit -m "feat(api): require session auth API-wide

Closes the pre-existing open-API hole. django_auth (SessionAuth) gates
every endpoint; GET is CSRF-safe, unsafe callers already send X-CSRFToken.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Session detail endpoint + schemas

**Files:**
- Modify: `games/api.py` (add schemas + `get_session` handler near the existing `session_router` block, ~line 156–174)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `auth` from Task 1; `Session`, `Game`, `Platform`, `Device` models (already imported).
- Produces:
  - `class PlatformOut(Schema)` → `{name: str, icon: str}`
  - `class GameOut(Schema)` → `{id: int, name: str, platform: PlatformOut | None}`
  - `class DeviceOut(Schema)` → `{id: int, name: str, type: str}`
  - `class SessionOut(Schema)` → `{id, game: GameOut|None, device: DeviceOut|None, timestamp_start: datetime, timestamp_end: datetime|None, duration_manual_seconds: int, is_manual: bool, note: str, emulated: bool, created_at: datetime, modified_at: datetime}` with `resolve_duration_manual_seconds(obj)` and `resolve_is_manual(obj)` staticmethods.
  - `GET /api/session/{session_id}` → `SessionOut`, `404` if absent.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
from datetime import datetime, timedelta, timezone as dt_timezone

from games.models import Device, Game, Platform, Session


def _make_session(**overrides):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Hades", platform=platform)
    device = Device.objects.create(name="Deck", type="h")
    fields = dict(
        game=game,
        device=device,
        timestamp_start=datetime(2026, 6, 24, 18, 0, tzinfo=dt_timezone.utc),
        timestamp_end=None,
        duration_manual=timedelta(0),
        note="",
        emulated=False,
    )
    fields.update(overrides)
    return Session.objects.create(**fields)


def test_session_detail_shape(auth_client):
    session = _make_session(
        timestamp_end=datetime(2026, 6, 24, 19, 0, tzinfo=dt_timezone.utc),
        duration_manual=timedelta(minutes=30),
    )
    response = auth_client.get(f"/api/session/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["game"] == {
        "id": session.game.id,
        "name": "Hades",
        "platform": {"name": "PC", "icon": session.game.platform.icon},
    }
    assert data["device"] == {"id": session.device.id, "name": "Deck", "type": "h"}
    assert data["timestamp_start"] == "2026-06-24T18:00:00Z"
    assert data["timestamp_end"] == "2026-06-24T19:00:00Z"
    assert data["duration_manual_seconds"] == 1800
    assert data["is_manual"] is True
    assert data["emulated"] is False
    assert "modified_at" in data and "created_at" in data


def test_session_detail_open_session_null_end(auth_client):
    session = _make_session()  # timestamp_end=None, manual=0
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["timestamp_end"] is None
    assert data["duration_manual_seconds"] == 0
    assert data["is_manual"] is False


@pytest.mark.parametrize(
    "manual,expected",
    [
        (timedelta(0), False),
        (timedelta(minutes=5), True),
        (timedelta(minutes=-5), True),  # negative still counts as manual
    ],
)
def test_session_is_manual_matrix(auth_client, manual, expected):
    # NB: Session.save() coerces a None duration_manual to timedelta(0),
    # so the null case is unreachable via normal save and not tested here.
    # is_manual is shipped explicitly (not derived client-side) to stay correct
    # for negative/sub-second durations and to match server display exactly.
    session = _make_session(duration_manual=manual)
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["is_manual"] is expected


def test_session_detail_404(auth_client):
    response = auth_client.get("/api/session/999999")
    assert response.status_code == 404


def test_session_detail_requires_auth():
    session = _make_session()
    assert Client().get(f"/api/session/{session.id}").status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest-django pytest tests/test_api.py -k session_detail -v`
Expected: FAIL — endpoint `/api/session/{id}` does not exist (404 for all, including the shape test).

- [ ] **Step 3: Add schemas + handler**

In `games/api.py`, add a `from datetime import timedelta` to the existing datetime import line if not present (currently `from datetime import date, datetime`), and in the `session_router` block (after line 156 `session_router = Router()`), add:

```python
class PlatformOut(Schema):
    name: str
    icon: str


class GameOut(Schema):
    id: int
    name: str
    platform: PlatformOut | None = None


class DeviceOut(Schema):
    id: int
    name: str
    type: str


class SessionOut(Schema):
    id: int
    game: GameOut | None = None
    device: DeviceOut | None = None
    timestamp_start: datetime
    timestamp_end: datetime | None = None
    duration_manual_seconds: int
    is_manual: bool
    note: str
    emulated: bool
    created_at: datetime
    modified_at: datetime

    @staticmethod
    def resolve_duration_manual_seconds(obj: Session) -> int:
        return int(obj.duration_manual.total_seconds()) if obj.duration_manual else 0

    @staticmethod
    def resolve_is_manual(obj: Session) -> bool:
        return obj.is_manual()


@session_router.get("/{session_id}", response=SessionOut)
def get_session(request, session_id: int):
    return get_object_or_404(
        Session.objects.select_related("game", "game__platform", "device"),
        id=session_id,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest-django pytest tests/test_api.py -k session_detail -v`
Expected: PASS.

Run the full new-tests file: `uv run --with pytest-django pytest tests/test_api.py -v`
Expected: PASS (detail + is_manual matrix + auth).

- [ ] **Step 5: Type-check**

Run: `make typecheck`
Expected: PASS (resolvers typed; `obj: Session`).

- [ ] **Step 6: Commit**

```bash
git add games/api.py tests/test_api.py
git commit -m "feat(api): resource-shaped GET /api/session/{id}

Nested id-bearing game/device/platform summaries, ISO-UTC timestamps,
duration_manual_seconds + explicit is_manual (not client-derivable).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Session list endpoint

**Files:**
- Modify: `games/api.py` (add `PAGE_SIZE`, `SessionListOut`, `list_sessions_api` handler; new imports)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `SessionOut` (Task 2); `parse_session_filter` (`games/filters.py`), `parse_find_filter` + `apply_sort` + `SESSION_SORTS` + `SESSION_DEFAULT_SORT` (`games/sorting.py`), `Paginator` (`django.core.paginator`).
- Produces:
  - `PAGE_SIZE = 10` (module constant in `games/api.py`)
  - `class SessionListOut(Schema)` → `{items: list[SessionOut], count: int, page: int, page_size: int, num_pages: int}`
  - `GET /api/session/` with params `filter: str = ""`, `sort: str = ""`, `page: int = 1` → `SessionListOut`. `sort` is consumed via `parse_find_filter(request)` (it reads `request.GET["sort"]`); it is declared so it appears in the OpenAPI schema.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_session_list_envelope(auth_client):
    for _ in range(3):
        _make_session()
    data = auth_client.get("/api/session/").json()
    assert set(data.keys()) == {"items", "count", "page", "page_size", "num_pages"}
    assert data["count"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["num_pages"] == 1
    assert len(data["items"]) == 3
    assert "id" in data["items"][0] and "game" in data["items"][0]


def test_session_list_pagination(auth_client):
    for _ in range(12):
        _make_session()
    page1 = auth_client.get("/api/session/").json()
    assert page1["count"] == 12
    assert page1["num_pages"] == 2
    assert len(page1["items"]) == 10
    page2 = auth_client.get("/api/session/?page=2").json()
    assert page2["page"] == 2
    assert len(page2["items"]) == 2


def test_session_list_sort_parity(auth_client):
    older = _make_session(
        timestamp_start=datetime(2020, 1, 1, tzinfo=dt_timezone.utc)
    )
    newer = _make_session(
        timestamp_start=datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
    )
    ascending = auth_client.get("/api/session/?sort=date").json()["items"]
    ids = [row["id"] for row in ascending]
    assert ids.index(older.id) < ids.index(newer.id)


def test_session_list_filter_parity(auth_client):
    import json

    keep = _make_session()
    other_platform = Platform.objects.create(name="Switch")
    other_game = Game.objects.create(name="Celeste", platform=other_platform)
    _make_session(game=other_game)
    # Structured filter: game name includes "Hades".
    session_filter = {
        "AND": [
            {
                "criterion": "game",
                "modifier": "INCLUDES",
                "value": [keep.game.id],
            }
        ]
    }
    response = auth_client.get(
        "/api/session/", {"filter": json.dumps(session_filter)}
    )
    items = response.json()["items"]
    assert [row["id"] for row in items] == [keep.id]


def test_session_list_requires_auth():
    assert Client().get("/api/session/").status_code == 401
```

> Note for the implementer: the exact `filter` JSON shape in `test_session_list_filter_parity` must match what `parse_session_filter` deserializes. Before writing the test, confirm the structure by reading `games/filters.py` (`parse_session_filter` / `SessionFilter`) and an existing filter test in `tests/test_filters.py`; adjust the dict to the real schema if it differs from the sketch above. The assertion (only the matching session returned) is the contract.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest-django pytest tests/test_api.py -k session_list -v`
Expected: FAIL — `/api/session/` (list) does not exist; the trailing-slash GET currently 404s.

- [ ] **Step 3: Add the constant, schema, imports, and handler**

In `games/api.py` add imports near the top:

```python
from django.core.paginator import Paginator

from games.filters import parse_session_filter
from games.sorting import (
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
)
```

Add the module constant (top of file, after `NOW_FACTORY`):

```python
PAGE_SIZE = 10
```

In the `session_router` block, after `SessionOut`, add:

```python
class SessionListOut(Schema):
    items: list[SessionOut]
    count: int
    page: int
    page_size: int
    num_pages: int


@session_router.get("/", response=SessionListOut)
def list_sessions_api(request, filter: str = "", sort: str = "", page: int = 1):
    sessions = Session.objects.select_related("game", "game__platform", "device")
    if filter:
        session_filter = parse_session_filter(filter)
        if session_filter is not None:
            sessions = sessions.filter(session_filter.to_q())
    # `sort` is read from request.GET by parse_find_filter; declared above so it
    # appears in the OpenAPI schema. Unknown sort keys are silently ignored.
    sort_result = apply_sort(
        sessions, parse_find_filter(request), SESSION_SORTS, SESSION_DEFAULT_SORT
    )
    paginator = Paginator(sort_result.queryset, PAGE_SIZE)
    page_obj = paginator.get_page(page)
    return {
        "items": list(page_obj.object_list),
        "count": paginator.count,
        "page": page_obj.number,
        "page_size": PAGE_SIZE,
        "num_pages": paginator.num_pages,
    }
```

> Implementer check: confirm `apply_sort(...)` returns an object with a `.queryset` attribute (read `games/sorting.py:116`). If the attribute name differs, use the real one. The HTML view does `sort = apply_sort(...)` then `sessions = sort.queryset`, so `.queryset` is expected.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest-django pytest tests/test_api.py -k session_list -v`
Expected: PASS (envelope, pagination, sort parity, filter parity, auth).

Run the whole file: `uv run --with pytest-django pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + type-check**

Run: `make lint && make typecheck`
Expected: PASS. (If ruff flags the unused `sort` parameter, keep it — it documents the OpenAPI param; add a `# noqa` only if the project's ruff config actually errors, which for function args it does not by default.)

- [ ] **Step 6: Commit**

```bash
git add games/api.py tests/test_api.py
git commit -m "feat(api): resource-shaped GET /api/session/ list

Reuses parse_session_filter + parse_find_filter/apply_sort so the JSON
list takes the same ?filter=/?sort=/?page= vocabulary as the HTML list.
items-keyed pagination envelope at fixed PAGE_SIZE.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: e2e CSRF regression (real browser)

**Files:**
- Create: `e2e/test_api_csrf_e2e.py`

**Interfaces:**
- Consumes: the running app with API-wide auth (Tasks 1–3); the session-list page's device dropdown (`SessionDeviceSelector` → `select.ts` PATCH to `/api/session/{id}/device`).
- Produces: a browser-level assertion that the device PATCH still returns `200` (not `403`) after `csrf=True`. The pytest `Client` is CSRF-exempt, so only a real browser catches a CSRF regression.

> Why this task is separate: it is the only test that exercises the real CSRF path. Read an existing e2e test (`e2e/test_custom_elements_e2e.py` for the login fixture, `e2e/test_widgets_e2e.py`) first and mirror its login + `live_server` + page setup conventions exactly.

- [ ] **Step 1: Write the test**

Create `e2e/test_api_csrf_e2e.py`. Mirror the existing e2e login/fixtures; the core assertion:

```python
# Mirror the login + live_server setup from e2e/test_custom_elements_e2e.py.
# After logging in and seeding one session with a device, drive the session
# list page and change the device via the dropdown, capturing the PATCH.

def test_device_patch_passes_csrf(page, live_server, logged_in, seeded_session):
    page.goto(f"{live_server.url}/session/list")
    with page.expect_response(
        lambda r: "/api/session/" in r.url
        and "/device" in r.url
        and r.request.method == "PATCH"
    ) as response_info:
        # open the device dropdown for the seeded row and pick a different device
        page.locator(f"#session-row-{seeded_session.id} [data-session-device]").click()
        page.get_by_role("option", name="Deck").click()
    response = response_info.value
    assert response.status == 200, (
        f"device PATCH returned {response.status} — CSRF likely rejected "
        f"(expected 200 with X-CSRFToken under django_auth)"
    )
```

> Implementer: the exact selectors (`[data-session-device]`, the option text) and the fixtures (`logged_in`, `seeded_session`) must be adapted to the real markup of `SessionDeviceSelector` and the e2e fixtures in `e2e/conftest.py`. Inspect the rendered dropdown (read `common/components/domain.py` `SessionDeviceSelector` and `ts/elements/behaviors/select.ts`) to get the trigger/option selectors right. The assertion — PATCH returns `200` — is the contract; the interaction details are yours to make real.

- [ ] **Step 2: Build TS + run the test to verify it passes**

Run: `make ts`
Then: `make test-e2e` (or target the file: `uv run pytest e2e/test_api_csrf_e2e.py -v`)
Expected: PASS — PATCH returns `200`. If it returns `403`, the CSRF wiring regressed: confirm `select.ts:47` still sends `X-CSRFToken` and the `csrftoken` cookie is set on the page.

- [ ] **Step 3: Commit**

```bash
git add e2e/test_api_csrf_e2e.py
git commit -m "test(e2e): device PATCH still passes CSRF under API-wide auth

Unit Client is CSRF-exempt; only a real browser catches a CSRF
regression after enabling django_auth (csrf=True).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Full verification gate

**Files:** none (verification only).

- [ ] **Step 1: Run the full aggregate check**

Run: `make check`
Expected: PASS — lint + format check + mypy + ts-check + drift gates + tests.

- [ ] **Step 2: Run e2e**

Run: `make test-e2e`
Expected: PASS, including the new CSRF regression test.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Run `make dev`, log in, then:
- `GET /api/session/` and `/api/session/<id>` (browser, logged in) → documented JSON shapes.
- Log out / fresh incognito → both endpoints return `401`.

- [ ] **Step 4: Final commit (only if any fixups were made)**

```bash
git add -A
git commit -m "chore(api): verification fixups for session JSON read API"
```

---

## Self-review notes (author)

- **Spec coverage:** resource schema (Task 2), `is_manual` explicit + matrix (Task 2), `modified_at` (Task 2), dropped `duration_total_seconds` (absent by design — Task 2 schema), nested summaries (Task 2), list filter/sort/page parity (Task 3), `items` envelope (Task 3), API-wide auth (Task 1), auth regression tests (Tasks 1–3), e2e CSRF regression (Task 4), single-user/no-IDOR (Global Constraints — no per-user filter by design), client-owns-routing (no hrefs in schema). All spec sections map to a task.
- **No `?limit` honored:** Task 3 uses a direct `Paginator` at `PAGE_SIZE` rather than `common.utils.paginate` (which reads `?limit` and returns `page_obj=None` for `limit=0`) — avoids that footgun and honors the fixed-page-size contract.
- **Type consistency:** `SessionOut`/`GameOut`/`DeviceOut`/`PlatformOut`/`SessionListOut` names and `resolve_duration_manual_seconds`/`resolve_is_manual` are referenced identically across Tasks 2–3.
