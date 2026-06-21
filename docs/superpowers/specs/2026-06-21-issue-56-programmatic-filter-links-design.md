# Issue #56 — Programmatic way of defining filters (filter links)

**Date:** 2026-06-21
**Issue:** https://github.com/KucharczykL/timetracker/issues/56

## Problem

Filters can currently only be built through the UI. There is no Python-level way
to construct a link to a filtered list view, so places that *should* link to a
filtered list cannot. The issue cites three call sites:

1. Navbar playtime totals ("today" / "last 7 days") — should link to the matching
   filtered session list.
2. Stats-page tables — rows should link to filtered results.
3. `view_game` tables — should link to filtered list views.

The acceptance criteria are:

- A programmatic way in Python to create a link to a combination of filters
  (analogous to Django's `reverse()`).
- Clickable links for the navbar playtime statistics.

## Scope

**In scope (this work):**

- The core `filter_url()` helper.
- The `OperatorFilter.where()` ergonomic constructor.
- The date-range filtering capability the navbar links require.
- Wiring the navbar "today" / "last 7 days" totals as links.

**Out of scope — filed as a follow-up issue:**

- Stats-page table links.
- `view_game` table links.

These are deferred deliberately to keep this change small. They both build
directly on `filter_url()`, so they are pure consumers of this work. See
"Follow-up issue" below for the drafted text.

## Current state (as investigated)

- Filters are `@dataclass` subclasses of `OperatorFilter` in `games/filters.py`
  (`GameFilter`, `SessionFilter`, `PurchaseFilter`, `PlayEventFilter`,
  `DeviceFilter`, `PlatformFilter`). Each is built from typed criterion objects
  defined in `common/criteria.py`.
- Serialization helpers in `common/criteria.py`: `filter_to_json(f)` →
  `json.dumps(f.to_json())`; `filter_from_json(cls, json_str)` → filter instance.
- List views read `request.GET.get("filter")` (a URL-encoded JSON string),
  deserialize via `parse_*_filter()`, and apply `.to_q()` to the queryset.
- List view URL names: `games:list_games`, `games:list_sessions`,
  `games:list_purchases`, `games:list_playevents`, `games:list_devices`,
  `games:list_platforms`.
- `games/views/filter_presets.py` already hand-rolls the URL-building pattern:
  `f"{reverse(f'games:list_{mode}')}?filter={quote(filter_json)}"`. There is **no
  shared helper** — this work introduces one.
- The navbar playtime totals are produced by the `model_counts` context processor
  (`games/views/general.py`) as formatted strings (`today_played`,
  `last_7_played`) and rendered by `NavbarPlaytime()` (`common/layout.py`). The
  component is also refreshed out-of-band after session changes
  (`games/views/session.py:311`), so any new data must flow through both paths.
- `SessionFilter.timestamp_start` / `timestamp_end` are typed as
  `StringCriterion`, which supports only EQUALS / NOT_EQUALS / INCLUDES /
  EXCLUDES / regex / null — **no `GREATER_THAN` / `LESS_THAN` / `BETWEEN`**. So
  date-range filtering on session timestamps is not currently expressible. These
  fields are **not** exposed in the filter-bar UI
  (`common/components/filters.py` has no reference to them), so their criterion
  type can be changed safely.

## Design

### Component 1 — `filter_url()` (the "`reverse()` for filters")

A single helper in `games/filters.py`, symmetric with the existing
`parse_*_filter()` functions. It infers the target list view from the filter
object's *type*, so a filter can never be paired with a mismatched URL.

```python
_FILTER_LIST_URL = {
    GameFilter: "games:list_games",
    SessionFilter: "games:list_sessions",
    PurchaseFilter: "games:list_purchases",
    PlayEventFilter: "games:list_playevents",
    DeviceFilter: "games:list_devices",
    PlatformFilter: "games:list_platforms",
}

def filter_url(filter_obj: OperatorFilter, **extra_params: str) -> str:
    """Build a URL to the filtered list view for ``filter_obj``.

    The target view is inferred from the filter's type. ``extra_params`` are
    merged into the query string (e.g. ``sort``, ``page``)."""
    url_name = _FILTER_LIST_URL[type(filter_obj)]
    params = {"filter": filter_to_json(filter_obj), **extra_params}
    return f"{reverse(url_name)}?{urlencode(params)}"
```

- Uses `django.utils.http.urlencode` (already imported in `common/utils.py`),
  which URL-encodes the JSON value correctly.
- `**extra_params` leaves room for `sort` / `page` later without being required
  now.
- `filter_presets.py` can adopt this helper later; not required for this change.

### Component 1b — `OperatorFilter.where()` (ergonomic construction)

Building filters via the explicit constructor is verbose, because each criterion
must be wrapped and a `Modifier` imported:

```python
GameFilter(
    purchase_count=IntCriterion(value=1, modifier=Modifier.GREATER_THAN),
    playtime_hours=IntCriterion(modifier=Modifier.IS_NULL),
)
```

Add a `where(**lookups)` classmethod on `OperatorFilter` (so every filter type
inherits it) accepting Django-`QuerySet.filter()`-style `field__modifier=value`
lookups:

```python
GameFilter.where(purchase_count__gt=1, playtime_hours__isnull=True)

# combined with filter_url():
filter_url(GameFilter.where(purchase_count__gt=1, playtime_hours__isnull=True))

# the navbar filters become:
filter_url(SessionFilter.where(timestamp_start=today_iso))
filter_url(SessionFilter.where(timestamp_start__between=(week_ago_iso, today_iso)))
```

How it works (no new architecture — it builds the same dataclass instances):

1. Split each kwarg into `(field_name, suffix)` on the last `__`.
2. Resolve the field's criterion class from its dataclass annotation, reusing the
   logic `from_json` already has (`common/criteria.py:439-473`). Factor that
   resolution into a shared helper (e.g. `_criterion_class_for(cls, field)`) so
   `from_json` and `where()` cannot drift — a small de-duplication bonus.
3. Map the suffix to a `Modifier` (see table); no suffix → the criterion type's
   natural default (`EQUALS` for scalar/string/bool, `INCLUDES` for the set
   criteria `MultiCriterion` / `ChoiceCriterion`).
4. Build the concrete criterion: scalar → `value`; a 2-tuple → `value` / `value2`
   (for `between` / `not_between`); a list → the set criterion's `value`.
5. Return a normal filter instance.

Suffix → `Modifier` map:

| suffix        | Modifier        |
|---------------|-----------------|
| *(none)*      | `EQUALS` (scalar/string/bool) / `INCLUDES` (set) |
| `gt`          | `GREATER_THAN`  |
| `lt`          | `LESS_THAN`     |
| `ne`          | `NOT_EQUALS`    |
| `between`     | `BETWEEN` (value is a 2-tuple) |
| `not_between` | `NOT_BETWEEN` (value is a 2-tuple) |
| `in`          | `INCLUDES` (set) |
| `exclude`     | `EXCLUDES` (set) |
| `all`         | `INCLUDES_ALL` (set) |
| `contains`    | `INCLUDES` (string `icontains`) |
| `regex`       | `MATCHES_REGEX` |
| `isnull`      | `IS_NULL` (value ignored) |
| `notnull`     | `NOT_NULL` (value ignored) |

Design decisions:

- **Purely additive.** The explicit constructor, `to_q()`, and serialization are
  unchanged. `where()` is chosen over a custom `__init__` precisely to keep the
  explicit `GameFilter(name=StringCriterion(...))` form **fully statically typed**
  (a `@dataclass(init=False)` + `**kwargs` constructor would have erased that).
- **Real field names, no aliasing.** Lookups use the actual dataclass field names
  (e.g. `playtime_hours`, not a prettier `playtime`); no alias layer to maintain.
- **Fail loud.** An unknown field name or an unknown/!type-incompatible suffix
  raises a clear `ValueError`/`TypeError` rather than silently producing an empty
  filter. The lookup form is dynamic (like Django's `.filter()`), so this runtime
  validation replaces static checking for that form only.
- **Scope.** `where()` covers the common flat-AND case (the verbose pain point).
  `AND` / `OR` / `NOT` nesting continues to use the explicit constructor, which
  reads fine and is rare.

### Component 2 — date-range filtering on session timestamps

**Decision: switch `SessionFilter.timestamp_start` / `timestamp_end` to
`DateCriterion` and apply them via Django's `__date` lookup.**

Rationale (the alternative was a new "relative date" criterion type):

- `DateCriterion` already exists and supports `GREATER_THAN` / `LESS_THAN` /
  `BETWEEN` — no new criterion semantics to invent.
- The navbar link is server-rendered and regenerated on every request, so
  encoding concrete dates is correct, reproducible, and shareable. A rolling
  "relative date" concept is unnecessary machinery for this scope (YAGNI).
- The serialized JSON shape (`value`, `modifier`, optional `value2`) is
  backward-compatible with any existing `StringCriterion`-shaped data for these
  fields, and the fields are not in the UI, so the type change is low-risk.

Changes in `SessionFilter`:

- Field annotations: `timestamp_start: DateCriterion | None`,
  `timestamp_end: DateCriterion | None`.
- In `to_q()`, target the date lookup so a date compares correctly against the
  datetime column:

  ```python
  if self.timestamp_start is not None:
      q &= self.timestamp_start.to_q("timestamp_start__date")
  if self.timestamp_end is not None:
      q &= self.timestamp_end.to_q("timestamp_end__date")
  ```

  `DateCriterion.to_q("timestamp_start__date")` produces
  `timestamp_start__date__gte=…` etc., which is valid.

The two navbar filters expressed with this:

- **Today:** `SessionFilter(timestamp_start=DateCriterion(value=today_iso,
  modifier=Modifier.EQUALS))` → `timestamp_start__date = today`.
- **Last 7 days:** `SessionFilter(timestamp_start=DateCriterion(
  value=(today−6)_iso, value2=today_iso, modifier=Modifier.BETWEEN))` →
  7 calendar days inclusive (today and the previous six).

### Component 3 — navbar wiring (and a consistency fix)

- `model_counts` (`games/views/general.py`) computes `today_url` and
  `last_7_url` with `filter_url(SessionFilter.where(...))` (see Component 1b) and
  adds them to its returned dict alongside the existing formatted totals.
- `NavbarPlaytime()` (`common/layout.py`) gains `today_url` / `last_7_url`
  parameters and wraps each total string in an `<a href>`. The out-of-band
  refresh call in `games/views/session.py:311` passes the new URLs too.

**Deliberate behavior change — align the "last 7 days" total with its link.**
The displayed "last 7 days" total currently uses a *rolling 168-hour* window
(`timestamp_start__gte = now − timedelta(days=7)`), which would not match a
calendar-day link. To keep the number and the list it links to consistent, the
total is changed to the same **calendar-day boundary** used by the link
(`timestamp_start__date >= today − 6 days`, i.e. 7 calendar days inclusive). The
"today" total already matches (`[midnight, next midnight)` ≡ `__date = today`),
so only the 7-day computation changes.

## Testing

- **`filter_url()`** (unit): returns the correct path for each filter type; the
  `filter` query param is the URL-encoded `filter_to_json(filter_obj)`; extra
  params are merged; the produced URL round-trips through `parse_session_filter`
  to an equivalent filter.
- **`where()`** (unit): each suffix maps to the right `Modifier`; the resolved
  criterion class matches the field annotation across criterion types
  (`Int`/`String`/`Bool`/`Date`/`Multi`/`Choice`); `between` consumes a 2-tuple
  into `value`/`value2`; no-suffix defaults to `EQUALS` for scalars and
  `INCLUDES` for set criteria; `isnull`/`notnull` ignore the value;
  `GameFilter.where(purchase_count__gt=1, playtime_hours__isnull=True)` produces a
  filter equal to the explicit construction and yields the same `to_q()`; an
  unknown field or suffix raises.
- **Date filtering** (unit/db): sessions started today / 3 days ago / 10 days ago
  fall into the correct buckets for the "today" and "last 7 days" filters via
  `SessionFilter.to_q()`.
- **Navbar** (render): `NavbarPlaytime` renders anchors with the expected
  `href`s; a smoke test confirms the linked URLs return 200 and apply the filter.

## Follow-up issue (to be filed)

**Title:** Wire programmatic filter links into stats tables and the game-detail page

**Body:**

> Issue #56 introduced `filter_url()` (a `reverse()`-style helper that builds a
> URL to a filtered list view from a filter object) and used it for the navbar
> playtime links. Two of the call sites named in #56 were deferred and should now
> be wired up using that helper:
>
> - **Stats-page tables** (`games/views/stats_content.py`): make table rows link
>   to the corresponding filtered list (e.g. a game's playtime row → sessions for
>   that game; a finished-games row → that game).
> - **`view_game` tables** (`games/views/game.py`): the sessions / purchases /
>   playevents sections should offer "view all … for this game" links to the
>   filtered list views.
>
> All of these are pure consumers of `filter_url()`; no new filter machinery is
> required. Decide per table which filter each link should encode.

`gh` is not installed in the working environment, so this is provided as
ready-to-paste text; it can be filed manually or via `gh` once available.

## Notes / risks

- Changing the criterion type of `timestamp_start` / `timestamp_end` affects how
  any persisted `FilterPreset` containing those fields deserializes (it will now
  resolve to `DateCriterion`). The JSON shape is compatible and these fields are
  not surfaced in the UI, so the risk is minimal, but it is worth a grep for any
  saved presets referencing them before merge.
