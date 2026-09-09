# The purchase Finished column

The Purchase list's Finished cell, `PURCHASE_SORTS["finished"]` and
`GAME_SORTS["finished"]` read the `Playthrough` projection. No finish is read
from `games_playevent`.

## The completion a row reports

`games/reads/playthrough_completions.py` gains three readers beside the four
#1014 wrote, and its docstring stops saying "for the statistics": the module
now answers a list as well. Each reader takes the path from the outer row to
its runs, so one set answers for a Purchase and for a Game.

```
type RunPath = str  # a lookup path from the outer row to its runs

PURCHASE_RUNS: RunPath = "player_game__game__purchases"
GAME_RUNS: RunPath = "player_game__game"
```

| the reader | answers |
|---|---|
| `ranked_completions(library, path)` | the runs, ordered so the first is the one the row reports |
| `reported_completion(library, path)` | that run's `completed` |
| `reported_completion_day(library, path)` | that run's `completed_lower` |

The order has three keys:

1. `completed_lower` descending, nulls last
2. `completed_upper` ascending, nulls last
3. `-pk`

The first key reports the most recent finish. The second settles a tie between
two values that share a lower bound: `2020-05-01` and `2020-05` both rank at
1 May 2020, and the narrower interval wins, so the row prints the more precise
of the two. The third makes the answer deterministic where the first two cannot
separate the runs. Both value readers read the first row of that one ordering,
so the cell and the sort key can never name different runs.

The runs are `completed_runs(library, None)`, which is #1014's, so the scope is
`library_runs`. A removed run, a run under a removed `PlayerGame`, a run of a
removed Game, another library's run, a run of another kind, and a run that
states no completion each answer nothing. A live bundle that names one removed
Game and one live Game therefore reports the live one, which is what
`PlayEventQuerySet` gave and a plain `Max` over the join would lose.

`completion_exists` stays purchase-only, because nothing needs the act on the
Game side: the Game list renders no Finished column. A Game-side existence
reader arrives with the screen that wants one.

## What the cell prints

Two annotations, because a null `completed` states two different facts: a
completion nobody dated, and no completion at all.

| the purchase names | the cell |
|---|---|
| no completion | `-` |
| a completion, no day | `Unknown` |
| a completion with a day | the words that value states |
| a completion whose value states no lower bound | the words that value states |

The act comes from `completion_exists(library, None)`, unchanged from #1014;
the words come from `reported_completion` through `TemporalText`. A run whose
canonical value is `202X` prints `2020s`, the same words Game detail and the
run list print. The canonical spelling and the printed words differ, and it is
the printed words a test asserts.

The fourth row is an open-start range, `../2020-05-01`. It is storable and the
API accepts it, its `completed_lower` is null and its `completed_upper` is not,
and it prints `until 2020-05-01`. It is a completion, so it is not `-`, and it
states words, so it is not `Unknown`.

Both are annotations, so neither adds a row, and `_render_purchase_row` loses
the `PlayEvent` query it runs once per row: the list costs no query per row.

`_render_purchase_row` has two callers. The second renders one row for the
swap after a refund, from a purchase read on its own. One named function builds
the annotated Purchase queryset, and both callers read through it, so the
refunded row's cell answers what the list's does.

## What the sorts order by

Both maps order by the reported run's `completed_lower`, nulls last in both
directions. Two rows sort with the rows that print `-`: a row that prints
`Unknown`, and a row whose value states no lower bound. In each the cell states
a completion the sort has no day for. A value coarser than a day sorts at its
lower bound, so `202X` sorts at 1 January 2020 and prints `2020s`.

The read is a correlated subquery rather than `Max` over the join, and that is
a repair, not a translation. `execute_filter` runs before `apply_sort`, and
`PurchaseFilter` reaches games through `games__id__in`, `games__name` and the
`games` set criterion. Django's filter-then-annotate rule then narrows the join
the aggregate reduces over. Measured on one bundle naming two games finished in
2020 and 2024: unfiltered it reports 2024, and under a filter naming only the
2020 game it reports 2020 for the same purchase. A correlated subquery shares
no join with the outer query and cannot be narrowed this way.

## Where the annotation comes from

The view annotates, and neither `finished` key carries an annotate dict. This
is the pattern `filtered_playtime` already follows: `list_games` annotates a
correlated `Subquery`, and `GAME_SORTS["filtered_playtime"]` names the alias
and nothing else. `apply_sort` keeps its signature, `SortSpec.annotate` keeps
its `Expression` value type, and no test that calls `apply_sort` changes.

