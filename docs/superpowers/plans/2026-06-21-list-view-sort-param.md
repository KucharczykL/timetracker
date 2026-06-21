# List-view `sort` query param Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `list_games`, `list_sessions`, `list_purchases` honor a signed comma-list `?sort=` query param (e.g. `?sort=-playtime,name`), with every visible column sortable plus stats-parity aggregates (playtime, finish date).

**Architecture:** A new `games/sorting.py` defines a per-model whitelist (`SortKey → SortSpec`), a pure parser (`parse_sort_terms`), and an applier (`apply_sort`) that annotates-then-orders and reports unknown keys. Each list view replaces its hardcoded `order_by(...)` with `apply_sort(...)`, eager-loads row relations, and turns unknown keys into warning toasts. Backend only — clickable-header UI is #73.

**Tech Stack:** Django 6, Python 3.13, pytest + pytest-django. Components/views per `CLAUDE.md`.

## Global Constraints

- **Never write to `GeneratedField`s** (`duration_calculated`, `duration_total`, `price_per_game`, `days_to_finish`) — they are read/order-only.
- **Complete-word identifiers** (Python + JS): `descending` not `desc_flag`, `queryset` not `qs` in real code.
- **Cross-relation sorts use annotated aggregates** (`Sum`/`Max`/`Min`) — never bare `order_by("relation__field")` for to-many relations (avoids row duplication). To-one relations (`game__sort_name`, `device__name`) may be ordered directly.
- **Name primitive roles** with PEP 695 transparent aliases (`type SortKey = str`), per the new `CLAUDE.md` convention.
- **`sorting.py` stays HTTP-free** — it reports unknown keys; the view emits `messages.warning`.
- Tests run with `uv run --with pytest-django pytest`.
- Spec: `docs/superpowers/specs/2026-06-21-list-view-sort-param-design.md`.

---

## File Structure

- **Create** `games/sorting.py` — all sorting logic (aliases, `SortSpec`, `SortTerm`, `ParsedSort`, `SortResult`, the three `*_SORTS` maps + `*_DEFAULT_SORT`, `parse_sort_terms`, `apply_sort`, `parse_find_filter`).
- **Create** `tests/test_sorting.py` — unit + integration tests.
- **Modify** `games/views/game.py` — wire sort into `list_games` + `select_related`.
- **Modify** `games/views/session.py` — wire sort into `list_sessions` + `select_related`.
- **Modify** `games/views/purchase.py` — wire sort into `list_purchases` + `prefetch_related`.

---

## Task 1: `sorting.py` core types + `parse_sort_terms`

**Files:**
- Create: `games/sorting.py`
- Test: `tests/test_sorting.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `type SortKey = str`, `type SortString = str`, `type AnnotationName = str`, `type OrderField = str`, `type Annotations = dict[AnnotationName, Aggregate]`
  - `SortSpec(expression: OrderField, annotate: Annotations | None = None)` (frozen dataclass)
  - `SortTerm(NamedTuple)`: `key: SortKey`, `descending: bool`
  - `type SortMap = dict[SortKey, SortSpec]`
  - `ParsedSort(NamedTuple)`: `terms: list[SortTerm]`, `unknown: list[SortKey]`
  - `parse_sort_terms(raw: SortString, sort_map: SortMap) -> ParsedSort`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sorting.py
"""Tests for the list-view sorting system (games/sorting.py)."""

from games.sorting import SortSpec, SortTerm, parse_sort_terms

# A minimal map; parse_sort_terms only checks key membership, not spec internals.
SAMPLE_MAP = {"name": SortSpec("name"), "date": SortSpec("created_at")}


class TestParseSortTerms:
    def test_bare_key_is_ascending(self):
        parsed = parse_sort_terms("name", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("name", False)]
        assert parsed.unknown == []

    def test_dash_prefix_is_descending(self):
        parsed = parse_sort_terms("-date", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("date", True)]

    def test_multi_column_preserves_order(self):
        parsed = parse_sort_terms("date,-name", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("date", False), SortTerm("name", True)]

    def test_unknown_key_is_reported_not_raised(self):
        parsed = parse_sort_terms("bogus", SAMPLE_MAP)
        assert parsed.terms == []
        assert parsed.unknown == ["bogus"]

    def test_mixed_valid_and_unknown(self):
        parsed = parse_sort_terms("-name,bogus", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("name", True)]
        assert parsed.unknown == ["bogus"]

    def test_whitespace_and_empty_tokens_ignored(self):
        parsed = parse_sort_terms(" name , , -date ", SAMPLE_MAP)
        assert parsed.terms == [SortTerm("name", False), SortTerm("date", True)]

    def test_empty_string_yields_nothing(self):
        parsed = parse_sort_terms("", SAMPLE_MAP)
        assert parsed.terms == []
        assert parsed.unknown == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_sorting.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'games.sorting'`.

