# Read Playthroughs on Game detail

Issue [#1012](https://github.com/KucharczykL/timetracker/issues/1012). The model
is [the PlayerGame read cutover](2026-08-28-issue-678-playergame-read-cutover-design.md),
which split one cutover by surface across #946, #947, #951 and #953.

The Game detail Playthrough section reads the projection. So do the two counts
beside it and the purchase list's Finished column. No screen this issue
delivers reads `games_playevent`.

## The boundary this issue moves

#1012 was written for Game detail and the paginated list page. The list page
moves to #1013.

`list_playthroughs` calls `apply_sort` on every request and `execute_filter`
whenever `?filter=` is set. Both name legacy columns: `started`, `ended`,
`days_to_finish`, `game__sort_name`. #1013 owns those. A list page switched to
the projection while its sort still names `days_to_finish` answers a 500, and a
filter switched to the projection while the page still lists legacy rows filters
one model by another's fields. The page and the things that order and narrow it
are one surface and move together.

Game detail carries no `?filter=`, no sort keys and no quick bar, so it moves
alone. #1013 grows the list page; the wave document and both issues record the
move.

## What a run states on screen

The legacy row had one column per endpoint, and null said nothing at all. A run
separates the act from its day, so three states reach a person where two did:

| the run states | the section renders |
|---|---|
| no marker | `-` |
| a marker and a day | the day, at its own precision |
| a marker and no day | `Unknown` |

`stated_start` and `stated_completion` in
`games/reads/playthrough_endpoints.py` answer the marker; `TemporalText` in
`common/temporal_presentation.py` answers the words, which is the presentation
#963 delivered.

The third row is the point of the two endpoint fields, not a side effect of the
conversion. #684 states both acts for every legacy row, because a legacy row
means a completed run, and it states no day where the legacy column held none.
Those rows render `Unknown` here for the first time.

## The section

`_playevents_section` in `games/views/game.py` becomes the Playthrough section.
Its heading and its caption name playthroughs. `Ended` becomes `Completed`: one
act, one verb.

| column | source |
|---|---|
| Playthrough | `display_name(run)` |
| Started | `stated_start(run)`, by the table above |
| Completed | `stated_completion(run)`, by the table above |
| Days to finish | the rule below |
| Note | `run.note` |
| Created | `run.created_at` |
| Actions | edit and remove, naming the run |

`Note` is the run's own note. `start_note` and `completion_note` belong to the
acts, and no column on this table holds an act's words; #1015 owns the screen
that states them.

The queryset is scoped on the library beside the parent, never inferred, as
`live_ordinary_runs` is: a run may name another library's `PlayerGame`, which is
the drift `audit_library_ownership` reports.

## Numbering and order

The rows pass through `with_display_number` from
`games/reads/playthrough_numbering.py`, which selects the live ordinary rows and
annotates each with its number. A removed run and the imported-history bucket
are therefore absent from the section, and `display_name` needs no fallback.

The section orders by the four fields the window orders by, so the numbers read
down the page in order. Ordering by anything else would print 2 above 1.

## Days to finish

`completed_upper` minus `started_lower`, in days. Equal bounds read 1, which is
what the legacy `GeneratedField` answered for a run that began and finished on
one day. Either bound absent reads `-`, which covers an endpoint with no marker
and an endpoint with a marker and no day alike.

The widest span is deliberate: a run that states a month reports the days that
month could hold rather than nothing. #1014 reads the same two columns through
the statistics builders, so it adopts this rule or states on its own issue why
it differs. The verdict belongs on #1014, not only here.

## The two counts

`Played N times` and the remove-game confirmation both count the live ordinary
runs that state either act.

#679 gives a tracked game one run from the moment the library tracks it, so
counting every run would read `Played 1 times` before anybody played anything.
Counting the acts skips that run and counts every run #684 converted, because a
converted run states both. The number a person reads back is therefore the
number of legacy rows their library held.

The confirmation line names playthroughs by the same rule. Removing a game
stamps the `PlayerGame`, not its runs, so the line says what leaves the screen,
which is the honest claim.

#1024 owns the affordance that states a count. This issue renders one.

## The route ids name the run

`edit_playthrough` and `remove_playthrough` resolve a `Playthrough` inside the
library instead of a `PlayEvent` and its converted run.

This is forced. `run_for_row` maps a legacy row to a run, and the map is partial
in the direction this section needs: a run `CreatePlaythrough` stated after #687
names no legacy row at all. A section that linked legacy ids could not link most
future runs.

`games/reads/playthrough_provenance.py` therefore narrows to the API, which
#1015 takes, and to the list page for one issue's window. The list page still
renders legacy rows, so its action buttons translate through the `runs_for_rows`
batch map and name the same run ids. A row the map does not reach renders no
actions; #771 takes that row with its table.

A bookmark naming a legacy id answers 404 after this lands. Both ids are UUIDs
in one path position, so no route can tell them apart, and the run is the id
that survives.

## Two row builders for one window

`create_playthrough_tabledata` takes a `PlayEvent`, and both surfaces share it.
Detail renders a `Playthrough`, so a run-shaped builder lands beside it and the
legacy one stays for the list page. #1013 removes the legacy builder when it
moves the page.

## The purchase Finished column

`_render_purchase_row` in `games/views/purchase.py` reads
`PlayEvent.objects.for_library(...).latest("ended")` over the purchase's games.
It reads the greatest `completed_upper` over the live ordinary runs of those
games instead, as one aggregate.

It is in this issue because it is a rendered table reading a lifecycle date, and
because it is the last such read outside the API. Leaving it would hand #771 a
legacy read with no owner in this wave.

## What stays legacy

The list page, its filter, its sorts, its quick facets and its saved presets,
until #1013. The two GET bodies of the API router, until #1015. The statistics,
until #1014. The table itself, until #771.

For the window between this issue and #1013, the section and the list disagree:
a run stated after #687 has no legacy row, so it appears on Game detail and not
in the list the View all link reaches. #687 opened that gap by switching the
writes; this issue closes the half of it a person looks at first.

## Rollback

Reads only. No migration, no event, no column. Reversal is the revert.

## Verification

Focused tests:

1. each of the three endpoint states, on the start and on the completion;
2. a day, a month, a decade and a range, each rendered at its own precision;
3. the days rule at both bounds, at equal bounds, and with either bound absent;
4. the display numbers, in order, with a removed run and a bucket present and
   counted across by neither;
5. both counts, over a tracked game with no act, a game with one converted run,
   and a game with a removed run beside a live one;
6. the edit and remove routes reached from the section, and reached from the
   list page through the provenance map;
7. the purchase Finished column, over a purchase whose games hold runs at
   several completions.

`tests/test_game_detail_links.py` and `tests/test_rendered_pages.py` cover the
section today and move with it. The full `make check` gate passes.
