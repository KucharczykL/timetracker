# Finish-date statistics

The statistics page computes every finish from the `Playthrough` projection.
`games/views/stats_data.py` reads no `games__playevents__ended` path, and
`PurchaseQueryset.finished()` reads none either. `games/views/stats_links.py`
already reads the projection, so this issue changes no builder there; it makes
the two halves read one source.

Other screens still read `games_playevent` for a finish day: the Purchase list's
Finished cell and the `finished` sort on Game and Purchase (#1026), and the API
bodies (#1015). #771 takes the table.

## One read seam

`games/reads/playthrough_finishes.py` holds every finish read the statistics
make. It builds on `library_runs(library)`, the queryset
`filter_query_context_for_library` hands `PlaythroughFilter`. One source for the
stat and for the link it carries is what makes their counts agree by
construction.

| the reader | answers |
|---|---|
| `completed_runs(library, year)` | the runs a finish in scope names |
| `finished_in_scope(library, year)` | an `Exists` for a Purchase queryset |
| `finish_day(library, year)` | the day a Purchase reports, as a `Subquery` |

`completed_runs` states the library beside the parent, a null `removed_at` on
the run and on both parents, and the ordinary kind — the scope `library_runs`
already states. The two Purchase readers correlate on
`player_game__game__purchases`, thus a bundle answers for every game it names.

## A finish in scope

All-time reads the act: `completion_recorded_at` is stated. A year reads the
interval the endpoint states, and the two generated bound columns hold it.

| scope | the read |
|---|---|
| all-time | `completion_recorded_at` is not null |
| a year | `completed_lower <= Dec 31` and `completed_upper >= Jan 1` |

Both are what `_completed_in_scope` in `stats_links.py` compiles today, the
first through `is_completed`, the second through the interval handler
`completed__between` names.

The year read overlaps. A completion stated as a whole year answers for that
year; one stated as a range across New Year answers for both years it touches,
so the per-year counts may sum above the all-time count. A completion whose day
nobody knows carries null bounds, thus it answers all-time and answers no year.
No converted row states such a value: #684 converts a `DateField`, which states
a day.

`PlayEvent.days_to_finish` has its replacement already:
`days_to_finish(run)` in `games/reads/playthrough_endpoints.py` counts from
`started_lower` to `completed_upper`, both ends included, and answers nothing
where a bound is absent or the completion precedes the start. No statistic reads
it. This issue names the rule and adds no second one.

## The day a Purchase reports

The finished tables print one day per row and order by it. That day is
`Max(completed_lower)` over the runs in scope: the most recent finish, read at
the earliest day its completion can name. A month-precision completion in March
2024 prints the first of March. The tables show no precision, and #1015 owns the
screen that does.

## What the statistics read

| the statistic | the read |
|---|---|
| `not_finished_q` | no done status and no finish in scope |
| `PurchaseQueryset.finished()` | a done status or a finish, all-time |
| `all_finished_this_year` | Purchases with a finish in scope |
| `this_year_finished_this_year` | those whose game released that year |
| `purchased_this_year_finished_this_year` | those bought in scope, not refunded |
| `backlog_decrease_count` | bought before the year, done, finished in it |

`backlog_decrease_count` keeps its two `filter()` calls, thus a bundle answers
as it answers today; only the finish predicate moves. Every other read above
becomes one row per Purchase: membership by `Exists`, the day by `Subquery`.

## Two values change

Both are narrow, both are stated, and the compare run reports each by name.

1. A Purchase whose game holds two completions in one scope counted twice and
   now counts once. The stat and the link it carries disagreed on such data,
   because the link counts Purchases. The parity test asserted a number that was
   right by luck.
2. A removed run no longer counts. The legacy join read `games_playevent` with
   no `removed_at` condition, thus a removed row still answered a statistic.

The `game_name` annotation goes away with the join. `_purchase_name` falls back
to the first game's name, thus a Purchase of type game prints what it prints
today. A DLC row prints the Purchase's own name beside its unchanged suffix.

## Verification

`tests/test_stats_links.py` keeps the projection half of its fixture and drops
the `PlayEvent` half, the bridge #1013 left. The parity tests then read one
source on both sides.

New tests state: the year edges of the overlap read, a completion with no known
day (all-time yes, that year no), a removed run, a run of a removed parent, and
a Purchase with two completions in one year.

A throwaway script over `make restore-dump` computes every statistic in the
table above the legacy way and the projection way, per year, and diffs them.
Its output goes on the pull request; the script is not committed. A difference
outside the two classes above is a defect, not evidence.

## Out of scope

- the Purchase list's Finished cell and the `finished` sorts: #1026
- the API bodies and the endpoint screen: #1015
- the replay-parity gate over both families: #688
- taking `games_playevent` away: #771
