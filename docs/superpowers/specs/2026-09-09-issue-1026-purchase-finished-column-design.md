# The purchase Finished column

The Purchase list's Finished cell, `PURCHASE_SORTS["finished"]` and
`GAME_SORTS["finished"]` read the `Playthrough` projection. No finish is read
from `games_playevent`.

## The completion a row reports

`games/reads/playthrough_completions.py` gains three readers beside the four
#1014 wrote. Each takes the path from the outer row to its runs, so one pair of
readers answers for a Purchase and for a Game.

| the reader | answers |
|---|---|
| `latest_completion(library, correlate)` | the runs, ordered so the first is the one the row reports |
| `latest_completion_value(library, correlate)` | that run's `completed` |
| `latest_completion_day(library, correlate)` | that run's `completed_lower` |

```
PURCHASE_RUNS = "player_game__game__purchases"
GAME_RUNS     = "player_game__game"
```

The order is `completed_lower` descending with nulls last, then `-pk`. Both
value readers read the first row of that one ordering, so the cell and the sort
key can never name different runs, and a same-day pair is settled rather than
left to the database.

The runs are `completed_runs(library, None)`, which is #1014's, so the scope is
`library_runs`. A removed run, a run under a removed `PlayerGame`, a run of a
removed Game, another library's run, a run of another kind, and a run that
states no completion each answer nothing. A live bundle that names one removed
Game and one live Game therefore reports the live one, which is what
`PlayEventQuerySet` gave and a plain `Max` over the join would lose.

## What the cell prints

Two annotations, because a null `completed` states two different facts: a
completion nobody dated, and no completion at all.

| the purchase names | the cell |
|---|---|
| no completion | `-` |
| a completion, no day | `Unknown` |
| a completion with a day | the words that value states |

The act comes from `completion_exists(library, None)`, unchanged from #1014;
the words come from `latest_completion_value` through `TemporalText`. A run
that states `2020s` prints `2020s`, the same words Game detail and the run list
print. A dated completion outranks a dayless one, so `Unknown` prints only
where no run the purchase names states a day.

Both are annotations, so neither adds a row, and `_render_purchase_row` loses
the `PlayEvent` query it runs once per row: the list costs no query per row.

## What the sorts order by

Both maps order by the reported run's `completed_lower`, nulls last in both
directions. A row that prints `Unknown` therefore sorts with the rows that
print `-`: the cell states an act the sort has no day for.

The read is a correlated subquery rather than `Max` over the join, and that is
a repair, not a translation. `execute_filter` runs before `apply_sort`, and
`PurchaseFilter` reaches games through `games__id__in`, `games__name` and the
`games` set criterion. Django's filter-then-annotate rule then narrows the join
the aggregate reduces over. Measured on one bundle naming two games finished in
2020 and 2024: unfiltered it reports 2024, and under a filter naming only the
2020 game it reports 2020 for the same purchase. A correlated subquery shares
no join with the outer query and cannot be narrowed this way.

## How a library reaches a sort

`SortSpec` gains a scoped annotation the library builds, and `apply_sort` gains
a required keyword `library`. Seven call sites pass one they already hold: the
six list views and `games/api.py`. A scoped annotation lands only when its key
is sorted, so no list pays for a key it does not use.

The Game list renders no Finished column. `GAME_SORTS["finished"]` is reachable
only through `?sort=` and a saved preset, which is why the key cannot depend on
a view remembering to annotate.

## Five values change

1. A completion with no known day prints `Unknown`, where the column printed
   `-`: `PlayEvent.ended` had to hold a day.
2. A completion coarser than a day prints its own words, where the column could
   print only a day.
3. A game the library does not track reports nothing. #687 made the run the
   only place a completion is stated, so a legacy row with no run behind it is
   #684's to convert, not this column's to read.
4. A removed run reports nothing.
5. A filtered list reports the whole purchase, not the part the filter matched.

## Verification

- The three readers, over: a dated run against a dayless one, a dayless run
  alone, a run with no completion, a removed run, a removed Game inside a live
  bundle, a run naming another library's `PlayerGame`, and a second ordinary
  run at one game.
- Both sorts, both directions, nulls last, over the Purchase map and the Game
  map.
- The narrowing regression above, as a test that fails against `Max` over the
  join.
- The cell, over the three rows of the table above.
- One query count over `list_purchases`, proving no per-row read.
- The full `make check`.

## What this closes

#1014 noted that its view-all links carry `sort=finished`, "which still reads
`games_playevent`". After this they order by the projection, and no finish is
read from that table anywhere. #771 takes it.

## Out of scope

- `PurchaseQueryset.finished()` and the statistics links: #1014, already
  switched
- a visible Finished column on the Game list
- the quantifier a bundle answers: #765 to #767
- taking `games_playevent` away: #771
