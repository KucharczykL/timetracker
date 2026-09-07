# Read Playthroughs on Game detail

Issue [#1012](https://github.com/KucharczykL/timetracker/issues/1012). The model
is [the PlayerGame read cutover](2026-08-28-issue-678-playergame-read-cutover-design.md),
which split one cutover by surface across #946, #947, #951 and #953.

The Game detail Playthrough section reads the projection, and so do the two
counts beside it. No screen this issue delivers reads `games_playevent`.

## The boundary this issue moves

#1012 was written for Game detail, the paginated list page and the purchase
list's Finished column. Two of those three left.

**The list page moved to #1013.** `list_playthroughs` calls `apply_sort` on every
request and `execute_filter` whenever `?filter=` is set. Both name legacy
columns: `started`, `ended`, `days_to_finish`, `game__sort_name`. #1013 owns
those. A list page switched to the projection while its sort still names
`days_to_finish` answers a 500, and a filter switched to the projection while the
page still lists legacy rows filters one model by another's fields. The page and
the things that order and narrow it are one surface and move together.

**The purchase Finished column moved to #1026.** It looked like one cell. It is a
cell, a sort key that `apply_sort` runs on every purchase request, and a second
sort key on Game reachable through `?sort=` and through a saved preset, all three
naming `Max("games__playevents__ended")`. It also asks a question no other
surface asks: what one aggregate over many games reports when a run states a
decade rather than a day. #1026 answers it once.

Game detail carries no `?filter=`, no sort keys and no quick bar, so it moves
alone. The wave document, both issues and #601 record the moves.

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

`_playevents_section` in `games/views/game.py` becomes `_playthroughs_section`.
Its heading, its caption and its container id name playthroughs; nothing targets
`playevents-container`, so the id is free to change. `Ended` becomes `Completed`:
one act, one verb.

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

Every live ordinary run of the tracked game gets a row, the actless one #679
states at tracking time included. That run is the game's first, and a person who
opens Game detail before playing sees `Playthrough 1` with three dashes and an
edit button, which is the row they will fill in.

The remove button renders on every row, the last one included, and
`RemovePlaythrough` refuses the last live ordinary run with its own sentence.
Hiding the button would state the same rule twice, in two places that can
disagree; the command is where the rule lives.

`Playthrough` declares no manager, so the section names its own scope. It selects
on `library` **and** on `player_game__library`, as `live_ordinary_runs` does:
a run may name another library's `PlayerGame`, which is the drift
`audit_library_ownership` reports, and a section scoped on one column alone would
render that run's number and link beside this library's game.

The section resolves the library's `PlayerGame` for the game — the pair is
unique, so there is exactly one — and passes it to the numbering.

### What the always-present row changes

`_game_section` drives three things off one count: the heading badge, the
`View all` gate, and the choice between the table and the empty message. The
count it gets is the number of rows, so the badge reads at least 1 on every
tracked game and the empty message becomes unreachable.

The empty branch stays. `view_game` resolves through `tracked_by`, and #679 and
#684 together give every tracked game a live ordinary run, so nothing reaches it
today — but a section that renders a bare count with no rows is worse than one
that says so.

Two tests assert the state that is now unreachable and are rewritten rather than
adjusted: `tests/test_rendered_pages.py` asserts the empty caption, and
`tests/test_game_detail_links.py::test_no_view_all_for_empty_section` asserts the
absent `View all` link, which now belongs to the purchase and session sections
alone. `tests/conftest.py` already gives every test Game a `PlayerGame` and a
default `Playthrough`, so no fixture changes.

## Numbering and order

`with_display_number` in `games/reads/playthrough_numbering.py` selects the live
ordinary rows and annotates each with its number. A removed run and the
imported-history bucket are therefore absent from the section, and
`display_name` needs no fallback.

The section orders by the four fields the window orders by, so the numbers read
down the page in order. Ordering by anything else would print 2 above 1.

### `numbered_for`, the deferral this issue owns

#679's review deferred `numbered_for(player_game_ids)` here, as the numbering's
first caller, and #601 records the verdict. This issue delivers it, with the
library in the signature:

```
numbered_for(library, player_game_ids)
```

`RowNumber` partitions over whatever the caller selected, so
`with_display_number` over a queryset already narrowed to one row answers 1 for
the run a person calls 4, and no exception marks it. `numbered_for` takes the
tracked games rather than a queryset, so the partition cannot be narrowed by the
caller: it selects every live ordinary run of those games, numbers them, and the
caller narrows afterwards or not at all.

The library is not optional and is not inferred from the games. Without it the
helper would number a drifted run into the partition, and the section would then
disagree with `live_ordinary_runs`, which scopes on both columns and is what
`RemovePlaythrough` counts across. Two readers of one partition must agree on
which rows are in it.

It takes a collection although this issue passes one game. The shape is decided
by the callers, and the second is the list page #1013 now holds, which passes a
page of tracked games. A singular entry point would be widened there rather than
used.

## Days to finish

`completed_upper` minus `started_lower`, in days. Equal bounds read 1, which is
what the legacy `GeneratedField` answered for a run that began and finished on
one day. Either bound absent reads `-`, which covers an endpoint with no marker
and an endpoint with a marker and no day alike.

A negative span reads `-` as well. It is not a length, and the legacy
`GeneratedField` coalesced it to 0, which read as a real number. Reversed
endpoints exist in the data: `games/preflight/playthrough.py` classifies
`REVERSED_ENDPOINTS`, and #684 converts those rows by appending events, which
does not pass through `endpoints_certainly_reversed` and so does not refuse them.
A dash says the pair states no span, which is the honest claim, and it costs the
person nothing: both dates are on the same row.

The widest span is deliberate: a run that states a month reports the days that
month could hold rather than nothing. #1014 reads the same two columns through
the statistics builders, and #1026 reads them through one aggregate; each adopts
this rule or states on its own issue why it differs. Those verdicts belong there,
not only here.

## The two counts

They do not count the same rows, and that is the decision.

**The section badge** counts the rows the section renders: every live ordinary
run. It is a count of a list, standing over that list.

**`Played N times`** counts the live ordinary runs whose completion is stated —
the marker set, the day known or unknown alike. It is a claim about the person's
history, and a run they have not finished is not a time they played through the
game.

That keeps the number a person reads today. The legacy row meant a completed run,
#684 states a completion marker for every one it converts, and #679's actless
default states none, so a library that has not touched the new commands reads the
same number after this lands as before it. A tracked game nobody has played reads
`Played 0 times` beside a section holding one empty row, which is right on both
sides: nothing was played, and there is one run to fill in.

A started but unfinished run reads 0 as well. The count follows completions by
this rule, deliberately; #1024 owns the affordance that states a count, and can
revisit the wording it stands beside.

The remove-game confirmation line follows the **section's** rule, not the count's:
it says what leaves the screen, and every row does. It reads the runs, so
`_removed_with_game` takes the library, which it does not take today. Removing a
game stamps the `PlayerGame`, not its runs — `Playthrough` is deliberately absent
from `REMOVABLE_MODELS` — exactly as the existing session line already works.

## The route ids name the run

`edit_playthrough` and `remove_playthrough` resolve a `Playthrough` inside the
library instead of a `PlayEvent` and its converted run.

This is forced. `run_for_row` maps a legacy row to a run, and the map is partial
in the direction this section needs: a run `CreatePlaythrough` stated after #687
names no legacy row at all. A section that linked legacy ids could not link most
future runs.

Both routes resolve on `library` and `player_game__library`, as the section does,
and both take only a live run: today's routes answer 404 for a removed legacy
row, so a run whose `removed_at` is stamped answers 404 too. A drifted run
resolved on one column alone would render another library's game name in the
heading and redirect into that library's detail page.

`tests/test_library_page_isolation.py` reaches these two routes through legacy
ids. After the flip those ids match no run at all, so the test would answer 404
for the reason it expects while testing nothing. It is rewritten to build a run
in the other library and ask for that.

`games/reads/playthrough_provenance.py` therefore narrows to the API, which
#1015 takes, and to the list page for one issue's window. The list page still
renders legacy rows, so its action buttons translate through the `runs_for_rows`
batch map and name the same run ids. A row the map does not reach renders no
actions; #771 takes that row with its table.

`tests/test_playthrough_api_writes.py` pins the provenance readers to exactly
`games/api.py` and `games/views/playthrough.py`, so the translation stays in the
view module even as the row builders split.

The route classification guard in `games/views/returns.py` keys on route names,
which do not change, so it needs nothing.

A bookmark naming a legacy id answers 404 after this lands. Both ids are UUIDs
in one path position, so no route can tell them apart, and the run is the id
that survives.

## Two row builders for one window

`create_playthrough_tabledata` takes a `PlayEvent`, and both surfaces share it.
Detail renders a `Playthrough`, so a run-shaped builder lands in its own module
beside the other run reads, and the legacy builder stays in
`games/views/playthrough.py` for the list page. The legacy one gains a `library`
parameter, because translating its action ids through `runs_for_rows` needs one
and it has none today. #1013 removes it when it moves the page.

## The prefill on Add playthrough

`add_playthrough` seeds its start date from `game.playevents.alive().latest("ended")`,
a legacy read no issue in the wave claims. It is reached from this section's
dropdown and it seeds a form this section's rows come from, so it moves here: the
seed reads the greatest stated completion over the library's live ordinary runs
of that game, and seeds nothing where that run states no day. It is the one write
path this read cutover touches, and it touches only what the write path reads.

## What stays legacy

The list page, its filter, its sorts, its quick facets and its saved presets,
until #1013. The two GET bodies of the API router, until #1015. The statistics,
until #1014. The purchase Finished column and the two `finished` sort keys, until
#1026. The table itself, until #771.

The API keeps legacy ids on the same path shape while Game detail serves run
ids. The two are UUIDs and no route distinguishes them, so for one window a
person holding both sees the same run under two ids. #1015 closes it.

For the window between this issue and #1013, the section and the list disagree
in both directions. A run stated after #687 has no legacy row, so it appears on
Game detail and not in the list the `View all` link reaches. Worse, a legacy row
frozen at its pre-#687 values is *stale*, not merely separate: a run whose start
was corrected shows one date in the section and another in the list, and a run
`RemovePlaythrough` took away stays in the list until #1013. #687 opened that gap
by switching the writes; this issue closes the half of it a person looks at
first, and #1013 closes the rest.

## Rollback

Reads only. No migration, no event, no column. Reversal is the revert.

## Verification

Focused tests:

1. each of the three endpoint states, on the start and on the completion;
2. a day, a month, a decade and a range, each rendered at its own precision;
3. the days rule at both bounds, at equal bounds, with either bound absent, and
   with the completion bound below the start bound;
4. the display numbers, in order, with a removed run and a bucket present and
   counted across by neither; `numbered_for` answering the same number for one
   game asked alone and asked beside others; and a run naming another library's
   `PlayerGame` counted across by neither library's partition;
5. the section over a tracked game with no act — one row, three dashes, a badge
   of 1, a `View all` link, and no empty message;
6. `Played N times` over a game with no act, a game with one converted run, a
   game with a started run and no completion, a game whose completion states no
   day, and a game with a removed run beside a live one;
7. the remove-game confirmation line, counting by the section's rule;
8. the remove button on a game's only run, rendering, and answering the
   command's refusal sentence on POST;
9. the edit and remove routes reached from the section; reached with a removed
   run's id, answering 404; reached with a run of another library, answering
   404; and reached from the list page through the provenance map;
10. the Add-playthrough prefill, seeded from the greatest stated completion, and
    seeding nothing where that run states no day.

`tests/test_game_detail_links.py`, `tests/test_rendered_pages.py` and
`tests/test_library_page_isolation.py` cover this section today and are rewritten
with it, for the reasons stated above. The full `make check` gate passes.
