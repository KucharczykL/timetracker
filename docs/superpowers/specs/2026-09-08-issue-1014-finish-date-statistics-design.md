# Finish-date statistics

The statistics page computes every finish from the `Playthrough` projection.
`games/views/stats_data.py` reads no `games__playevents__ended` path, and
`PurchaseQueryset.finished()` reads none either. `games/views/stats_links.py`
already reads the projection, so this issue changes no builder there; it makes
the two halves read one object.

Other screens still read `games_playevent` for a finish day: the Purchase list's
Finished cell and the `finished` sort on Game and Purchase (#1026), and the API
bodies (#1015). #771 takes the table.

## One read seam

`games/reads/playthrough_completions.py` holds every completion read the
statistics make. It states the projection's own verb: the act is a completion,
and `finished` stays the Purchase-side word its incumbents already spell.

| the reader | answers |
|---|---|
| `completed_in_scope(year)` | the `PlaythroughFilter` a scope states |
| `completed_runs(library, year)` | the runs that filter matches |
| `completion_exists(library, year)` | an `Exists` for a Purchase queryset |
| `completion_day(library, year)` | the day a Purchase reports, a `Subquery` |

`completed_in_scope` moves here from `stats_links.py`, which imports it back.
`completed_runs` executes that same filter object against
`filter_query_context_for_library(library)`, whose `Playthrough` entry is
`library_runs(library)`. The stat and the link it carries therefore compile one
predicate over one queryset. A restated predicate would not: the interval
handler emits three parts, and the two obvious ones are not all of it.

`library_runs` states the library beside the parent, a null `removed_at` on the
run and on both parents, and the ordinary kind. Nothing writes the
`imported_history` kind yet, so excluding it moves no row today. The two
Purchase readers correlate on `player_game__game__purchases`, thus a bundle
answers for every game it names.

## A completion in scope

All-time reads the act. A year reads the interval the endpoint states, through
the two generated bound columns.

| scope | the filter | the predicate |
|---|---|---|
| all-time | `is_completed=True` | `completion_recorded_at` is not null |
| a year | `completed__between` that year's ends | the three parts below |

The year predicate is `completed` is not null, **and** `completed_lower` is at
most Dec 31 or absent, **and** `completed_upper` is at least Jan 1 or absent. An
absent bound is unbounded, which is the handler's rule for every endpoint
comparison, not something the statistics choose.

Three consequences the tests state:

- a completion stated as a whole year answers for that year; one stated as a
  range across New Year answers for both years it touches, so per-year counts
  may sum above the all-time count;
- a completion whose day nobody knows carries a null `completed`, thus it
  answers all-time and answers no year;
- a completion stated as an open range, such as up to a day in May 2024,
  carries a null bound on its open side, thus it answers every year on that
  side. No converted row states one — #684 converts a `DateField` — but
  `CompletePlaythrough` and `CorrectPlaythroughCompletion` both accept a whole
  `TemporalValue`, so the API can state one today.

`PlayEvent.days_to_finish` has its replacement already: `days_to_finish(run)` in
`games/reads/playthrough_endpoints.py` counts from `started_lower` to
`completed_upper`, both ends included, and answers nothing where a bound is
absent or the completion precedes the start. No statistic reads it. This issue
names the rule and adds no second one.

## The day a Purchase reports

The tables print one day per row and order by it. That day is `completed_lower`
of one run in scope: the earliest run for a year, the latest for all-time. Each
table thus reports the finish its own order leads with — a year ascends from the
first finish inside it, and all-time descends from the most recent one. A
month-precision completion in March 2024 prints the first of March; the tables
show no precision, and #1015 owns the screen that does.

A Purchase finished by a done status alone reports no day, as it does today. A
completion with no known day, and one with an open lower bound, report none
either. Every table orders those rows last. Today they lead, which fills a
ten-row table with rows that print nothing.

## What the statistics read

| the statistic | the read |
|---|---|
| `not_finished_q` | no done status and no completion in scope |
| `PurchaseQueryset.finished()` | a done status or a completion, all-time |
| `all_finished_this_year` | Purchases with a completion in scope |
| `this_year_finished_this_year` | those whose game released that year |
| `purchased_this_year_finished_this_year` | those bought in scope, not refunded |
| `backlog_decrease_count` | bought before the year, done, completed in it |

Each becomes one row per Purchase: membership by `Exists`, the day by
`Subquery`. `finished()` keeps its `distinct()`, because its done-status half
still opens the M2M join and still fans a bundle out.

## The name a row prints

The `game_name` annotation goes away with the join, because a value read off a
joined row is what fans the row out. `_purchase_name` reads it through
`getattr`, so it falls back on its own. Its fallback for a Purchase that is not
of type game is `purchase.name`, which is blank by default and would render an
empty link; it becomes `standardized_name`, the Purchase's own name or its first
game's. A bundle prints its first game, which is what every other Purchase table
prints.

## Three values change

Each is narrow, each is stated, and the compare run reports it by name. A
difference outside these three is a defect.

1. **A completion counted per run now counts per Purchase.** Today each read
   joins `games_playevent`, so a Purchase appears once per matching row: twice
   for a game completed twice in one year, and twice for a two-game bundle with
   a completion each. The count drops to one, and the tables print one row,
   named as `_purchase_name` names every other row and dated by the rule above.
   `all_finished_this_year_count` and `backlog_decrease_count` both move on such
   data. The stat and its own link disagreed there, because the link counts
   Purchases; the parity test asserted a number that was right by luck.
2. **A removed run no longer counts.** The legacy join read `games_playevent`
   with no `removed_at` condition.
3. **A removed Game no longer supplies a completion.** `library_runs` reads the
   Game's mark; the legacy join did not. `finished()` is asymmetric on this
   today — its done-status half reads `tracked_by`, which calls `alive()`, and
   its playevent half reads a removed Game's rows. Removal stamps no
   `PlayerGame`, so the projection row stays beside the removed catalog row.

## What this issue does not make agree

The stat and its link share the run-level predicate after this change. They
still ask different questions of a Purchase, and both divergences predate this
issue:

- **a bundle.** `_not_finished_game` nests the negation inside a `GameFilter`,
  which `relation_to_q` compiles as "any game of this Purchase is unfinished".
  `not_finished_q` asks "no game of this Purchase is done and none is
  completed". A bundle of one finished game and one unfinished game answers
  differently. The header comment in `stats_links.py` already concedes it;
- **an untracked game.** The link's Game subquery resolves from
  `Game.objects.tracked_by(library)`, which holds no untracked game.
  `~Q(games__in=done)` holds it. The crash window `remove_game_for_request`
  documents can leave one.

Parity therefore holds for single-game Purchases of tracked games, the shape the
fixtures state and the shape the product models. The filter audit owns the rest.

Beside them, one disagreement this issue opens and #1026 closes: the view-all
link under each finished section carries `sort=finished`, and that sort key
still reads `Max("games__playevents__ended")`. Until #1026 the section and the
list it opens order by different columns.

## Verification

`tests/test_stats_links.py` keeps the projection half of its fixture and drops
the `PlayEvent` half, the bridge #1013 left. Eight parity tests fail on that
fixture today and pass on the cutover. `tests/test_stats_content_links.py`
carries the same bridge on one line; it goes too, and the section it seeds keeps
its completion.

New tests state: the first and last day of a year; a completion with no known
day; one with an open bound; a removed run; a run whose Game is removed; a
Purchase with two completions in one year; a two-game bundle with one completion
each; and a table whose dateless rows sort last.

A throwaway script over `make restore-dump` computes every statistic in the
table above the legacy way and the projection way, per year, and diffs them. Its
output goes on the pull request; the script is not committed.

## Out of scope

- the Purchase list's Finished cell and the `finished` sorts: #1026
- the API bodies and the endpoint screen: #1015
- the quantifier a bundle answers, and an untracked game: #765 to #767
- the replay-parity gate over both families: #688
- taking `games_playevent` away: #771
