# Plan: one order for games (#1392)

Spec: `docs/superpowers/specs/2026-09-30-issue-1392-game-display-order-design.md`.
TDD per task: write the test, see it fail, change the code, see it pass.

## Shared test fixture

`tests/game_display_order.py`: `tied_games(library, platforms)` creates
games out of display order that tie on `sort_name` and differ by `name`,
plus a full tie (same `sort_name` and `name`, two platforms). Returns them
in expected display order. Every task below reads it. Gotcha: `sort_name`
is blank unless set; set it on every row.

## Task 1: the two helpers

- `games/models.py`: `GameQuerySet.in_display_order()`;
  `game_display_order_through(path: str) -> tuple[FieldName, ...]` beside
  `game_display_key` (path ends without `__`; the helper joins).
- Test `tests/test_game_display_order.py`: the method orders a related
  manager (`purchase.games.in_display_order()`); the helper spells the
  three paths.

## Task 2: game querysets

- `games/api.py` `search_games` → `.in_display_order()`.
  Test in `tests/test_search_select.py`: order and `limit=1`.
- `games/forms.py` `_game_options` → ordered. Test: resolver order;
  existing one-query test must stay one query.
- `games/forms.py` seven picker querysets and `games/entry_forms.py:214`.
  Test in `tests/test_purchase_separate_orders.py`: separate-prices POST
  creates purchases in display order (read by `created_at`, `id`).
- `games/views/purchase.py`: page list → `in_display_order()` (drop the
  explicit `order_by`); `_split`, `_refund` → `in_display_order()`.
  Test split order (new purchases' `created_at`/`id` order follows games).
- `Purchase.first_game` → `min(self.games.all(), key=game_display_key,
  default=None)`. Tests: names display-order first; zero queries when
  prefetched; `None` for no games (`tests/test_purchase_without_games.py`
  stays green).
- `games/bulk_removal.py`: `in_display_order()` before `with_departures`.
  `games/bulk_game_edit.py`: same. Tests in
  `tests/test_bulk_game_removal.py` / `tests/test_bulk_game_edit.py`.

## Task 3: through a relation

- `games/bulk_entries.py`: `order_by(*game_display_order_through(
  "player_game__game"), "id")`. Test in `tests/test_bulk_entry_acts.py`.
- `games/bulk_runs.py`: key `game_display_key(run.player_game.game)`.
  Test: two tied games' runs group by game, numbering order kept.
- `games/sorting.py`:
  - `name` keys (sessions, runs, records, entries): head `…__sort_name`,
    `then` the other two fields. Build with a small local helper so each
    spec reads `_by_game(path)`.
  - `playthrough` keys: head `…__sort_name`, `then` game name, game id,
    `run_numbered`, run display order (sessions add `sort_instant`).
  - `GAME_SORTS["sort_name"]`: `then=("name",)`.
  - Tests in `tests/test_sorting.py` through `apply_sort`: tied games
    group; descending reverses the game order. Keep
    `:366-373` (`GAME_SORTS["name"]`) green.

## Task 4: docs

- #715 spec, "The two keys": lead with the game's display order.
- CLAUDE.md: #715 paragraph ("game, then …") — check wording holds.

## Gotchas

- `with_departures` returns `QuerySet[Game]`: order before calling it.
- `first()` on an ordered queryset still queries; `first_game` must read
  `.all()` to hit the prefetch cache.
- The Purchase page list must keep the #1391 test green.
- `make vale` over changed files: no refused words.