- [ ] **Step 3: Write minimal implementation**

```python
# games/sorting.py
"""Structured sorting for list views (Stash-inspired, paired with games/filters.py).

A list view maps a public sort key to a SortSpec; the URL ?sort= param is a
signed comma-list of those keys (e.g. "-playtime,name"). See
docs/superpowers/specs/2026-06-21-list-view-sort-param-design.md.
"""

from dataclasses import dataclass
from typing import NamedTuple

from django.db.models import Aggregate

type SortKey = str         # public column key in a *_SORTS map and in a URL term ("playtime", "name")
type SortString = str      # comma-list of signed SortKeys: the URL ?sort= value and *_DEFAULT_SORT ("-date,created")
type AnnotationName = str  # an alias added via .annotate(), then referenced by SortSpec.expression
type OrderField = str      # SortSpec.expression: a real model field path OR an AnnotationName

# alias name -> the ORM aggregate that computes it, applied via queryset.annotate()
# e.g. {"total_playtime": Sum("sessions__duration_total")}
type Annotations = dict[AnnotationName, Aggregate]


@dataclass(frozen=True)
class SortSpec:
    expression: OrderField           # unsigned; a real column path or an AnnotationName
    annotate: Annotations | None = None


class SortTerm(NamedTuple):
    key: SortKey
    descending: bool      # True = "-key" (desc), False = bare key (asc)


type SortMap = dict[SortKey, SortSpec]


class ParsedSort(NamedTuple):
    terms: list[SortTerm]
    unknown: list[SortKey]   # keys not in the map — the view turns these into warnings


def parse_sort_terms(raw: SortString, sort_map: SortMap) -> ParsedSort:
    terms: list[SortTerm] = []
    unknown: list[SortKey] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        descending = token.startswith("-")
        key = token.lstrip("-")
        if key in sort_map:
            terms.append(SortTerm(key, descending))
        else:
            unknown.append(key)
    return ParsedSort(terms, unknown)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest-django pytest tests/test_sorting.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add games/sorting.py tests/test_sorting.py
git commit -m "feat(sorting): SortSpec/SortTerm types + parse_sort_terms (#68)"
```

---

## Task 2: Per-model maps + `apply_sort` + `parse_find_filter`

**Files:**
- Modify: `games/sorting.py`
- Test: `tests/test_sorting.py`

