# One order for games wherever a read orders by game (#1392)

## Problem

`Game.DISPLAY_ORDER_FIELDS` is `("sort_name", "name", "id")`, a total
order. Many reads that order by a game still order by `sort_name` alone,
by `name` alone, or not at all. Games tie on `sort_name` often: the sample
fixture holds `Resident Evil`, `Tell Me Why` and others three times each,
one per platform. PostgreSQL returns tied rows in plan order, so these
reads can change order after a migration or a new plan. Where a sort
groups by game, rows of tied games interleave.

## Decision

Every read that orders by a game orders by the whole display order. Two
helpers beside `game_display_key` in `games/models.py` spell it:

- `GameQuerySet.in_display_order()` answers
  `self.order_by(*Game.DISPLAY_ORDER_FIELDS)`. A related manager is built
  from `GameQuerySet.as_manager()`, so `purchase.games.in_display_order()`
  works (checked: `Purchase.games.related_manager_cls` has
  `removable_by`; mypy types it too).
- `game_display_order_through(path)` answers the three fields reached
  through a relation, the twin of the runs' `display_order_through`.

## Sites

**Game querysets, `in_display_order()`:**

- `api.py` `search_games`: which games a `limit`-capped answer holds.
- `forms.py` `_game_options`: the order of the pills a picker renders.
  Display order, not pick order: an edit form's values come from an
  unordered relation, so pick order is not known there.
- `forms.py` `PurchaseForm.games`: `ModelMultipleChoiceField.clean`
  returns `self.queryset.filter(pk__in=…)` and keeps its order, and
  `_create_separate_purchases` creates one purchase per game in it.
- `forms.py` single game pickers (1415, 2006 via `__init__`, 2340) and
  `entry_forms.py:214`. Nothing reads their order today; one rule holds
  for every game picker. The class-level querysets at 1476, 1987, 2006
  and 2356 are defaults every `__init__` replaces; they change with the
  rest.
- `views/purchase.py`: the Purchase page's list, `_split` (creates one
  purchase per game) and `_refund` (dispatches per game, and its failure
  sentence counts games done).
- `Purchase.first_game`: `self.games.first()` orders by pk. It names an
  unnamed bundle (title, `__str__`, confirmations, stats rows). It becomes
  `min(self.games.all(), key=game_display_key, default=None)`: the game
  the tooltip and the page list lead with, read from the prefetch cache
  the stats page already pays for.
- `bulk_removal.game_resolution`: order before `with_departures`, whose
  `QuerySet[Game]` return type drops the queryset's methods for mypy;
  `annotate` keeps the order. `bulk_game_edit.game_edit_resolution`.

**Through a relation, `game_display_order_through`:**

- `bulk_entries.entry_resolution`: the game's order, then the entry key.
- `bulk_runs`: the Python key is `game_display_key` of the run's game; a
  stable sort keeps numbering order inside a game.
- `sorting.py` `name` keys over sessions, runs, records and entries: the
  head stays `…__sort_name`, `then` adds `…__name`, `…__id`. `ENTRY`'s
  default sort is `name,-acquired`, so this is not only a stated sort.
- `sorting.py` `playthrough` keys over sessions and runs: the game's three
  fields lead, then the run key. Their rule is "the game first"; tied
  games no longer interleave.
- `GAME_SORTS["sort_name"]`: `then=("name",)`.

`games_by_playtime_queryset` already ends in the fields after its
playtime head. `LinkedPurchase` keeps its Python sort: a queryset method
skips the prefetch cache.

## Not changed

- `GAME_SORTS["name"]` states the name column; `apply_sort` ends in `pk`.
- `PURCHASE_SORTS["name"]` sorts purchases by `Min("games__name")`, the
  name a row prints; ties end in `pk`. It orders purchases, not games.
- The figure readers (`session_figures.py`, `play_figures.py` and
  `PlayKey`) break ties on `sort_name`, then the game key. The order is
  total, CLAUDE.md states it, and the parity gate pins the figures; a
  new tie rule moves figures, which is a separate change.
- A blank `sort_name` leads rather than falling back to `name`. No sample
  row holds one.

The #715 organizer spec says both `playthrough` keys lead with the
game's `sort_name`; it is updated to name the game's display order.

## Tests

In tests, `sort_name` is blank unless set, so each test sets it to make a
tie. Each site gets one behaviour test with games created out of display
order: the API answer and `limit=1`; `_game_options`; `PurchaseForm`
cleaned games and the separate-prices POST; `first_game`; split order;
both game resolutions; entry and run resolutions; each changed `SortSpec`
through `apply_sort`.

## Follow-up issues

- #1393: the game search offers shared catalog games (`visible_to`), but
  `_game_options` and three forms resolve through `for_library`.
- #1394: a Purchase's game reads (`first_game`, `LinkedPurchase`, the Purchase
  page) include removed games.
- #1395: the stats page's purchase lists (`stats_data.py` 332, 342, 429, 440)
  order by one date; tied rows come back in plan order.
