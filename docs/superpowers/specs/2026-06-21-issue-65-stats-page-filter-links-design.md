# Issue #65 — Stats-page filtered links

**Date:** 2026-06-21
**Issue:** https://github.com/KucharczykL/timetracker/issues/65 (sub-issue of #61, follow-up to #56)
**Prereq:** #67 — date-range filtering on `PlayEventFilter.ended`/`started`
(**merged**, PR #69). `ended`/`started` are now `DateCriterion`; because they are
`DateField`s (not `DateTimeField`s) the implementation uses a bare lookup, not
`__date`. Tier 2 is therefore unblocked — both tiers can ship together.

## Problem

The stats page (`games/views/stats_content.py`, data from `stats_data.py`) shows
aggregate playtime/purchase metrics and several lists. Rows and counts don't link
to the underlying records. #56 introduced `filter_url()` and
`OperatorFilter.where()`; this wires the stats page to those helpers so a row or
count drills into the filtered list it represents.

The page is scoped either to a single year (`compute_stats(year)`, `data["year"]`
is an int) or all-time (`compute_stats(None)`, `data["year"] == "Alltime"`).

## Scope

Two tiers, split by what the filter system can express **today**:

- **Tier 1 — implemented in this issue** (no new filter machinery).
- **Tier 2 — needs "finished in year" filtering** from #67 (now merged, PR #69),
  so it can ship alongside Tier 1.

Also in scope (from design review): shorten long lists to 5 items with a "view
all" link, and remove the "All purchases" list.

## Year scoping

Every link encodes the page's scope:

- **Per-year page**: sessions filtered by `timestamp_start` BETWEEN `{year}-01-01`
  and `{year}-12-31`; purchases by `date_purchased` BETWEEN the same bounds.
- **All-time page**: no date constraint.

A single helper computes the year bounds (or `None`) once and is reused by every
link builder so scoping is consistent.

## Design

### A. Per-row entity links

**Game rows** — superlative rows in `_playtime_table` (longest session, most
sessions, highest average, first/last play) and the "Games by playtime" list.
Keep the existing `GameLink` (→ game detail) and **add** a separate affordance (a
small icon link) to that game's filtered session list:

```python
filter_url(SessionFilter.where(game=[game.id], **session_year_bounds))
```

**Platform rows** — "Platforms by playtime". Link each platform to its sessions:

```python
filter_url(SessionFilter.where(
    game_filter=GameFilter.where(platform=[platform_id]),
    **session_year_bounds,
))
```

Requires a **data change**: `total_playtime_per_platform` rows currently carry
only `platform_name`. Add `platform_id` to the dict in `stats_data.py`.

**Month rows** — "Playtime per month" (per-year only). Link each month to its
sessions:

```python
filter_url(SessionFilter.where(
    timestamp_start__between=(month_start_iso, month_end_iso)
))
```

### B. Aggregate count links

In `_playtime_table` (Tier 1 — added per design review item G):

- **Sessions** count → `SessionFilter.where(**session_year_bounds)`.
- **Games** count → games played in scope:
  `GameFilter.where(session_filter=SessionFilter.where(**session_year_bounds))`.

In `_purchases_table`:

- **Total purchased** (Tier 1) → `PurchaseFilter.where(**purchase_year_bounds)`.
- **Refunded** (Tier 1) →
  `PurchaseFilter.where(is_refunded=True, **purchase_year_bounds)`.
- **Dropped** (Tier 2) → purchases that are abandoned-or-refunded and not
  finished; uses the `not_finished` composition (see Tier 2).
- **Unfinished** (Tier 2) → the `purchased_unfinished` set (see Tier 2).
- **Backlog decrease** (Tier 2) → per-year: purchases bought before the year whose
  game is finished-in-year (see Tier 2). Expressible with prereq #67 — no extra
  machinery.

### C. List capping + "view all"

Cap these lists to **5 rows** and append a **"View all (N) →"** link to the
filtered list (N = the full count):

| List | Cap from | "View all" target |
|------|----------|-------------------|
| Games by playtime | 10 | games played in scope (Tier 1) |
| Finished | all | finished purchases in scope (Tier 2) |
| Finished (YYYY) | all | finished-in-year, released-in-year (Tier 2) |
| Bought & Finished (YYYY) | all | purchased-in-year ∧ finished-in-year (Tier 2) |
| Unfinished purchases | all | `purchased_unfinished` set (Tier 2) |

Capping is done in `stats_content.py` (slice to 5 for display); the full count
for the link label comes from the existing `_count` keys in `StatsData` (or
`len()` where no count key exists). The "Games by playtime" cap also reduces
`top_10_games_by_playtime` usage to 5 (slice at render; the data key may keep its
name or be renamed to `top_games_by_playtime` — implementer's choice, update both
sites).

**Remove** the "All purchases" list (`all_purchased_this_year` rendering). Its
entry point is the "Total purchased" count link. The `StatsData` key may remain
(harmless) or be removed if no other consumer exists.

### D. Tier 2 — finished/dropped/unfinished/backlog (uses #67)

With #67 merged, `PlayEventFilter.ended` is a `DateCriterion` (bare `DateField`
lookup), so "finished in year" is expressible and the chain
`PurchaseFilter.game_filter → GameFilter.playevent_filter → PlayEventFilter`
composes the Tier-2 targets. Reference semantics (from `stats_data.py`):