**Interfaces:**
- Consumes: Task 1's `SortSpec`, `SortTerm`, `SortMap`, `parse_sort_terms`; `FindFilter` from `games.filters`.
- Produces:
  - `GAME_SORTS: SortMap`, `GAME_DEFAULT_SORT = "-created"`
  - `SESSION_SORTS: SortMap`, `SESSION_DEFAULT_SORT = "-date,created"`
  - `PURCHASE_SORTS: SortMap`, `PURCHASE_DEFAULT_SORT = "-purchased,-created"`
  - `SortResult(NamedTuple)`: `queryset: QuerySet`, `terms: list[SortTerm]`, `unknown: list[SortKey]`
  - `apply_sort(queryset, find: FindFilter, sort_map: SortMap, default_sort: SortString) -> SortResult`
  - `parse_find_filter(request: HttpRequest) -> FindFilter`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sorting.py`:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.test import RequestFactory

from games.filters import FindFilter
from games.models import Game, Platform, Purchase, Session
from games.sorting import (
    GAME_DEFAULT_SORT,
    GAME_SORTS,
    PURCHASE_DEFAULT_SORT,
    PURCHASE_SORTS,
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
)

ZONEINFO = ZoneInfo(settings.TIME_ZONE)


def _find(sort=None):
    return FindFilter(sort=sort)


@pytest.fixture
def two_games(db):
    platform = Platform.objects.create(name="P", icon="p")
    alpha = Game.objects.create(name="Alpha", sort_name="Alpha", platform=platform)
    beta = Game.objects.create(name="Beta", sort_name="Beta", platform=platform)
    return alpha, beta


class TestApplySortGames:
    def test_name_ascending(self, two_games):
        alpha, beta = two_games
        result = apply_sort(Game.objects.all(), _find("name"), GAME_SORTS, GAME_DEFAULT_SORT)
        assert list(result.queryset) == [alpha, beta]
        assert result.terms[0].key == "name"
        assert result.unknown == []

    def test_name_descending(self, two_games):
        alpha, beta = two_games
        result = apply_sort(Game.objects.all(), _find("-name"), GAME_SORTS, GAME_DEFAULT_SORT)
        assert list(result.queryset) == [beta, alpha]

    def test_default_sort_when_absent_is_created_desc(self, two_games):
        alpha, beta = two_games  # beta created after alpha
        result = apply_sort(Game.objects.all(), _find(None), GAME_SORTS, GAME_DEFAULT_SORT)
        assert list(result.queryset) == [beta, alpha]

    def test_unknown_key_reported_and_falls_back(self, two_games):
        result = apply_sort(Game.objects.all(), _find("bogus"), GAME_SORTS, GAME_DEFAULT_SORT)
        assert result.unknown == ["bogus"]
        assert result.queryset.count() == 2  # still returns rows (default order)

    def test_playtime_annotation_no_duplicate_rows(self, two_games):
        alpha, _ = two_games
        device = None
        Session.objects.create(
            game=alpha,
            timestamp_start=datetime(2022, 1, 1, 10, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 1, 1, 12, tzinfo=ZONEINFO),
        )
        Session.objects.create(
            game=alpha,
            timestamp_start=datetime(2022, 1, 2, 10, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 1, 2, 11, tzinfo=ZONEINFO),
        )
        result = apply_sort(Game.objects.all(), _find("-playtime"), GAME_SORTS, GAME_DEFAULT_SORT)
        # two sessions on alpha must not duplicate the alpha row
        assert result.queryset.count() == 2
        assert list(result.queryset)[0] == alpha  # most playtime first


class TestParseFindFilter:
    def test_reads_sort_param(self):
        request = RequestFactory().get("/x", {"sort": "-playtime,name"})
        assert parse_find_filter(request).sort == "-playtime,name"

    def test_absent_sort_is_none(self):
        request = RequestFactory().get("/x")
        assert parse_find_filter(request).sort is None


class TestSortMapShapes:
    def test_default_sort_keys_exist_in_maps(self):
        # every key referenced by a default sort string must be defined in its map
        for default, sort_map in [
            (GAME_DEFAULT_SORT, GAME_SORTS),
            (SESSION_DEFAULT_SORT, SESSION_SORTS),
            (PURCHASE_DEFAULT_SORT, PURCHASE_SORTS),
        ]:
            for token in default.split(","):
                assert token.lstrip("-") in sort_map
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_sorting.py -v`
Expected: FAIL — `ImportError: cannot import name 'GAME_SORTS'` (and friends).