Both keys are reachable from exactly two views, `list_games` and
`list_purchases`, and both hold the library. Nothing else reads either map to
build a query: `games/api.py` sorts sessions, and `SORT_MAPS` is read to
validate a key, not to run one. So a key that names an alias can never reach a
queryset that lacks it.

The Purchase list annotates both readers, because it prints the cell. The Game
list annotates the day alone, and does it unconditionally, as it already does
for `filtered_playtime` — one correlated subquery on a list that pays for one
already.

## The fan-out this unmasks

A `game_filter` on the Purchase list duplicates rows today. Measured against
`main`: one bundle naming two games, one `game_filter`, the default sort, and
the list answers the same purchase twice. `PurchaseFilter` compiles
`game_filter` to `games__id__in`, which is a join, and neither `execute_filter`
nor `list_purchases` calls `.distinct()`.

`Max("games__playevents__ended")` groups by the purchase's primary key, so
`?sort=finished` collapses the duplicates by accident. The two statistics links
carry `sort=finished`, so those two pages are the ones the accident protects.
Taking the aggregate away takes the protection with it.

So `list_purchases` calls `.distinct()` where a filter ran. It is a repair of a
bug that predates this issue and is reachable on `main` by sorting a
game-filtered purchase list any other way. It lands here because this issue is
what removes the thing hiding it, and the two cannot be split without shipping
a visible regression on the pages #1014 links from. The narrow fix is the one
taken; compiling `game_filter` to a subquery, as the `games` criterion already
does, would end fan-out for every consumer and is a separate issue.

The same reasoning does not reach `GAME_SORTS["finished"]`. `Sum` over
`sessions__` already carries the Game list's group, and `total_playtime` keeps
its aggregate.

## What the statistics links reorder

"Purchases bought and finished in 2024" and "Purchases finished and released in
2024" both link with a year filter and `sort=finished`. Today the sort reads
the in-year finish, because the year filter narrows the join the aggregate
reduces over, while the cell beside it reads the purchase's all-time latest
finish. Cell and sort disagree, and nothing says so.

After this they agree, and both report the all-time latest. The rows on those
two pages therefore reorder. That is the intended reading: a column and the
sort on that column report one number. A person who wants the in-year finish
wants a different column, not a sort that silently means something else from
the cell above it.

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

## What stays as it is

- A purchase naming no game prints `-`. It names no run.
- A refunded purchase keeps printing its completion. `refund_purchase` marks
  the games abandoned and leaves the runs, and a game played before a refund
  was still played.
- `PurchaseQueryset.finished()` counts a purchase whose game holds a done
  status **or** whose runs state a completion. The column reads runs alone. So
  a purchase whose game is marked finished with no completion stated is
  counted by the statistics and prints `-` in the column those statistics link
  into. Both are right: the status is a person's word for the game, the run is
  a record of one play through it. #684 is what gives such a game a run.

## Verification

- The three readers, over: a dated run against a dayless one, a dayless run
  alone, an open-start range, two runs sharing a lower bound at different
  precisions, a run with no completion, a removed run, a removed Game inside a
  live bundle, a run naming another library's `PlayerGame`, and a second
  ordinary run at one game.
- The cell, over the four rows of its table, and over a purchase naming no
  game.
- The refunded row's cell, through the swap `refund_purchase` answers with.
- Both sorts, both directions, nulls last, over the Purchase map and the Game
  map. `test_nullable_aggregate_sort_keeps_null_last_in_both_directions` seeds
  `PlayEvent` rows to do this today; it is rewritten onto runs, not
  re-signatured.
- `?sort=finished` on the Game list, end to end, since no column renders it.
- A saved preset carrying `sort=finished`, loaded and run.
- The narrowing regression above, as a test that fails against `Max` over the
  join.
- The fan-out, as a test that counts the rows a `game_filter` answers under the
  default sort and under `?sort=finished`. It fails against `main` under the
  default sort, which is the pre-existing bug, and against this change without
  `.distinct()` under both.
- Both statistics links, asserting the order each answers.
- Query counts over `list_purchases` and `list_games`, each stating the number
  it expects, so neither can be written to pass against whatever the
  implementation does.
- The full `make check`.

## What this closes

#1014 noted that its view-all links carry `sort=finished`, "which still reads
`games_playevent`". After this they order by the projection, and no finish is
read from that table anywhere. #771 takes it.

## Out of scope

- `PurchaseQueryset.finished()` and the statistics links: #1014, already
  switched
- a visible Finished column on the Game list
- compiling `game_filter` to a subquery, so no consumer needs `.distinct()`
- the quantifier a bundle answers: #765 to #767
- taking `games_playevent` away: #771
