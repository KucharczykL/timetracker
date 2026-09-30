# The game display order

A read that orders by a game uses one order. The order is
`Game.DISPLAY_ORDER_FIELDS`: `sort_name`, then `name`, then `id`. The last
field is unique, so the order is total.

Games often have the same `sort_name`. One game on three platforms is three
rows. PostgreSQL returns tied rows in plan order, and a new plan can change
that order. A sort on `sort_name` alone is therefore not stable.

## The spellings

The code is in `games/models.py`.

| Spelling | Use |
|---|---|
| `GameQuerySet.in_display_order()` | A game queryset. It also works on a related manager, for example `purchase.games` |
| `game_display_order_through(path)` | The three fields through a relation, for a sort or an `order_by` on another model |
| `game_display_key` | A Python sort of games that are already loaded |

A path has no trailing `__`, and `""` is the row itself. `lookup` in
`common/keyset.py` joins a path and a field. The runs' `display_order_through`
and `numbered_sort_key` use the same rule.

Use `game_display_key` where the rows can come from a prefetch. `order_by()`
makes a new query. `first()` also makes one on `Game`, because `Game` has no
default order. Each call costs one query for each purchase. `LinkedPurchase`
and `Purchase.first_game` use the key for this reason.

PostgreSQL compares text in `C.UTF-8` by code point. Python compares `str`
by code point. Python and PostgreSQL also compare a UUID in the same order.
The two sorts therefore agree.

## Where the order applies

These reads use the order, among others:

- The game search, `GET /api/games/search`. The order decides which games a
  `limit` keeps.
- Every game picker: the field queryset and the selected options. A multi-game
  picker shows its selected games in display order. It does not keep the
  order in which a person picked them.
- `PurchaseForm.games`. `ModelMultipleChoiceField.clean` keeps the order of
  its queryset, so the separate purchases are created in display order.
- A purchase: its page list, its tooltip, `first_game`, split and refund.
- The bulk resolutions of games, copies and runs.
- The `name` sort of sessions, runs, records and copies, and the `sort_name`
  sort of games. The fields after the first go into `SortSpec.then`, so a
  descending sort reverses all three.
- The `playthrough` sort of sessions and runs. The game order comes first, so
  runs of two tied games do not mix.

- The stats games card, `games_by_playtime_queryset`. Playtime comes first.
- The games list's `kind` sort, after the kind, and a game's add-ons,
  `tracked_addons`.

`_game_first` in `games/sorting.py` makes a `SortSpec` that starts with the
game order.

## Where the order does not apply

- A sort on one column that is not a game. `apply_sort` ends every order with
  `pk`, so the order is total.
- The Purchase list's `name` sort. It orders purchases by the lowest `name`
  of their games. It does not read `sort_name` or the purchase's own name.
- The figure readers in `session_figures.py` and `play_figures.py`. They
  break a tie on `sort_name`, then on the game key. A change to that rule
  changes figures.

A blank `sort_name` comes before all other values. It does not use `name`
in its place.

## Tests

`tests/game_display_order.py` makes games in an order that is not their
display order. Their creation order, name order and case-blind order are all
different. Two games tie on `sort_name`, and two tie on `sort_name` and
`name`. `tests/test_game_display_order.py` checks each read against these
games.

## Related issues

- #1393: the game search offers shared games that the forms refuse.
- #1394: a purchase's game reads include removed games.
- #1395: the stats page's purchase lists order by one date.
- #1399: a purchase with no games breaks its page and name.
