# Honor `sort`/`direction` query params on list views (#68)

## Problem

The stats page (#65) adds "View all (N) →" links from its sorted lists to the
filtered list views. The list views (`list_games`, `list_sessions`,
`list_purchases`) hardcode `order_by(...)` and ignore any sort parameter, so a
"view all" link lands on the right *set* of rows but not in the same *order* the
stats page showed.

`FindFilter` (in `games/filters.py`) already models `sort` / `direction` but is
never parsed or applied anywhere.

Hardcoded orders today:

- `games/views/game.py:59` — `Game.objects.order_by("-created_at")`
- `games/views/session.py:122` — `Session.objects.order_by("-timestamp_start", "created_at")`
- `games/views/purchase.py:122` — `Purchase.objects.order_by("-date_purchased", "-created_at")`

## Goal

Make all three list views honor a `sort` query param (a signed comma-list of
column keys), with every visible column sortable plus the aggregate sorts the
stats page needs for "view all" parity (games-by-playtime, finish-date). Backend
only — no clickable header UI in this issue (tracked in #73).

## Scope decisions (from brainstorming)

- **Sortable set:** all visible list columns, plus stats-parity aggregates
  (playtime, finish date) even where they are not visible columns.
- **UI:** backend only. Honor the query param; do not add clickable column
  headers. File a follow-up issue for the header UI.
- **URL contract:** a single signed comma-list of **public keys** —
  `?sort=-playtime,name`. The `-` attaches to the public key and sets that
  key's direction; the whitelist still maps the key to its internal
  expression+annotation. Bare key = **ascending** (Django semantics, no hidden
  per-key defaults); leading `-` = descending. Rationale: natural multi-column,
  one param, each term self-describes direction, mirrors Django `order_by`, and
  is **forward-compatible to multi-column with zero contract change**.
- **Multi-column:** the backend parses and applies the **full** term list now
  (server-side multi-column works immediately). Only the UI that *generates*
  multi-term URLs (clickable headers, shift-click to add a column) is deferred
  to the follow-up issue.
- **Default ordering:** since bare keys are ascending and signs are explicit,
  each view's default order is itself just a default signed sort string parsed
  by the same machinery — no separate `default_direction` field, no per-key
  tiebreak concept.
- **Module:** new `games/sorting.py` (keeps the already-large `filters.py`
  focused; imports `FindFilter` from it).
- **Purchase name sort:** annotated `Min("games__name")` — one row per purchase,
  no M2M duplication.

## Prerequisite: fix N+1 queries on list rows

The list querysets currently have **no** `select_related`/`prefetch_related`, so
each rendered row lazy-loads its relations. The sort work touches these exact
querysets (and adds aggregate annotations), so the eager-loading fix lands here:

- `list_games` — `Game.objects.select_related("platform")` (icon via
  `NameWithIcon`).
- `list_sessions` — `Session.objects.select_related("game", "game__platform", "device")`.
- `list_purchases` — `Purchase.objects.prefetch_related("games", "games__platform")`
  (M2M rendered by `LinkedPurchase`; confirm `games__platform` need during impl).

These are added to the **base** queryset (before filtering/annotating), so they
compose with `apply_sort`'s annotations.

## Design

### URL contract

`?sort=<signed-key>[,<signed-key>...]` on `list_games`, `list_sessions`,
`list_purchases`. Examples: `?sort=-playtime`, `?sort=status,name`,
`?sort=-date,created`.

- Each term is a public key, optionally prefixed `-`. Bare = ascending; `-` =
  descending (Django `order_by` semantics).
- Terms whose key is not in the model's map are **ignored, and a user-facing
  warning toast is shown** ("Unknown sort field '<key>' was ignored.") — never a
  400. Any remaining valid terms still apply; the page renders normally.
- If `sort` is absent, empty, or has no valid terms → the view's default sort
  string is used (parsed by the same machinery).
- Invalid values never raise.

The warning surfaces drift (e.g. a #65 "view all" link with a stale/typo'd key)
without breaking a user-facing, hand-editable URL. It rides the existing
messages→toast path: `render_page()` serializes `get_messages(request)` into the
`#django-messages` JSON block (`common/layout.py`) and `toast.js` renders it —
works on a full-page GET, which is what #65 links are. No new plumbing.

`sorting.py` itself stays HTTP-free: it *reports* unknown keys; the view emits
the `messages.warning`.

Pagination already preserves the param: `_page_url` (in
`common/components/primitives.py`) copies `request.GET` and only replaces `page`.

### `games/sorting.py`

Named string roles (PEP 695 transparent aliases — `requires-python >=3.13`).
They read like TS `type X = string`: no runtime cost, no wrapping ceremony, but
each `str` in a signature now says *which* string it is:

```python
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
```

All current sorts use `Aggregate` subclasses (`Sum`/`Max`/`Min`); if a
non-aggregate annotation (`F`, `ExpressionWrapper`) is ever needed, widen
`Annotations`' value to `Combinable` then.

Direction is never stored on the spec — it comes from the sign in the URL term.
Cross-relation sorts use **annotated aggregates** (`Sum`/`Max`/`Min`), which
group by the model PK and therefore produce no duplicate rows. Bare
`order_by("relation__field")` is never used for to-many relations.

#### Per-model maps + default sort strings

All three maps are typed `SortMap` (`dict[SortKey, SortSpec]`); each
`*_DEFAULT_SORT` is a `SortString`.

**`GAME_SORTS`** — `GAME_DEFAULT_SORT = "-created"`:

| key | expression | annotate |
|---|---|---|
| name | `name` | — |
| sort_name | `sort_name` | — |
| year | `year_released` | — |
| status | `status` | — |
| wikidata | `wikidata` | — |
| created | `created_at` | — |
| playtime | `total_playtime` | `Sum("sessions__duration_total")` |
| finished | `last_finished` | `Max("playevents__ended")` |

**`SESSION_SORTS`** — `SESSION_DEFAULT_SORT = "-date,created"`
(reproduces today's `order_by("-timestamp_start", "created_at")`):

| key | expression | annotate |
|---|---|---|
| name | `game__sort_name` | — (to-one; safe) |
| date | `timestamp_start` | — |
| duration | `duration_total` | — |
| device | `device__name` | — (to-one; safe) |
| created | `created_at` | — |

**`PURCHASE_SORTS`** — `PURCHASE_DEFAULT_SORT = "-purchased,-created"`
(reproduces today's `order_by("-date_purchased", "-created_at")`):

| key | expression | annotate |
|---|---|---|
| name | `first_game_name` | `Min("games__name")` |
| type | `type` | — |
| price | `converted_price` | — |
| infinite | `infinite` | — |
| purchased | `date_purchased` | — |
| refunded | `date_refunded` | — |
| created | `created_at` | — |
| finished | `last_finished` | `Max("games__playevents__ended")` |

> `game__sort_name` / `device__name` are to-one relations — no duplication, so
> no annotation needed.
> The `finished` purchase key gives the stats "view all" finish-date parity.
> Model field names confirmed against `games/models.py`: `infinite`,
> `converted_price`, `date_purchased`, `date_refunded`, `type`; session
> `duration_total` is a `GeneratedField` (orderable).

#### Term parsing

```python
class SortTerm(NamedTuple):
    key: SortKey
    descending: bool      # True = "-key" (desc), False = bare key (asc)

type SortMap = dict[SortKey, SortSpec]

class ParsedSort(NamedTuple):
    terms: list[SortTerm]
    unknown: list[SortKey]   # keys not in the map — the view turns these into warnings

def parse_sort_terms(raw: SortString, sort_map: SortMap) -> ParsedSort:
    terms, unknown = [], []
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

### Apply helper

```python
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
```

The full term list is applied (server-side multi-column). `SortResult.terms` is
what the future header UI (#73) consumes; `SortResult.unknown` is what the view
turns into warning toasts.

### FindFilter parsing

```python
def parse_find_filter(request: HttpRequest) -> FindFilter:
    return FindFilter(sort=request.GET.get("sort") or None)  # FindFilter.sort holds a SortString
```

`FindFilter.direction` is **not used** by #68 — direction lives in the sign of
each `sort` term, not a separate field. Nothing serializes it today (the
`FilterPreset.find_filter` `JSONField` is currently unpopulated; `FindFilter`
has no JSON round-trip), so #68 leaves the field untouched rather than churn it.
Whether to remove it or formally wire it is decided in **#74**. Page / per_page
likewise stay with `paginate()`; not wired into `FindFilter` now (YAGNI, #74).

### View wiring (×3)

In each list view, remove the hardcoded `.order_by(...)` from the base queryset
and, after filtering and before `paginate()`:

```python
find = parse_find_filter(request)
sort = apply_sort(games, find, GAME_SORTS, GAME_DEFAULT_SORT)  # sort: SortResult
games = sort.queryset
for key in sort.unknown:
    messages.warning(request, f"Unknown sort field '{key}' was ignored.")
```

(`session.py` / `purchase.py` analogous with their maps + default sort strings.)

## Testing

`tests/test_sorting.py`:

- Default order unchanged for each model when no `sort` param is present
  (regression guard against the removed hardcoded `order_by` — the default sort
  string must reproduce the old order exactly).
- Each key in each map sorts ascending (bare) and descending (`-` prefix).
- Multi-column term list applies in order (e.g. `?sort=status,name`).
- Unknown keys are reported in `SortResult.unknown`; the view emits a
  `messages.warning` per unknown key (assert on `get_messages`). A valid key
  emits none.
- An all-invalid/empty `sort` falls back to the default sort string.
- A mixed `?sort=-playtime,bogus` both sorts by `playtime` *and* warns on `bogus`.
- Annotated sorts (game playtime, game/purchase finish date, purchase name)
  return no duplicate rows (`count` equals unsorted `count`).
- `parse_sort_terms` unit tests: signs, whitespace, empty tokens, unknown keys.
- Smoke: `?sort=<key>` and `?sort=-key,key` URLs return 200 for each list view.

## Coordination with #65

#65 (stats "view all" links, still unmerged) generates URLs that pass `sort=`.
Those links **must use the same public sort keys** defined in this spec's maps
(`playtime`, `finished`, etc.). When #65 and #68 both land, verify each "view
all" link's `sort=` matches a key in the target model's `*_SORTS` map and
reproduces the stats list's order. Call this out in the #68 PR description.

## Related follow-ups (filed during design review)

- **#73** — clickable sortable column headers + multi-column UI (consumes
  `SortResult.terms`).
- **#74** — make `FindFilter` the single request parser (sort + pagination +
  free-text); fixes the `paginate()` 10-vs-25 / `limit`-vs-`per_page` mismatch.
- **#75** — purchase list free-text search parity.
- **#76** — extract a shared `list_view` helper across the three list views.

## Out of scope (follow-up issue)

Clickable sortable column headers (asc/desc indicator, toggle on click) and the
multi-column UI affordance (shift-click to add a column → multi-term `?sort=`
URL). The backend `apply_sort` already returns `SortResult.terms` and applies
the full term list, so this is UI-only work. Tracked in **#73**.
