# Recency-ranked SearchSelect Prefetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return recently used devices and platforms first for blank SearchSelect prefetches while retaining alphabetical typed-search results.

**Architecture:** Keep `SearchSelect` unchanged. Rank results inside its two existing endpoint handlers only when `q` is blank; keep the current alphabetical ordering otherwise.

**Tech Stack:** Django ORM, Django Ninja, pytest-django, SQLite.

## Global Constraints

- Run project commands through `make`.
- Preserve the endpoint JSON schema and limit behavior.
- Device recency is `Session.timestamp_start`.
- Platform recency is the newest related `Game.updated_at` or `Purchase.updated_at`.
- Never alter the alphabetical ordering of non-empty searches.

---

### Task 1: Add API regression tests

**Files:**

- Modify: `tests/test_api.py`

**Interfaces:**

- Consumes: `GET /api/devices/search` and `GET /api/platforms/search`.
- Produces: tests for blank-query recency and typed-query alphabetical ordering.

- [ ] **Step 1: Write failing tests**

```python
def test_device_search_blank_query_orders_by_most_recent_session(auth_client):
    desktop = Device.objects.create(name="Desktop")
    deck = Device.objects.create(name="Steam Deck")
    _make_session(device=desktop, timestamp_start=datetime(2025, 1, 1, tzinfo=dt_timezone.utc))
    _make_session(device=deck, timestamp_start=datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
    rows = auth_client.get("/api/devices/search", {"limit": 10}).json()
    assert [row["value"] for row in rows][:2] == [deck.id, desktop.id]


def test_platform_search_blank_query_uses_newest_game_or_purchase(auth_client):
    atari = Platform.objects.create(name="Atari")
    switch = Platform.objects.create(name="Switch")
    old_game = Game.objects.create(name="Old game", platform=atari)
    recent_purchase = Purchase.objects.create(
        platform=switch, date_purchased=date(2026, 1, 1)
    )
    Game.objects.filter(pk=old_game.pk).update(
        updated_at=datetime(2025, 1, 1, tzinfo=dt_timezone.utc)
    )
    Purchase.objects.filter(pk=recent_purchase.pk).update(
        updated_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
    )
    rows = auth_client.get("/api/platforms/search", {"limit": 10}).json()
    assert [row["value"] for row in rows][:2] == [switch.id, atari.id]


def test_device_search_typed_query_remains_alphabetical(auth_client):
    alpha = Device.objects.create(name="Alpha")
    alpine = Device.objects.create(name="Alpine")
    _make_session(device=alpha, timestamp_start=datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
    _make_session(device=alpine, timestamp_start=datetime(2025, 1, 1, tzinfo=dt_timezone.utc))
    rows = auth_client.get("/api/devices/search", {"q": "Al", "limit": 10}).json()
    assert [row["value"] for row in rows] == [alpha.id, alpine.id]
```

- [ ] **Step 2: Verify red**

Run `make test ARGS="tests/test_api.py -k 'search_blank_query_orders or search_typed_query_remains' -x"`.

Expected: blank-query assertions fail because endpoints sort by `name`.

- [ ] **Step 3: Commit tests**

Run `git add tests/test_api.py` followed by `git commit -m "test: specify recency-ranked search prefetch"`.

### Task 2: Rank the existing empty-query endpoints

**Files:**

- Modify: `games/api.py:167-180`
- Test: `tests/test_api.py`

**Interfaces:**

- Consumes: `q: str = ""`, `limit: int = 10`.
- Produces: unchanged `list[GameOption]` payloads with recency ordering only for blank `q`.

- [ ] **Step 1: Implement the minimal queryset annotations**

```python
if q:
    qs = Device.objects.filter(name__icontains=q).order_by("name")
else:
    qs = Device.objects.annotate(last_used=Max("session__timestamp_start")).order_by(
        F("last_used").desc(nulls_last=True), "-created_at", "name"
    )
```

Add `Case`, `DateTimeField`, `F`, `Max`, `Value`, `When`, `Coalesce`, and
`Greatest` imports, plus the timezone-aware epoch
`datetime(1970, 1, 1, tzinfo=dt_timezone.utc)`. Implement the platform
blank-query branch as:

```python
qs = Platform.objects.annotate(
    last_game_use=Max("game__updated_at"),
    last_purchase_use=Max("purchase__updated_at"),
).annotate(
    last_used=Case(
        When(
            last_game_use__isnull=True,
            last_purchase_use__isnull=True,
            then=Value(None, output_field=DateTimeField()),
        ),
        default=Greatest(
            Coalesce("last_game_use", Value(EPOCH)),
            Coalesce("last_purchase_use", Value(EPOCH)),
        ),
        output_field=DateTimeField(),
    )
).order_by(F("last_used").desc(nulls_last=True), "-created_at", "name")
```

Import `Purchase` from `games.models`. This explicit null branch avoids the
SQLite behavior where `Greatest` returns `NULL` when any operand is null.

- [ ] **Step 2: Verify green**

Run `make test ARGS="tests/test_api.py -k 'search_blank_query_orders or search_typed_query_remains' -x"`.

Expected: the focused regression tests pass.

- [ ] **Step 3: Run the endpoint test file**

Run `make test ARGS="tests/test_api.py -x"`.

Expected: all API tests pass.

- [ ] **Step 4: Commit implementation**

Run `git add games/api.py tests/test_api.py` followed by `git commit -m "feat: rank search prefetch by recency"`.

### Task 3: Full verification

**Files:**

- Verify only: repository-wide checks.

- [ ] **Step 1: Run the repository gate**

Run `make check`.

Expected: exit status 0.

- [ ] **Step 2: Inspect final state**

Run `git status --short` and `git log --oneline -3`.

Expected: no uncommitted implementation files.
