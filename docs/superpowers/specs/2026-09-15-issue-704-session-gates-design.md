# Pass the Session replay, statistics and budget gates

Issue: [#704](https://github.com/KucharczykL/timetracker/issues/704). Part of the
[session delivery wave](2026-09-12-session-wave-design.md). Member 4 of stack
#1072, after #1077; never merged alone.

## Rule

Three gates, each a thing that runs and fails. A gate that is a sentence in a
document is a claim; a gate that is a command is a fact about the tree it ran
on.

## What stands before this issue

- `make verify-replay-parity` replays every registered projection, the
  session one included, and fails on a differing row. The in-suite gate
  `tests/test_playergame_playthrough_gate.py` replays one command stream and
  compares rows, but its coverage guard walks `PlayerGames.handles` and
  `Playthroughs.handles` only. No test replays a session stream from an empty
  table, swaps the session table, or repeats a session command under its key.
- `make verify-playtime-parity` compares every `PlaytimeSource` member across
  both tables. The stats page also prints a session count, distinct days, the
  longest session, the game with most sessions, the game with the highest
  average, and the first and last play. The navbar asks whether any session
  exists. No instrument compares those.
- `make bench` states two budgets, the command's 100 ms at p95 and the
  rebuild's 60 s per 100,000 events. It times no read. Its seed writes the
  tracking pair and no session, so the third projector family's per-event
  cost is unmeasured, and the read paths it would time are empty.
- Corrected mode and the arbitration between two dated overlapping runs are
  unit-tested (`tests/test_playersession_conversion.py`,
  `tests/test_playersession_projection.py`). The conversion's `reconcile`
  runs a `CHECK` rebuild over the converted rows, and the conversion tests
  assert it clean for the seeded rows; the two-claimers case does not call
  it. No command stream in a gate holds a Corrected row.

## Gate 1: replay

`tests/test_playergame_playthrough_gate.py` becomes
`tests/test_projection_replay_gate.py`, one gate over the three
`CURRENT_STATE` tables. The name stops naming two of three.

**The stream.** After the tracking and run commands it already dispatches, it
records sessions through commands, never by appended event, because the gate
is a claim about the write path:

- `CreateSession` three times on one run: a running Timed row, a
  Duration-only row, a Corrected row. The Corrected row is the first
  synthetic branch; no legacy row converts into it.
- `EndSession` on the running row.
- `CorrectSessionTiming` that moves the Duration-only row to Timed, so the
  correction changes mode and every timing column.
- `DescribeSession` stating note, device and emulated at once, which appends
  the three description events.
- `MoveSessionToPlaythrough` onto a run at another game.
- `RemoveSession` then `RestoreSession` on one row; `RemoveSession` alone on
  another, so the stream leaves one removed row in the third table, as it
  does in the first two.

Each column takes two values across the stream, so a projector that writes a
constant fails. Every Timed and Corrected statement carries
`calendar_day_zone(library).key` as its day zone: `CreateSession` and
`CorrectSessionTiming` refuse any other, and a test library holds no
calendar row, so the zone is read, never written as a literal.

**The legs.** The three legs stay as #688 wrote them, over three tables:

1. Empty-database replay empties `PlayerSession`, then `Playthrough`, then
   `PlayerGame`, scoped by library, and replays. `rows_of` answers three
   `.values()` lists and refuses an empty one.
2. Rebuild and swap reports three tables with no row only live, none only
   rebuilt, none differing.
3. Idempotency repeats every command under its key; the head does not move.

The neighbour library's `row_versions` unions `games_playersession` with the
two it reads, so an unscoped session replay moves an `xmin` the test sees.

**The coverage guard** walks `PlayerSessions.handles` beside the other two. A
registered session event type the stream does not append fails and names
itself. The partial-stream test's expected count of missing types grows
from thirteen to twenty-two.

**The conversion leg** is not in this file. The conversion's replay check is
`reconcile` in `games/backfill/playersession.py`, which runs a `CHECK`
rebuild over the converted rows, and `tests/test_playersession_conversion.py`
asserts it clean for its seeded rows. The two-dated-claimers case there, the
second synthetic branch, gains the same assertion, so the bucket assignment
the converter recorded is the one replay reproduces.

**Rename fallout.** `tests/test_playersession_conversion.py` imports
`UNREACHABLE_KINDS` from the gate module; the #688 spec, the #697 spec, the
wave document and the CLEAN-02 plan name the file. Each follows the rename.

## Gate 2: statistics

One command compares every session figure the surfaces print, across both
tables, on restored production data.

**Name.** `verify_playtime_parity` becomes `verify_session_parity`, and the
Make target `verify-session-parity`. It compares the playtime figures as
before and the session figures below. The old name understated what the
command checks, and a gate with a narrow name is read as narrow.

**The page's readers.** `compute_stats` computes its session figures inline
today. They move to `games/reads/session_figures.py`, one function each,
taking `(library, year)` with `None` for all-time, and `compute_stats` calls
them. The parity module's projection side wraps them and the bench times
them, so the figure compared and the figure timed are the figure served.

**Figures.** `SessionFigureSource` is a protocol beside `PlaytimeSource`,
in `games/reads/session_parity.py`, with one member per figure a surface
prints from sessions and no playtime figure answers:

| member | surface | answer |
|---|---|---|
| `session_count(library, year)` | stats | int |
| `distinct_days(library, year)` | stats | int |
| `longest_session(library, year)` | stats | `(duration, game id, session id)` or None |
| `most_sessions_game(library, year)` | stats | `(count, game id)` or None |
| `highest_average_game(library, year)` | stats | `(average, game id)` or None |
| `first_play(library, year)` | stats | `(day, game id)` or None |
| `last_play(library, year)` | stats | `(day, game id)` or None |
| `has_sessions(library)` | navbar | bool |

Each figure is read once per played year and once all-time, under one
snapshot, in the library's calendar zone, as the playtime figures are. The
projection side reads `library_sessions`. The legacy side reads
`Session.objects.for_library` in the same module, which joins the import
guard's allow list with the reason "the statistics gate's legacy side; #772
takes it"; the guard needs the literal `from games.models import Session`
there. `games/reads/playtime_parity.py` keeps its name and its
`timedelta`-typed figure, because migration `0004`'s gate imports it; the
session module states its own figure and pair types and a public snapshot.

**Ties are broken on the page, not left.** The served page orders the
longest session by `(-effective_duration, -id)` and the most-sessions and
highest-average games by their value alone, so two equal games print in
whichever order the planner chose, and the legacy page did the same. A
parity figure cannot be "whichever", and neither should a page. This is a
page change: the three readers order by value descending, then the game's
`sort_name`, then the game's id, then the session's id where one is named,
and the page prints what the reader answers. The converted session's id is
the legacy row's own, so the legacy side breaks ties on the same key.

**First and last play are compared by day.** The page orders them by
`sort_instant`, which is midnight UTC for a Duration-only row, while the
legacy row keeps the instant its manual entry was stamped with. On a day
holding one of each, the two sides pick different rows with no defect, so
the figure is `(day, game id)` with the row picked by `(day, id)` on both
sides, and the page keeps `sort_instant`. Where the earliest or latest day
holds both shapes, the page-render rehearsal records the differing name and
attributes it to #689's `sort_instant`.

**The legacy side reads `duration_total`.** The legacy page's longest session
was `timestamp_end - timestamp_start` and its highest average was
`Avg(duration_calculated)`: a manual-entry row entered at zero. The
projection's `effective_duration` enters it at its stated time. #702 recorded
that delta as the projection's, so the legacy figure here is what the page
should have printed, not what it did: elapsed time plus the manual part,
which is the generated `duration_total`. The page-render rehearsal shows
the page-level delta where a manual row wins a superlative, and the wave
document records it.

**Zone.** Every figure is measured in the zone `calendar_day_zone(library)`
answers, printed per library as the command prints it today. The legacy
side reads its days in that zone; the projection side reads `effective_day`,
a stored column #1047's projector fixed in the same zone. `--day-zone`
moves the legacy reading and the today and last-seven-days windows only,
as now; it cannot move a stored day, and the command's output says so.

**Coverage.** `tests/test_playtime_parity.py` becomes
`tests/test_session_parity.py`. Its member-coverage test holds both protocols
whole: every member of both is compared or named in `UNCOMPARED_MEMBERS`
with a reason. A twin-of-each-mode test states that every session figure
agrees for a library whose legacy rows and projection rows describe the
same sessions, and that an emptied projection differs on every non-empty
figure.

## Gate 3: budget

`make bench` measures the third family and the reads that grow, and states
a budget for each.

**The seed writes three events a game.** After the tracking pair, in the
same batch under the same correlation id, `session_events(run_id, day,
day_zone)` appends one `library.playersession.created`: a finished Timed
row of one hour, started at noon in the day zone. The run id is the
tracking pair's second aggregate id, and `append` applies projectors event
by event in sequence, so the run row lands before the session's insert. The
day zone is `calendar_day_zone(library).key`, never a literal: a direct
append runs no command check, and a `--keep`'d library must pass
`verify-session-parity`. Days cycle over the last two years, one step back
per game, so per-day, per-month and distinct-day reads aggregate many rows
per cell and `played_years` stays two, not a century. `--seed N` seeds
`N // 3` games; a remainder seeds fewer events, which the help text says,
and a positive seed under three is refused as one that seeds no game.
Every site that spells the two-a-game ratio follows: the estimate and the
`seed // 2` in `benchmark_events.py`, the seed report's event count, the
`_SEEDED_TABLES` list `ANALYZE` walks, which gains `games_playersession`,
`docs/event-benchmarks.md`, and the tests that assert fifty events for
twenty-five games or a per-event slope over forty. `SECONDS_PER_SEEDED_EVENT`
and its two siblings are re-measured and pasted. The seed builder lives
beside `CreateSession` in `games/commands/playersession.py`, as
`tracking_events` lives beside `TrackGame`, for the reason that function
states: a seed that drifted from the command would measure a stream no
command produces.

**A second command budget.** The command scenario times `CreateSession` as
it times `TrackGame`: `iterations` dispatches of a Duration-only session on
seeded runs, `warmup` more discarded, at the charter's 100 ms p95. The
charter asks every phase that attaches a projector family to re-measure
against that budget. The amplification scenario counts the session
command's statements and rows beside the tracking command's.

**Six reads, one threshold.** A read scenario runs on the scratch library
and under `--library`. Each read executes `iterations` times after `warmup`
discarded runs; the sample is the wall time of executing the queryset to a
list, not of rendering a page. The budget is **20 ms at p95** for each, on
the documented development machine, gated only at 20 samples or more, as the
command budget is. One order of magnitude over every figure the wave
document recorded on the 2026-09-12 dump, so a join gone quadratic trips it
and `DEBUG` query logging does not.

| read | what executes |
|---|---|
| `session_page` | the first 25 rows of `readable_sessions(library)` in the list's `(-sort_instant, -id)` order: the five-join row path (run, tracked game, game, platform, device) the list view and the API's two GET routes share, lifted from `games/api.py` into `games/reads/player_sessions.py` |
| `game_playtime_sort` | the game list's first page with `sort=playtime`, through the queryset builder `list_games` calls |
| `stats_totals` | `total_playtime`, `session_count` and `distinct_days`, all-time |
| `stats_by_platform` | `playtime_by_platform`, all-time |
| `stats_by_month` | `playtime_by_month` for the latest played year |
| `stats_superlatives` | `longest_session`, `most_sessions_game`, `highest_average_game`, `first_play`, `last_play`, all-time |

The reads call the functions the views call. `list_games` builds its
queryset inline today and takes its sort from the request; it moves into a
named function in `games/views/game.py` that takes the sort, so the bench
names `playtime` and times the served plan. `session_page` and
`stats_superlatives` were never recorded; the #704 recording is their first
baseline. `_measure_existing` takes `iterations` and `warmup`, which it does
not today.

**The remedy is named, not built.** A read over its budget is materialised
by exactly the breaching cells, the shape #909 and #913 use. Nothing here
builds a totals table; the budget is the trigger the wave document promised
instead of one.

**Report.** `BenchmarkReport` gains `session_command: Timings | None` and
`reads: tuple[ReadTimings, ...]`, where `ReadTimings` is a name and a
`Timings`. The JSON schema number increments. `--library` mode fills the
reads and the rebuild, and leaves the command timings `None`, because a
command on a real library writes to it.

**Recording.** `docs/event-benchmarks.md` gains "The #704 recording": the
scratch run pasted whole, and a `--library` run against the restored
2026-09-12 dump, with the machine block, so the budget's first measurement
on production-shaped data is in the tree.

## The rehearsal

The gates run on restored production data once, by hand, and the results
are recorded. This is the operator's run, not `make check`.

**`make render-pages`.** A management command `render_pages` renders every
`READ_ONLY` route of `games/views/returns.py` as one user, to one file per
URL under a directory: list routes at every page of the user's page size,
`view_game` and `view_purchase` for every live row, `stats_by_year` for every
played year, `filter_builder` once per filter mode, and the rest once. It
logs the user in with Django's test `Client`, so no server runs; the client
names `localhost` as its host, because `ALLOWED_HOSTS` admits `testserver`
only under the test runner. It runs under `DEBUG`, where static names are
not hashed and every route is mounted, with `INTERNAL_IPS` overridden empty
so the debug toolbar renders no per-request timings into the page. Two
things then differ between two commits on identical data and are
normalised out: the CSRF token and the version footer. A route the user may
not open, such as `admin_settings` for a non-superuser, is recorded with
its status, so the set stays complete. The `READ_ONLY` set is guarded
complete against the route table, so a route added later is rendered
without an edit here.

**The command lands ahead of the stack.** The "before" render needs
`render_pages` on `main`'s code, where nothing this issue adds exists. The
command depends on nothing the wave adds, so it goes to `main` as its own
PR, outside the stack. Until that PR merges, the operator's run checks out
`origin/main` in a worktree and copies the one file in.

**The run.**

1. `make restore-dump DUMP=.dumps/timetracker-2026-09-12.dump`.
2. At `origin/main` with `render_pages` present, against that database:
   `make render-pages` for each user, into `before/`.
3. At the stack head, against the same database: `make migrate`, then
   `make render-pages` into `after/`, `make verify-session-parity
   ARGS="--all-libraries"`, `make verify-replay-parity`, `make bench
   ARGS="--library <id> --gate"`.
4. `diff -r before after`.

Every differing page is attributed: to #702's superlative delta, to
#1047's zone, to a tie the page prints the other way, or to a defect this
issue fixes. The attribution goes in the wave document and in the issue.
A difference nothing explains is a defect, not a footnote.

## What this lifts

The wave document states that nothing deploys between #700 and #704. With
the three gates green on the dump, the projection is the record and the
legacy table is inert. The wave document's #704 section records that, and
#772 takes the table.

## Documents

- The wave document's #704 section gains a Delivered block: the numbers,
  the attributed differences, and the constraint lifted.
- `CLAUDE.md`: the commands table (`verify-session-parity`, `render-pages`,
  `bench` help), the playtime reads paragraph's parity sentence, and the
  Session model bullet's guard sentence, which now names one more file.
- `docs/event-benchmarks.md`: the #704 recording.
- Every name the renames retire, found by grep: `verify-playtime-parity` and
  `verify_playtime_parity` in the Makefile, `CLAUDE.md`, the wave document
  and the #697 spec; `test_playergame_playthrough_gate` in the #688 spec,
  the #697 spec, the wave document, the CLEAN-02 plan and the conversion
  test's import; `test_playtime_parity` wherever it is named.
- Comment on #772: the allow list now holds `games/reads/session_parity.py`,
  and `verify_session_parity` goes with the table.

## Foreclosed

- The read budget times a queryset, not a view. A slow template, a slow
  component tree or a slow context processor is invisible to it. A page
  budget would need a live server and is a different instrument.
- The page-render rehearsal is not in `make check`. It needs two commits and
  one dump; a test cannot hold the "before".
- The seed's session is one shape, a finished Timed hour. Reads over
  Duration-only and Corrected rows are exercised on the scratch library by
  the command scenario's rows only, and on production data by neither,
  because production holds no Corrected row.
- `--seed` counts events, as before, and three now go to one game. A caller
  who wanted a session count names `N * 3`.

## Follow-up issues to file

None. Every remedy the budget names is #909's and #913's shape, and the
legacy side's removal is #772's.