- **finished** (`Purchase.objects.finished()`) = game `status == FINISHED` **or**
  game has a playevent with `ended` set →
  `GameFilter.where(OR=...)` of `status=[FINISHED]` and
  `playevent_filter=PlayEventFilter.where(ended__notnull=True)`.
- **finished in year** = above **and** `ended` within the year →
  add `playevent_filter=PlayEventFilter.where(ended__between=(jan1, dec31))`.
- **finished (YYYY) released-in-year** = finished-in-year **and**
  `GameFilter year_released == year`.
- **bought & finished (YYYY)** = `is_refunded=False`, `date_purchased` in year,
  game finished-in-year.
- **dropped** = `type in (game, dlc)`, `infinite=False`, **and**
  (`game status=ABANDONED` **or** `is_refunded=True`), **and** not finished-in-year.
- **unfinished** = `is_refunded=False`, `infinite=False`, `type in (game, dlc)`,
  game `status NOT IN (FINISHED, RETIRED, ABANDONED)`, **and** not finished-in-year.
- **backlog decrease** (per-year) = `date_purchased__lt = {year}-01-01`, game
  `status=FINISHED`, **and** finished-in-year →
  `PurchaseFilter.where(date_purchased__lt=jan1, game_filter=GameFilter.where(
  status=[FINISHED], playevent_filter=PlayEventFilter.where(ended__between=(jan1, dec31))))`.
  All-time backlog decrease equals the all-time finished count (matches current
  `stats_data.py` behavior) → link to the all-time finished filter.

These are nested AND/OR/NOT compositions of existing fields plus the #67 date
range — no further machinery.

### E. Components / rendering

Reuse existing builders in `stats_content.py` (`_td`, `_tr`, `GameLink`, `A`).
Add small helpers:

- `_session_link_icon(game_id, year_bounds)` → an `A` wrapping an `Icon`, for the
  per-row game session affordance.
- `_view_all(count, url)` → the "View all (N) →" row/footer link.

Year-bounds helper (e.g. `_year_bounds(year)`) returns the session/purchase
`where()` kwargs (or empty dict for all-time), so every builder scopes
identically.

## Sorting parity (#68)

The stats lists are sorted (Games by playtime → playtime desc; the Finished lists
→ finish date; etc.), but the list views hardcode their `order_by` and ignore any
sort param (`game.py:59`, `session.py:122`, `purchase.py:122`). So a "view all"
link lands on the right *set* but not the same *order*.

This is handled by a separate, **non-prereq** issue (#68: honor a `sort` query
param on the list views). #65 ships without waiting on it:

- Each "view all" link that has a non-default sort on the stats page is built
  with the intended `filter_url(..., sort=...)` param **and** carries a `TODO`
  comment referencing #68, stating the linked list won't preserve the stats
  order until #68 lands. Sites: Games by playtime, Finished, Finished (YYYY),
  Bought & Finished (YYYY), Unfinished purchases.
- The links are correct as *filtered sets* regardless; only ordering differs.

## Exact-match requirement

A count or "view all" link must land on a list whose total equals the displayed
number. The stats queries traverse M2M (`games__…`) joins; the filter layer
resolves cross-entity criteria via `Game.objects.filter(...).values_list("id")`
subqueries, so join/`distinct` semantics can differ. Each linked category gets a
test asserting the linked filter's queryset count equals the corresponding
`StatsData` count, on seeded data. Any category that can't be made to match
exactly is reported (not silently shipped with a wrong number).

## Testing

- **Link builders** (unit): for each linked row/count, `filter_url(...)` produces
  the expected path and the `filter` JSON round-trips through the matching
  `parse_*_filter`. Year-scoped vs all-time variants both covered.
- **Exact-match** (db): seed games/sessions/purchases/playevents spanning the year
  boundary and other years; assert each linked filter's count equals the
  `compute_stats(year)` / `compute_stats(None)` value for that category (both
  tiers, since #67 is merged).
- **Rendering** (db): stats page renders; capped lists show ≤5 rows + a "View all"
  link; the "All purchases" list is gone; smoke-test that the generated link URLs
  return 200.

## Implementation order

1. **Tier 1 + capping + removal** (this issue, independent of #67): per-row game /
   platform / month session links, sessions/games/total-purchased/refunded count
   links, list capping with Tier-1 "view all" links, remove "All purchases",
   `platform_id` data change.
2. **Tier 2** (unblocked — #67 is merged): finished/dropped/unfinished/
   backlog-decrease count and "view all" links.

Both tiers can ship together now that #67 is merged; Tier 1 remains independently
shippable if a smaller first PR is preferred.

## Out of scope

- The `view_game` table links (#66, the other #61 sub-issue).
- Implementing list-view sort support (#68) — #65 only passes the `sort` param and
  leaves a `TODO` at each affected link site (see "Sorting parity").
