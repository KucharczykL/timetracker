# The purchase Finished column

The Purchase list's Finished cell reads the `Playthrough` projection. Both
`finished` sort keys read it too. No finish comes from `games_playevent`.

## The reported run

`games/reads/playthrough_completions.py` holds three readers for this. Each
takes a `RunPath`, the lookup path from the outer row to its runs.
`PURCHASE_RUNS` is `player_game__game__purchases`. `GAME_RUNS` is
`player_game__game`.

| Reader | Answer |
|---|---|
| `ranked_completions(library, path)` | the completed runs, the reported one first |
| `reported_completion(library, path)` | that run's `completed` |
| `reported_completion_day(library, path)` | that run's `completed_lower` |

The order has three keys: `completed_lower` descending nulls last, then
`completed_upper` ascending nulls last, then `-pk`. The first key reports the
most recent finish. The second gives a tie to the narrower interval, so the
more precise of two values that start on one day is reported. The third makes
the answer stable. Both value readers read the first row of that one order, so
the cell and the sort key always name one run.

The runs are `completed_runs(library, None)`, scoped to `library_runs`. A
removed run answers nothing. So does a run under a removed `PlayerGame`, a run
of a removed Game, another library's run, and a run that states no completion.

`completion_exists` stays purchase-only. The Game list renders no Finished
column.

## The cell

A null `completed` states two facts, so the cell reads two annotations.

| The purchase names | The cell |
|---|---|
| no completion | `-` |
| a completion, no day | `Unknown` |
| a completion with a value | the words that value states |

`TemporalText` prints the words. A value of `202X` prints `2020s`. An
open-start range prints `until 2020-05-01`.

`_purchases_with_completions` builds the annotated queryset. The list and the
row that a refund swaps in both read through it, so the two cells agree. Both
facts are annotations, so the list costs no query per row.

## The sorts

Both maps name the `completed_day` alias and carry no annotate dict. Each list
view annotates it, as `list_games` already does for `filtered_playtime`. Nulls
sort last in both directions. A row that prints `Unknown` sorts with the rows
that print `-`.

The read is a correlated subquery. An aggregate over the join is the other way
to write it, and a `game_filter` narrows one annotated after it, so a bundle
would report its matched game rather than itself. A subquery shares no join
with the outer query, so no filter can narrow it, wherever it is annotated.

An aggregate also groups the fan-out away. `PurchaseFilter` compiles
`game_filter` to a join, so `list_purchases` calls `.distinct()` where a filter
ran.

## Effects

A completion with no known day prints `Unknown`. A coarse completion prints its
own words. A filtered list reports the whole purchase. A bundle reports the run
the order ranks first, which a shared lower bound gives to the narrower value.
Three statistics links carry `sort=finished`, so their rows reorder: the cell
and the sort now report one number. The Game list's `finished` sort orders by
each game's own runs.

`PurchaseQueryset.finished()` also counts a done status, so a game marked
finished with no run stated is counted and prints `-`. #684 gives such a game a
run.

## Out of scope

- a Finished column on the Game list
- a `game_filter` compiled to a subquery
- the quantifier a bundle answers: #765 to #767
- taking `games_playevent` away: #771