- [ ] **Step 3: Write minimal implementation**

Add imports at the top of `games/sorting.py` (merge with existing):

```python
from django.db.models import Aggregate, Max, Min, QuerySet, Sum
from django.http import HttpRequest

from games.filters import FindFilter
```

Append to `games/sorting.py`:

```python
# ── Per-model sort maps ─────────────────────────────────────────────────────
# Cross-relation sorts use annotated aggregates (group by PK → no row dup).
# To-one relations (game__sort_name, device__name) are ordered directly.

GAME_SORTS: SortMap = {
    "name": SortSpec("name"),
    "sort_name": SortSpec("sort_name"),
    "year": SortSpec("year_released"),
    "status": SortSpec("status"),
    "wikidata": SortSpec("wikidata"),
    "created": SortSpec("created_at"),
    "playtime": SortSpec("total_playtime", {"total_playtime": Sum("sessions__duration_total")}),
    "finished": SortSpec("last_finished", {"last_finished": Max("playevents__ended")}),
}
GAME_DEFAULT_SORT: SortString = "-created"

SESSION_SORTS: SortMap = {
    "name": SortSpec("game__sort_name"),
    "date": SortSpec("timestamp_start"),
    "duration": SortSpec("duration_total"),
    "device": SortSpec("device__name"),
    "created": SortSpec("created_at"),
}
SESSION_DEFAULT_SORT: SortString = "-date,created"

PURCHASE_SORTS: SortMap = {
    "name": SortSpec("first_game_name", {"first_game_name": Min("games__name")}),
    "type": SortSpec("type"),
    "price": SortSpec("converted_price"),
    "infinite": SortSpec("infinite"),
    "purchased": SortSpec("date_purchased"),
    "refunded": SortSpec("date_refunded"),
    "created": SortSpec("created_at"),
    "finished": SortSpec("last_finished", {"last_finished": Max("games__playevents__ended")}),
}
PURCHASE_DEFAULT_SORT: SortString = "-purchased,-created"


# ── Apply ───────────────────────────────────────────────────────────────────


class SortResult(NamedTuple):
    queryset: QuerySet
    terms: list[SortTerm]    # the order actually applied — #73's header UI consumes this
    unknown: list[SortKey]   # rejected keys — the view turns these into warning toasts


def apply_sort(
    queryset: QuerySet, find: FindFilter, sort_map: SortMap, default_sort: SortString
) -> SortResult:
    terms, unknown = parse_sort_terms(find.sort or "", sort_map)
    if not terms:
        # default_sort is trusted developer config — ignore any "unknown" from it
        terms, _ = parse_sort_terms(default_sort, sort_map)
    annotations: Annotations = {}
    order_by: list[OrderField] = []
    for term in terms:
        spec = sort_map[term.key]
        if spec.annotate:
            annotations.update(spec.annotate)
        order_by.append(("-" if term.descending else "") + spec.expression)
    if annotations:
        queryset = queryset.annotate(**annotations)
    return SortResult(queryset.order_by(*order_by), terms, unknown)


def parse_find_filter(request: HttpRequest) -> FindFilter:
    return FindFilter(sort=request.GET.get("sort") or None)  # FindFilter.sort holds a SortString
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest-django pytest tests/test_sorting.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add games/sorting.py tests/test_sorting.py
git commit -m "feat(sorting): per-model maps, apply_sort, parse_find_filter (#68)"
```

---

## Task 3: Wire `list_games` (sort + N+1 + warnings)

**Files:**
- Modify: `games/views/game.py` (`list_games`, starts line 57; base queryset line 59)
- Test: `tests/test_sorting.py`

**Interfaces:**
- Consumes: `apply_sort`, `parse_find_filter`, `GAME_SORTS`, `GAME_DEFAULT_SORT` from `games.sorting`.
- Produces: `GET /games/?sort=<...>` honored; unknown key → warning message.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sorting.py`:

```python
from django.contrib.messages import get_messages
from django.urls import reverse


