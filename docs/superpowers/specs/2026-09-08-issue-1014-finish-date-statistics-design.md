# Finish-date statistics

The statistics page computes every finish from the `Playthrough` projection. No
statistic reads `games_playevent`.

## The read seam

`games/reads/playthrough_completions.py` holds every completion read the
statistics make, per scope: a year, or `None` for all-time.

| the reader | answers |
|---|---|
| `completed_in_scope(year)` | the `PlaythroughFilter` a scope states |
| `completed_runs(library, year)` | the runs that filter matches |
| `completion_exists(library, year)` | an `Exists` for a Purchase queryset |
| `completion_day(library, year)` | the day a Purchase reports |

`games/views/stats_links.py` reads `completed_in_scope`. A statistic and the
link beside it therefore compile one predicate over `library_runs(library)`.
Restating the predicate is refused: the handler states three parts, and two
answer differently for an open bound.

Both Purchase readers correlate on `player_game__game__purchases`, so a bundle
answers for every game it names.

## A completion in scope

All-time reads the act: `completion_recorded_at` is not null. A year reads the
interval the endpoint states, through the two generated bound columns. An absent
bound is unbounded.

- A whole-year completion answers for that year, and a range across New Year
  for both. Per-year counts can sum above the all-time count.
- A completion with no known day answers all-time only.
- A completion with an open bound answers every year on that side.

## The day a Purchase reports

The day is `completed_lower` of one run in scope: the earliest for a year, the
latest for all-time. Each table thus leads with the finish its order names. A
Purchase finished by a done status reports no day, and every table orders
dateless rows last.

## What the statistics read

| the statistic | the read |
|---|---|
| `not_finished_q` | no done status and no completion in scope |
| `PurchaseQueryset.finished()` | a done status or a completion, all-time |
| `all_finished_this_year` | Purchases with a completion in scope |
| `this_year_finished_this_year` | those whose game released that year |
| `purchased_this_year_finished_this_year` | those bought in scope, not refunded |
| `backlog_decrease_count` | bought before the year, done, completed in it |

Each is one row per Purchase: membership by `Exists`, the day by `Subquery`.
`finished()` keeps its `distinct()` for the M2M join its done-status half
opens.

## Three values change

1. A completion counts per Purchase, not per run. A game completed twice, and
   a bundle with two completions, count once.
2. A removed run counts for nothing.
3. A removed Game supplies no completion.

## What is not made to agree

A statistic and its link share the run-level predicate, but ask a Purchase
different questions: a bundle answers a different quantifier, and an untracked
game answers the negation differently. The filter audit owns both. The view-all
link carries `sort=finished`, which still reads `games_playevent`.

## Out of scope

- the Purchase list's Finished cell and the `finished` sorts: #1026
- the API bodies and the endpoint screen: #1015
- the quantifier a bundle answers, and an untracked game: #765 to #767
- the replay-parity gate over both families: #688
- taking `games_playevent` away: #771
