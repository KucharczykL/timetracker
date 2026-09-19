# Pass the Session replay, statistics and budget gates

Issue: [#704](https://github.com/KucharczykL/timetracker/issues/704). Part of the
[session delivery wave](2026-09-12-session-wave-design.md). Member 4 of stack
#1072; `render_pages` is its own PR on `main` (#1078).

## Purpose

Three gates run and fail. All three are green on the 2026-09-12 production
dump, so the projection is the record and the legacy table is inert.

## Replay

`tests/test_projection_replay_gate.py` is one gate over the three
`CURRENT_STATE` tables. Its stream records sessions through commands: one row
in each timing mode, an end, a correction that changes the mode, a description
that states three facts, a move to another game's run, a removal and a
restoration, and one row left removed. The three legs are unchanged: empty the
three tables and replay, rebuild and swap with an empty diff, repeat each
command under its key. The coverage guard walks `PlayerSessions.handles`. The
two-dated-claimers conversion case asserts `reconcile` clean.

## Statistics

`make verify-session-parity` compares the playtime figures and the session
figures across both tables, per played year and all-time, in the library's
calendar zone. `SessionFigureSource` in `games/reads/session_parity.py` names
eight figures: session count, distinct days, longest session, most-sessions
game, highest-average game, first play, last play, and whether any session
exists. The legacy side reads `duration_total`, so a manual entry counts its
stated time on both sides. The projection side wraps the readers in
`games/reads/session_figures.py`, which `compute_stats` calls, so the figure
compared is the figure served. (#1126 later moved the distinct days and the
first and last play to `games/reads/play_figures.py`, where they count
day-precision records as well.)

Every tie is broken: value, then the game's `sort_name`, then the game's key,
then the session's. The converted session keeps the legacy row's id, so both
sides break a tie on one key. First and last play compare `(day, game)` with
the row picked by `(day, id)`.

## Budget

`make bench` seeds three events a game: the tracking pair, then one finished
hour on the run, built by `session_events` beside `CreateSession`. It times
`CreateSession` at the charter's 100 ms p95 beside `TrackGame`, and six reads
at 20 ms p95: the session list's row page, the game list sorted by playtime,
and the stats page's totals, per-platform, per-month and superlative reads.
Each read executes the function the page calls.

The 20 ms verdict is given under `--library`, on a real library. On the
scratch seed the reads are measured and recorded, never gated: one session on
every one of tens of thousands of games is a shape no library has. A read over
its budget is materialised by exactly the breaching cells.

## Rehearsal

`make render-pages` renders every `READ_ONLY` route as one user to files,
lists whole, CSRF tokens and the version footer normalised. Run at `main` and
at the stack head against one restored dump, the directories diff on content.
Every differing page is attributed in the wave review; a difference nothing
explains is a defect.

## Out

The read budget times a queryset, not a view. The page rehearsal is not in
`make check`. The seed's session is one shape, a finished Timed hour.