@pytest.fixture
def logged_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


class TestListGamesSort:
    def test_sort_param_orders_rows(self, logged_client, two_games):
        alpha, beta = two_games
        response = logged_client.get(reverse("games:list_games"), {"sort": "-name"})
        assert response.status_code == 200
        body = response.content.decode()
        assert body.index("Beta") < body.index("Alpha")

    def test_unknown_sort_emits_warning_message(self, logged_client, two_games):
        response = logged_client.get(reverse("games:list_games"), {"sort": "bogus"})
        assert response.status_code == 200
        warnings = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("bogus" in w for w in warnings)

    def test_valid_sort_emits_no_warning(self, logged_client, two_games):
        response = logged_client.get(reverse("games:list_games"), {"sort": "name"})
        warnings = [str(m) for m in get_messages(response.wsgi_request)]
        assert warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_sorting.py::TestListGamesSort -v`
Expected: FAIL — `test_sort_param_orders_rows` fails (rows still ordered by `-created_at`, so `-name` ignored); `test_unknown_sort_emits_warning_message` fails (no message).

- [ ] **Step 3: Write minimal implementation**

In `games/views/game.py`, add to the imports from `django.contrib`:

```python
from django.contrib import messages
```

Add to the `games.sorting` import (new import line near the other `games.*` imports, e.g. after `from games.filters import parse_game_filter`):

```python
from games.sorting import GAME_DEFAULT_SORT, GAME_SORTS, apply_sort, parse_find_filter
```

Change the base queryset (line 59) from:

```python
    games = Game.objects.order_by("-created_at")
```

to:

```python
    games = Game.objects.select_related("platform")
