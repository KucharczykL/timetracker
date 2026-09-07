# Switch lifecycle writes to Playthrough commands

Issue [#687](https://github.com/KucharczykL/timetracker/issues/687). The model
is [the PlayerGame write path](2026-08-28-issue-677-playergame-write-cutover-design.md),
and the order comes from [the Playthrough delivery wave](2026-09-04-playthrough-wave-design.md).

Every request path that wrote a `PlayEvent` row states a Playthrough command
instead. After this issue no request writes `games_playevent`. The legacy table
is still read, and the word `playevent` leaves every identifier that does not
derive from the model's own name.

## The window, and why no mirror is built

Reads stay legacy until #1012 through #1015. Between this issue and those four
the legacy screens are wrong in three ways, not one:

1. a run a person records appears nowhere: not on the Game detail section, not
   on the list page, not in a filter, not in the statistics, not on the API;
2. a run a person removes stays on every legacy screen, because the removal
   stamps the projection and not the row;
3. a run a person edits still reads with its old values, and the add form
   prefill still reads the old ones as well.

The second is the sharpest: a person may press Remove on the same row for the
rest of the window, and each press answers `Unchanged`.

Worse than stale, a run recorded after the cutover is unreachable. The edit and
the remove view take a legacy row id, and every link to them is rendered from
`PlayEvent.objects.for_library(...)`. A run with no row therefore has no button
anywhere until #1012 renders the projection.

That whole window is accepted. The four read issues land on one stack and reach
a release together, and no deployed tag stands inside it.

The alternative was a mirror: state the command, then write the run back onto a
legacy row, as #677 mirrors a `PlayerGame` fact onto the catalog. It needs a
column linking a row to its run, because #684 wrote none, and a data migration
to fill that column for every converted row. Column, migration and mirror are
all taken away again by #771, which is a week of code with a lifetime of hours.
The stale window costs less than the code that would close it.

## The act rule

A legacy row means a completed run. The table never grouped the sessions of a
run in progress: it recorded that a game was played through, with the days where
a person wrote them down. #684 read the rows that way, and a live write reads
them the same way, so an imported run and a new one say the same thing.

Every write therefore states both acts, with the day where the person gave one:

| the person states | the events say |
|---|---|
| started 2026-01-02, ended 2026-02-03 | start on 2026-01-02, completion on 2026-02-03 |
| started 2026-01-02, no end | start on 2026-01-02, completion with no day |
| no start, ended 2026-02-03 | start with no day, completion on 2026-02-03 |
| neither | start with no day, completion with no day |

A day is stated at day precision, through `TemporalValue.from_day`. The form
keeps its date pickers. The temporal grammar is available to whichever screen
issue wants it; this one changes no widget.

Many dayless runs under one game stay in order. `with_display_number()` ties
them on both bounds and breaks the tie on `created_at` and `id`, which are
monotonic per dispatch.

## The "Played +1" action goes away

The Game detail split button carried a `Played times +1` item: one click wrote a
dateless row and bumped the count beside it. It is taken out here, and #1024
owns the need behind it — a person stating how many times they played a game
through without filling in a form for each run.

The action stopped meaning anything under the run model, and the mismatch is not
cosmetic. A tracked game already holds one run from the moment #679 tracks it.
A click that filled that run in left the game with one run stating both acts,
which #1011 refuses to take off a tracked game — so a misclick was undoable only
by untracking the whole game. A click that instead appended a second dateless
run said nothing a person could read back.

Taken out with it: the `Played times +1` dropdown item, the `<play-event-row>`
custom element whose only behaviour it was, `ts/elements/play-event-row.ts`,
`_PlayEventRow` and its registered props, and the two e2e tests that pressed it
(`test_played_plus_one_fires_when_clicking_row_edge` and
`test_played_plus_one_refreshes_play_events_table` in
`e2e/test_played_dropdown_e2e.py`). The three remaining tests in that file
exercise the dropdown itself and stay.

The "Played N times" count and the "Add playthrough…" item stay. The count is a
legacy read until #1012, and the count button keeps its link to the add form.
`_played_row` returns the `SplitButtonDropdown` alone where it wrapped one in a
custom element, the section around it loses the htmx trigger that refreshed the
table after a `+1`, and the props codegen is re-run.

This also settles who reads a refusal on the API create. `fetchWithHtmxTriggers`
never checks `response.ok`, so the element kept its optimistic count on a 409
and showed nothing. With the element gone the endpoint answers only callers that
read status codes.

## The write path

Two modules, following the pair #677 delivered:

- `games/writes/playthrough.py` takes an actor and raises, wrapped in
  `answered("playthrough")`;
- `games/views/playthrough_writes.py` takes a request, toasts a `CommandFailed`
  and answers.

One correlation id per request, given to every dispatch the request makes.

### The first run of a tracked game is the one it already holds

#679 states a run the moment a library tracks a game, so a tracked game that was
never played holds one run stating no act. A write that created a second run
beside it would leave every such game with an empty run forever, and #1012 would
have to render it.

So the write path reads the game's live ordinary runs first:

- exactly one, and it states no act — the write states the acts and the note
  onto that run;
- anything else, none included — the write creates a run.

Nothing enforces "at most one actless run" at runtime. `Playthrough.Meta`
carries no constraint of the kind, and #684's `SURPLUS_ACTLESS_RUN` check runs
inside `reconcile()`, which only the conversion migration and `load_sample_data`
call. The branch above therefore does not rely on the invariant: it takes the
single-actless case and lets every other shape create a run.

The read this needs does not exist. `Playthrough` declares no manager, so
`Playthrough.objects` is the plain default, and the nearest thing is
`_other_live_ordinary_runs`, private to the command module and shaped around
excluding one run. `games/reads/playthrough_runs.py` states it: the live
ordinary runs of one tracked game, filtered on `library`, `player_game`,
`removed_at__isnull=True` and `kind=ORDINARY`.

### One command states a whole new run

`CreatePlaythrough` is extended to state the run and both its acts. It gains
three fields beside `game_id`: `started` and `completed`, each an `ActStatement`
or `None`, and `note`. Its build appends, in order: the creation, a note where
the note is not blank, the start where one is stated, and the completion where
one is stated. It mints the run identity inside the build and threads it through
all four.

`ActStatement` is the small pair the endpoint commands already carry
separately — a `TemporalValue` or `None` for the day, and a note. It is needed
because `None` alone is taken: under the act rule a stated act with no day is
`None` for the day, so a field of `TemporalValue | None` leaves no way to say
"this act never happened", which is exactly the run `TrackGame` states.
`canonical_command_input` already encodes `TemporalValue`, and the pair is a
plain dataclass beside it.

One build rather than four dispatches, for a reason the family itself states: a
creation that commits followed by a start that fails leaves a run with no act,
and `RemovePlaythrough` refuses to take the last live ordinary run off a
tracked game. The failure would leave a row a person cannot get rid of. One
build also matches #986: one submit, one transaction.

The build refuses a completion that certainly precedes its start, through the
`endpoints_certainly_reversed` rule #681 already states, before it appends
anything.

Nothing dispatches `CreatePlaythrough` in production today, so the extension
costs no caller; the five constructions in `tests/test_playthrough_command.py`
take the new fields.

### Stating acts onto a run that already exists

Both the branch above and the edit path state differences, under one correlation
id:

1. `DescribePlaythrough` with the note, where the note is different;
2. `CorrectPlaythroughStart`, where the start day is different;
3. `CorrectPlaythroughCompletion`, where the completion day is different.

Where an endpoint is not stated at all, the first statement is
`StartPlaythrough` or `CompletePlaythrough` rather than a correction, because a
correction of an unstated endpoint is refused by design. An adopted run states
neither endpoint, so it always takes that branch; a run this path created states
both, and so does a run #684 converted.

Three dispatches rather than one composite: each command answers `Unchanged`
for state the run already holds, so a submit that fails after the first act is
finished by submitting again. A creation has no such property, which is why it
is one build and this is three.

Two rules keep three dispatches from stating something the run cannot take back.

**The reversal is refused before the first one.** `StartPlaythrough` compares
its day against the completion the run already states, and an adopted run states
none, so a reversed pair would commit the start and refuse only at the
completion — and no command withdraws a stated act. The write path therefore
applies `endpoints_certainly_reversed` to the values it is about to state,
before it dispatches anything, and answers refusal 1 from there.

**A correction carries the endpoint's note.** `CorrectPlaythroughStart` and
`CorrectPlaythroughCompletion` state `(when, note)` as a pair, and #684 wrote
`""` as every endpoint note, putting the legacy note on the run. A day-only
correction therefore passes `note=""`, or it states a note the person never
wrote.

**The choice of command is re-read once.** The write path picks
`StartPlaythrough` or `CorrectPlaythroughStart` from a read taken before
dispatch takes its lock, so two requests racing on one run can both read
"unstated" and the second is refused for stating a start twice. On that refusal,
and on its mirror for a correction of an endpoint that turned out unstated, the
write path re-reads the run and dispatches once more — one attempt, the shape
tracking already uses. A second refusal is answered.

### Removal

The remove view keeps its confirmation page and becomes one `confirm_and_apply`
call dispatching `RemovePlaythrough`. It writes no `removed_at` on the legacy
row. `confirm_and_apply` renders a refusal's sentence with its status code, so
the refusals below reach the page unchanged.

The command refuses the last live ordinary run of a tracked game. A person who
removes the only playthrough of a game therefore reads *"This is the only
playthrough of that game, and a tracked game keeps one. Remove the game itself
instead."* where the row used to leave the list. This is the law the wave
committed to, and it is a change from today.

Its consequence is recorded here rather than solved here: no command withdraws
a stated act. A person who fills in the run their tracked game already held, and
then wants it gone, removes the tracked game. Taking "Played +1" out keeps that
wall off a single misclick, which is why it goes in this issue rather than in
#1024. A command that withdraws an act belongs to the family, not to a write
cutover.

### Tracking the game first

A game the library does not track raises `PlayerGameNotTracked` from the
resolver inside the build. The write path catches it in a nested `try` inside
`answered("playthrough")`, the shape `record_facts` uses, calls `track_game`,
and dispatches once more — one attempt, never a loop.

The retry re-runs the adopt-or-create branch rather than re-dispatching the
command it built. `TrackGame` states a default run of its own, so a re-dispatch
of the original `CreatePlaythrough` would leave a second run beside it.

### The status beside the act

`mark_as_finished` keeps its behaviour and changes its envelope: today
`_record_completed` mints a fresh correlation id, and after this issue it takes
the request's. No shipped reader groups events by correlation id —
`playergame_history` groups on `aggregate_id` and `event_type` — so no screen
changes; this is plumbing for #683 and the journal. The two stay two dispatches
and two transactions, because `run_in_transaction` refuses to nest.

## The bridge from a row to its run, which #771 takes away

#684 wrote no column linking a legacy row to the run it became, and this issue
builds none. It reads the provenance the conversion recorded: a
`library.playthrough.created` event the conversion minted from a row carries
that row's id in `source_metadata.play_event_id`, and the event's `aggregate_id`
is the run.

The mapping is partial by construction. A default run the conversion minted
carries no `play_event_id`, and neither does a run `TrackGame` states, because
no row became either.

`games/reads/playthrough_provenance.py` states one function, which takes a
library and row ids and answers a mapping to run ids. Its docstring names #771
as the issue that takes the module away, and #771's own text gains the module,
so the removal is tracked rather than remembered.

The query filters on `library` and on the event type before it reads the JSON
column. `source_metadata` carries no index, so the read is a scan of one
library's events. That is accepted: four low-traffic paths, one table that a
private library keeps small, and a module whose life is measured in days. An
index on the JSON column is the escape if a library ever makes the read felt.

Four call sites read it: the edit view, the remove view, the API update and the
API removal. A test pins that list, so a fifth reader is a decision somebody
makes on purpose.

### Rows that map to nothing

Such a row is refused, on the edit path and the removal path alike, with one
sentence naming the state. Answering it any other way would either track a game
behind the person's back or create a run only to remove it in the same request.

Two populations reach that refusal, and only one of them is reachable from a
screen:

- **rows of a game the library no longer tracks.** #684 pages live `PlayerGame`
  rows, so it never converted these. `PlayEvent.objects.for_library` filters on
  the catalog game's own mark and not on tracking, so they stay on the list page
  with buttons that now always refuse. Untracking a game is an ordinary action,
  so this is a real population, not a fixture artefact.
- **rows of a catalog-removed game.** Also skipped by the conversion, and
  already absent from `for_library`, so only a stale link reaches one.

The size of the first is a number, not a guess: `make preflight-playthroughs`
reports it, and the plan reads it against a restored production copy before the
change merges. A count large enough to matter turns this from a refusal into a
conversion pass, which #684 owns. Against the 2026-09-06 copy the number is
zero: `rows_untracked`, `rows_on_removed_game` and `rows_without_projection` are
all 0 of 209 rows, so no live row on that library meets the refusal.

## What each surface does

| surface | after this issue |
|---|---|
| Add view, and add-for-game | adopt, else `CreatePlaythrough`, with the form's days and note |
| Edit view | the three difference statements above |
| Remove view | `confirm_and_apply` with `RemovePlaythrough` |
| `POST /api/playthrough` | the same adopt-or-create; answers 204 |
| `PATCH /api/playthrough/{id}` | the same difference statements; 409 on a refusal |
| `DELETE /api/playthrough/{id}` | `RemovePlaythrough`; 409 on a refusal |
| `GET /api/playthrough`, `GET /api/playthrough/{id}` | the same bodies as today, reading the legacy table, until #1015 |
| the form | a plain `Form`, no `ModelForm`, no `save()` |

The POST answers 204 because the body it used to answer was the row it created,
and no row is written. The projection-backed shape belongs to #1015.

The form keeps its fields, its widgets and its validation and stops being a
`ModelForm`, because no model row is written. It already declares `game`
itself, and `__init__` already narrows that field to `Game.objects.for_library`,
which stays exactly as it is — a run belongs to the library's own catalog row.
Restated by hand, because `ModelForm` derived them: `started` and `ended` as
`DateField(required=False)`, and `note` as `CharField(max_length=255,
required=False)`. `mark_as_finished` and the `DatePickerWidget` assignment are
unchanged. The edit view stops passing `instance=` and passes `initial=` built
from the row instead. On an edit a posted change of game is answered as a field
error on `game`, stated by the form's own `clean_game`: a run belongs to its
tracked game, and no command moves one. The control itself stays live, because
disabling a composite widget means disabling the search input inside it, and a
field error says the same thing with no widget surgery and no way for a
scripting-off submit to slip past.

## The rename

The word `playevent` named a completion stamp. The record is now a run: two
acts, a name, a note, days at any precision, and — after #700 and #701 — the
sessions that belong to it. Every identifier carrying the old word is on its way
out, and this issue clears the ones that are free to move.

Renamed here:

| from | to |
|---|---|
| `games/views/playevent.py` | `games/views/playthrough.py` |
| `games:add_playevent`, `…_for_game`, `edit`, `remove`, `list` | the same five, `playthrough` |
| `/playevent/…` paths | `/playthrough/…` |
| `PlayEventForm` | `PlaythroughForm` |
| `/api/playevent` | `/api/playthrough` |
| `parse_playevent_filter` | `parse_playthrough_filter` |
| `playevent_count`, `playevent_filter` criterion keys | `playthrough_count`, `playthrough_filter` |
| `PLAYEVENT_SORTS`, `PLAYEVENT_DEFAULT_SORT` | the same two, `PLAYTHROUGH` |
| the `playevents` filter mode key | `playthroughs` |

The mode key is one string in six tables — `MODE_PARSERS`, `FILTER_MODE_LIST_URLS`,
`FILTER_MODE_MODELS`, `BUILDER_MODES`, `QUICK_FACETS`, `MODE_SORTS` — and in
`FilterPreset.MODE_CHOICES`. All seven move together, and contract tests already
hold their key sets equal.

`<play-event-row>` needs no rename, because it is taken out.

### What the model's own name holds back

Three names are the model's name wearing a suffix, and they cannot move until
#771 renames the model:

- the filter class `PlayEventFilter`. `filter_for_model` resolves
  `globals()[f"{model.__name__}Filter"]` by convention and keeps no registry, so
  a rename here is a `KeyError` on the quick bar, the nested builder and
  `tests/test_quick_filter_bar.py`.
- the singular model key `"playevent"`, which is `PlayEvent._meta.model_name`.
  It is what `apps.get_model` takes, what `RelationTarget.model` carries out of
  `_comparison_model()`, and what the builder URL segment `/playevent/filter`
  reads. `ts/elements/filter-tree/fixtures.json` names it, and so does
  `FILTER_FOR_MODEL` in `tests/test_filter_tree_contract.py`; neither changes.
- `related_name="playevents"` and `game.playevents`, including the two sort
  annotations `Max("playevents__ended")` on Game and on Purchase.

Breaking the convention with an explicit model-to-filter map would move all
three, and #771 would remove the map again. #771's issue body gains these three
names instead.

Left for #1013 and #1015: the logic behind the renamed filters, sorts and
facets, which those issues move onto the projection. Both issues gain a line
saying the names are already done.

### The API router

One router carries the reads and the writes, and it is mounted once. The prefix
therefore moves whole: the GET handlers keep their bodies and change URL, and
#1015 rewrites those bodies in place. This takes a surface the wave doc assigns
to #1015, so the wave doc's boundary text is amended in the same commit.

Ninja derives each route's `url_name` from its view function, so renaming the
five functions renames the five reverses. The one non-test reverse,
`api-1.0.0:create_playevent` in `_played_row`, goes away with the element. Every
other caller is a test, and eleven of them name `/api/playevent` as a literal
string. No test pins the OpenAPI schema for these paths.

### Saved presets

Two stored strings carry the old word, so one data migration rewrites them in
`games_filterpreset`:

- `mode`, where `playevents` becomes `playthroughs`;
- `object_filter`, where the keys `playevent_count` and `playevent_filter` are
  rewritten wherever they appear, at any depth, because `OperatorFilter` nests,
  and inside `field_comparisons` as well.

`find_filter` needs no pass: it holds only `sort` and `per_page`, and the sort
keys of every mode are plain words like `started` and `ended`, which no rename
touches.

Changing `MODE_CHOICES` makes Django emit an `AlterField`, so the schema
operation and the data operation travel in one migration file. It reverses by
the inverse rewrite. #1013 changes what those criteria mean without renaming
them again, so this is the only pass over saved presets.

Route paths change with no alias: the links are built by `action_url` and
`reverse`, an `?origin=` is validated against the route table, and
`games/views/returns.py` classifies the renamed routes, so a stale bookmark is
the whole exposure. Taking the element out re-runs `make gen-element-types`.

## Refusals a person can now meet

Five, all of them new to these screens:

1. a completion that certainly precedes its start;
2. the removal of a game's last live ordinary run;
3. a changed game on an edit;
4. an act under a removed game or a removed run;
5. an act on a legacy row the conversion never turned into a run.

Each is answered through `answered("playthrough")`: a sentence in a toast for a
view that stays on its page, the sentence on the confirmation page for a
removal, and a 409 with the sentence for the API.

## Tests

New:

- one per surface, over the events the stream holds afterwards: the four shapes
  of the act rule, and the note;
- the first playthrough added to a tracked game states its acts onto the run the
  game already holds, and creates none;
- the second creates one;
- the edit path states only the differences, and states nothing twice;
- a resubmitted edit answers `Unchanged` and appends nothing;
- an unstated endpoint reached by an edit is a first statement, not a
  correction;
- a day-only correction leaves the endpoint's note alone;
- a reversed pair is refused before any event is appended, on the create path
  and on the difference path alike;
- an untracked game is tracked once, the branch is re-run, and one run is left;
- the five refusals above, each answered where its surface answers;
- no request path writes a `games_playevent` row;
- the provenance bridge maps a converted row to its run, answers nothing for a
  default run or a row the conversion skipped, and is read from four call sites
  and no fifth;
- the preset migration rewrites a mode and a nested criterion key, and reverses;
- every renamed route is classified in `games/views/returns.py`, which its own
  completeness guard already checks.

A test of the adopt branch builds its game through `track_game()`. The autouse
fixture in `tests/conftest.py` writes `PlayerGame` rows straight through the
ORM, so a fixture-tracked game holds no run at all and would take the create
branch for the wrong reason.

Rewritten, because the rename gives them no route to reverse or no name to
import: `tests/test_paths_return_200.py`, `tests/test_html_validity.py`,
`tests/test_sorting.py`, `tests/test_date_time_rendering_paths.py`,
`tests/test_playergame_view_cutover.py`, `tests/test_library_page_isolation.py`,
`tests/test_session_playhistory_runtime_identity.py`, the eleven files naming
`/api/playevent` as a literal, and the rest naming the five route names,
`PlayEventForm`, `parse_playevent_filter`, `PLAYEVENT_SORTS` or the mode key.
The plan sizes that list; around fifty files under `tests/` and `e2e/` name the
word, and most name only the model, the relation or the singular key, which all
stay.

`tests/test_removal_confirmation.py` needs three changes, not one. Its game is
already tracked, because the autouse fixture tracks every game it creates; its
`PlayEvent.objects.create(game=owned)` mints no conversion event, so the row
maps to no run and meets refusal 5; and its assertions read
`PlayEvent.objects.for_library`, which the removal no longer touches. The
fixture states its run through the write path and the assertions read the
projection.

`tests/test_rendered_pages.py` and `e2e/test_custom_elements_e2e.py` name the
element that goes away.

A test that posts through a view carries `django_db(transaction=True)`, because
`run_in_transaction` refuses to nest.

Existing tests that assert a `PlayEvent` row after an add or an edit are
rewritten to read the projection. Tests that read the legacy table for anything
else are left alone; #1012 through #1015 own them.

## The change in three commits

The issue is one outcome and three reviewable pieces, in this order:

1. **the write cutover** — the two write modules, the read of a game's live
   ordinary runs, the extended `CreatePlaythrough`, the four surfaces, the five
   refusals, and the removal of "Played +1" with its element and its two e2e
   tests. Every behavioural risk in this issue is here, and this is the commit a
   revert would take back.
2. **the rename and the router move** — no behaviour, verified by the suite
   passing under new names.
3. **the preset migration** — the `AlterField` and the data rewrite, verified
   on a restored copy with `make verify-dump`, independent of whether the rename
   that motivates it reads well.

## Rollback

The write path appends events and writes no legacy row, so its reversal is the
projection rebuild #667 provides. The preset migration reverses by the inverse
rewrite. Nothing in this issue is destructive, and the legacy rows are exactly
as #684 left them.

## Verification

The full `make check` gate, including `e2e/`. Beyond it, four things this issue
is measured by:

1. a run recorded by each write surface reads back from the projection with both
   acts and the right days;
2. no request path adds a `games_playevent` row — the fixture loader and the
   sample anonymizer still write the table, and they are out of scope;
3. a library with saved presets naming the old mode loads its presets after the
   migration;
4. `make preflight-playthroughs` against a restored production copy reports how
   many rows meet refusal 5, and the number is small enough to accept.