```

Then, immediately before `games, page_obj, elided_page_range = paginate(request, games)` (line 89), insert:

```python
    sort = apply_sort(games, parse_find_filter(request), GAME_SORTS, GAME_DEFAULT_SORT)
    games = sort.queryset
    for key in sort.unknown:
        messages.warning(request, f"Unknown sort field '{key}' was ignored.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest-django pytest tests/test_sorting.py::TestListGamesSort -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add games/views/game.py tests/test_sorting.py
git commit -m "feat(games): honor ?sort= on list_games + eager-load platform (#68)"
```

---

## Task 4: Wire `list_sessions` (sort + N+1 + warnings)

**Files:**
- Modify: `games/views/session.py` (`list_sessions`, starts line 120; base queryset line 122)
- Test: `tests/test_sorting.py`

**Interfaces:**
- Consumes: `apply_sort`, `parse_find_filter`, `SESSION_SORTS`, `SESSION_DEFAULT_SORT`.
- Produces: `GET /sessions/?sort=<...>` honored; unknown key → warning.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sorting.py`:

```python
class TestListSessionsSort:
    def test_sort_by_duration_descending(self, logged_client, two_games):
        alpha, beta = two_games
        Session.objects.create(
            game=alpha,
            timestamp_start=datetime(2022, 1, 1, 10, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 1, 1, 10, 30, tzinfo=ZONEINFO),  # 30 min
        )
        Session.objects.create(
            game=beta,
            timestamp_start=datetime(2022, 1, 2, 10, tzinfo=ZONEINFO),
            timestamp_end=datetime(2022, 1, 2, 13, tzinfo=ZONEINFO),  # 3 h
        )
        response = logged_client.get(reverse("games:list_sessions"), {"sort": "-duration"})
        assert response.status_code == 200
        body = response.content.decode()
        assert body.index("Beta") < body.index("Alpha")  # longer session first

    def test_unknown_sort_emits_warning(self, logged_client, two_games):
        response = logged_client.get(reverse("games:list_sessions"), {"sort": "nope"})
        warnings = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("nope" in w for w in warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_sorting.py::TestListSessionsSort -v`
Expected: FAIL — sort ignored / no warning.

- [ ] **Step 3: Write minimal implementation**

In `games/views/session.py`, add the imports:

```python
from django.contrib import messages
from games.sorting import (
    SESSION_DEFAULT_SORT,
    SESSION_SORTS,
    apply_sort,
    parse_find_filter,
)
```

Change the base queryset (line 122) from:

```python
    sessions = Session.objects.order_by("-timestamp_start", "created_at")
```

to:

```python
    sessions = Session.objects.select_related("game", "game__platform", "device")
```

Then, immediately before `sessions, page_obj, elided_page_range = paginate(request, sessions)` (line 148), insert:

```python
    sort = apply_sort(sessions, parse_find_filter(request), SESSION_SORTS, SESSION_DEFAULT_SORT)
    sessions = sort.queryset
    for key in sort.unknown:
        messages.warning(request, f"Unknown sort field '{key}' was ignored.")
```

> Note: `last_session = sessions.latest()` (line 145) runs before pagination and is unaffected by `order_by` (`.latest()` uses the model's `get_latest_by`); leave it as-is. The `apply_sort` call goes after it, before `paginate`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest-django pytest tests/test_sorting.py::TestListSessionsSort -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add games/views/session.py tests/test_sorting.py
git commit -m "feat(sessions): honor ?sort= on list_sessions + eager-load relations (#68)"
```

---

## Task 5: Wire `list_purchases` (sort + N+1 + warnings)

**Files:**
- Modify: `games/views/purchase.py` (`list_purchases`, starts line 121; base queryset line 122)
- Test: `tests/test_sorting.py`

**Interfaces:**
- Consumes: `apply_sort`, `parse_find_filter`, `PURCHASE_SORTS`, `PURCHASE_DEFAULT_SORT`.
- Produces: `GET /purchases/?sort=<...>` honored; unknown key → warning; `name`/`finished` aggregate sorts do not duplicate rows.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sorting.py`:

```python
class TestListPurchasesSort:
    @pytest.fixture
    def two_purchases(self, db, two_games):
        alpha, beta = two_games
        cheap = Purchase.objects.create(
            date_purchased=datetime(2022, 1, 1, tzinfo=ZONEINFO),
            price=10,
            converted_price=10,
            platform=alpha.platform,
        )
        cheap.games.add(alpha)
        dear = Purchase.objects.create(
            date_purchased=datetime(2022, 1, 2, tzinfo=ZONEINFO),
            price=90,
            converted_price=90,
            platform=beta.platform,
        )
        dear.games.add(beta)
        return cheap, dear

    def test_sort_by_price_descending(self, logged_client, two_purchases):
        response = logged_client.get(reverse("games:list_purchases"), {"sort": "-price"})
        assert response.status_code == 200
        body = response.content.decode()
        assert body.index("Beta") < body.index("Alpha")  # 90 before 10

    def test_name_aggregate_sort_no_duplicate_rows(self, logged_client, two_purchases):
        # a multi-game purchase must still render exactly one row
        cheap, _ = two_purchases
        from games.models import Game
        extra = Game.objects.create(name="Aaa", sort_name="Aaa", platform=cheap.platform)
        cheap.games.add(extra)
        response = logged_client.get(reverse("games:list_purchases"), {"sort": "name"})
        body = response.content.decode()
        assert body.count("purchase-row-") == 2  # exactly two purchase rows

    def test_unknown_sort_emits_warning(self, logged_client, two_purchases):
        response = logged_client.get(reverse("games:list_purchases"), {"sort": "nope"})
        warnings = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("nope" in w for w in warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest-django pytest tests/test_sorting.py::TestListPurchasesSort -v`
Expected: FAIL — sort ignored / no warning.

- [ ] **Step 3: Write minimal implementation**

In `games/views/purchase.py`, add the imports:

```python
from django.contrib import messages
from games.sorting import (
    PURCHASE_DEFAULT_SORT,
    PURCHASE_SORTS,
    apply_sort,
    parse_find_filter,
)
```

Change the base queryset (line 122) from:

```python
    purchases = Purchase.objects.order_by("-date_purchased", "-created_at")
```

to:

```python
    purchases = Purchase.objects.prefetch_related("games", "games__platform")
```

Then, immediately before `purchases, page_obj, elided_page_range = paginate(request, purchases)` (line 132), insert:

```python
    sort = apply_sort(purchases, parse_find_filter(request), PURCHASE_SORTS, PURCHASE_DEFAULT_SORT)
    purchases = sort.queryset
    for key in sort.unknown:
        messages.warning(request, f"Unknown sort field '{key}' was ignored.")
```

> If `apply_sort` ever yields duplicate purchase rows for an aggregate sort (it should not — `Min`/`Max` group by PK), add `.distinct()` after `order_by` in the view; the `test_name_aggregate_sort_no_duplicate_rows` test guards this.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest-django pytest tests/test_sorting.py::TestListPurchasesSort -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite + lint**

Run: `uv run --with pytest-django pytest tests/test_sorting.py -v && make lint`
Expected: all sorting tests PASS; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add games/views/purchase.py tests/test_sorting.py
git commit -m "feat(purchases): honor ?sort= on list_purchases + eager-load games (#68)"
```

---

## Task 6: Regression smoke + full suite

**Files:**
- Test: `tests/test_sorting.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: confidence that default order is unchanged and every map key returns 200.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sorting.py`:

```python
class TestDefaultOrderUnchanged:
    """The default sort strings must reproduce the pre-#68 hardcoded order."""

    def test_games_default_is_created_descending(self, logged_client, two_games):
        alpha, beta = two_games  # beta newer
        response = logged_client.get(reverse("games:list_games"))
        body = response.content.decode()
        assert body.index("Beta") < body.index("Alpha")


class TestEverySortKeyReturns200:
    def test_all_game_keys(self, logged_client, two_games):
        for key in GAME_SORTS:
            for raw in (key, f"-{key}"):
                response = logged_client.get(reverse("games:list_games"), {"sort": raw})
                assert response.status_code == 200, raw

    def test_all_session_keys(self, logged_client, two_games):
        for key in SESSION_SORTS:
            response = logged_client.get(reverse("games:list_sessions"), {"sort": key})
            assert response.status_code == 200, key

    def test_all_purchase_keys(self, logged_client, two_games):
        for key in PURCHASE_SORTS:
            response = logged_client.get(reverse("games:list_purchases"), {"sort": key})
            assert response.status_code == 200, key
```

- [ ] **Step 2: Run to verify it passes (these assert already-correct behavior)**

Run: `uv run --with pytest-django pytest tests/test_sorting.py::TestDefaultOrderUnchanged tests/test_sorting.py::TestEverySortKeyReturns200 -v`
Expected: PASS. If any `?sort=<key>` returns 500, that key's expression/annotation is wrong — fix the offending `SortSpec` in `games/sorting.py` and re-run.

- [ ] **Step 3: Run the entire project test suite**

Run: `make test`
Expected: PASS (no regressions; note `make test` also collects `e2e/` — a browser must be available, or run `uv run --with pytest-django pytest tests/` to scope to unit/integration tests).

- [ ] **Step 4: Lint + format check**

Run: `make check`
Expected: ruff + format + tests clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_sorting.py
git commit -m "test(sorting): default-order regression + all-keys smoke (#68)"
```

---

## Post-implementation (not tasks)

- **PR description** must call out the #65 coordination (per spec): each stats "view all" link's `sort=` must use a key in the target model's `*_SORTS` map. Verify when #65 lands.
- Follow-ups already filed: #73 (header UI), #74 (FindFilter unify + dead `direction`/`page`/`per_page`), #75 (purchase free-text search), #76 (shared `list_view` helper), #77 (presets persist/restore sort). Do not address them here.
