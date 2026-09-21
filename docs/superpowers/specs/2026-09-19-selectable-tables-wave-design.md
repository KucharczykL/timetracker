# Selectable tables and Session organization delivery wave

Date: 2026-09-19

Parent epic: [#601](https://github.com/KucharczykL/timetracker/issues/601)

## Purpose

This document is the wave review #601 requires before the Selectable tables
and Session organization group begins. It replaces the placeholder ordering
of #711 through #718 with a dependency-ordered sequence, states each issue's
boundary, pulls in two issues the last wave filed against its own bulk act,
and names what the production data says the organizer is for.

The eight placeholders carry an outcome line and the shared acceptance
block. Three of them describe one table personality from three sides, one
describes a population of one row, and none of them knows that a bulk act
already ships without the framework they define. This review merges one,
closes two through another, adds one action, and leaves seven issues.

The Historical Playtime wave is the model: no deployment window and no
stack, because nothing here converts data.

Every empirical claim below was checked against a production dump taken on
2026-09-19, migrated to `0011`, and against the code. A clean-context
review against the code corrected the first draft; its findings are included,
and the corrections are named under "What was applied".

## Product boundary

A person selects rows of a table and acts on the selection: removes them,
moves sessions to a playthrough, turns written-down sessions into historical
playtime records. The act runs as one batch the person can undo as one. The
Playtime page's session list, narrowed to one game and made selectable, is
the organizer the charter describes.

This wave does not add drag and drop, does not add a second session list,
does not make the Games, Purchases, Devices or Platforms lists selectable,
does not merge the two Playtime tabs (#1100), and does not build the Trash
(#795).

## What the data says

One library. The conversion (#700) placed every legacy session by rule and
left one bucket.

| population | count |
|---|---|
| live ordinary runs | 869 |
| sessions in the imported-history bucket | 1 |
| games with two or more live runs | 8, none with more than 3 |
| sessions dated outside their sole run's stated interval | 113, on 39 runs |
| busiest run | 47 sessions |
| runs holding no session | 145 |
| run pairs at one game whose session days overlap | 0 |

The charter's organizer reconciles "ambiguous" sessions, which it defines as
the bucket's. That population is one row: a Timed session at Our Red String
on 2026-04-14, at a game that also holds two live runs. #717 as written is
one move.

The organizer's real population is the third row of the table. Elden Ring's
sole run states February to April 2022 and holds 32 sessions running to July
2024; Pokémon Pokopia's run states ten days and holds 25 sessions beyond
them; The Rise of Golden Idol holds 8. The sole-run rule assigned them
without asking, which was right, and nobody has since been offered the
question. The organizer's first facet is that question.

Bulk sizes, for the chunking decision:

| list | live rows |
|---|---|
| sessions | 2,817 |
| playthroughs | 870 |
| games, purchases | 860, 805 |
| devices, platforms | 13, 25 |
| the reclassification review at 8 hours | 93 |

Every real bulk is under 100 rows except "all matching" on the session list.

## The wave's siblings

Two open issues are this wave's questions asked against #1098's page, and
join it:

- **#1125** — the bulk reclassification posts one hidden field per row and
  meets Django's field cap at a thousand. The framework decides what a
  confirmation posts once, below.
- **#1123** — the bulk reclassification offers no Undo because nothing names
  the batch. The framework decides the batch's identity once, below. Today's
  page already stamps one `correlation_id` across every row it converts, so
  a batch converted before this wave ships has the identity; nothing shows
  it to a person until the Trash (#795) lists batches.

#1100 waits behind this wave, as filed. #481, #520 and #521 touch the same
table and stay outside.

## Selection

`StyledTable` gains a selectable personality: a custom element
`<selectable-table>` wrapping `<responsive-table>`, which keeps owning column
dropping. The charter's rules hold, and this wave settles the shape:

- The checkbox is the first child of the pinned identity cell, so the cell
  stays the row's `<th scope="row">` and its pinning and shadow above the
  `md` breakpoint hold. The element builds it: the server renders one
  `data-selection-key` attribute on each `<tr>`, through `make_row`'s
  attributes, and `<selectable-table>` inserts the checkbox when the mode
  turns on and takes it out when the mode turns off, so `TableRow` renders
  the first cell's content verbatim and the view's row builder does not
  know the checkbox exists. A row swapped into the live `tbody` while the
  mode is on arrives bare, so the element observes the `tbody` and
  decorates the new row, checked when its key was checked before the swap.
  Only the checkbox selects; the row's links and immediate controls keep
  their meaning. The checkbox is not a column and does not count against
  `MAX_DATA_TABLE_COLUMNS`.
- Selection is a mode. A Select toggle turns it on: one ends a slim strip
  above the table, always visible, and one ends the footer's selection
  line, visible with the mode, so the control sits at an edge whichever end
  of a long table the person is at. Every checkbox is built when the
  element connects and shown only with the mode, so turning the mode on
  moves no row; the column is reserved on a selectable table always, which
  the header label clears and the name floor below `md` budgets. The
  reserve stands empty while the mode is off, which the user finds
  awkward on the shipped list; #1212 decides whether it collapses while
  the mode is off, before #718 judges the finished pages. The mode
  is off on a page load unless the list holds a selection, which the
  element restores from session storage together with the mode. There is
  no header checkbox. Check-all for the page, "Select all N matching" with N read
  from the paginator, the count, Clear and the actions all live in the
  footer's selection line, which the toggle opens above the pagination
  row. Without a paginator there is no "all matching": the page is the
  matching set, on Game detail's tables and on a list shown whole. Prior art, settled by the user: PatternFly, Carbon, Polaris, Helios
  and SABnzbd's Glitter queue, whose check-all also lives in its multi-edit
  bar and whose rows also do not toggle on click.
- A selection outlives the page. The element keeps the statement, never
  the rows: the keys a person clicked, or the scope and its exclusions,
  in session storage keyed on the library, the table's caption and the
  list's path, one per table, with the filter inside the value: paging
  keeps it, a filter that does not match restores nothing and keeps the
  value for a person who goes back, two tables on one page keep two, and a
  second person signing in at the same browser inherits none, since session
  storage outlives a logout. Clear, the mode turned off and the submit of a bulk action forget
  it, so a statement acted on is never restored over the rows it changed:
  the element answers a `submit` in the actions slot itself, and a tray
  that posts without a form calls its public `forgetAndClose()`. That
  answer runs inside the submit, before the form's entry list is built,
  and dispatches `selectable-table:change` with an empty statement, so
  the slot's form carries the statement it latched at the press and
  writes nothing on that event; a slot that wrote there would post zero
  rows to the runner and see a confirmation with no submit. The element
  dispatches at connect only when it restores, on itself, and the slot's
  element upgrades after it, so the slot reads the element's public
  `statement()` when it connects rather than waiting for a change. Every
  act's slot content, #714's move included, keeps both rules. An "all matching" statement
  is not restored on a page that reports no count. The runner reads the
  statement the POST carries and nothing else, so what the element keeps
  changes nothing in the runner; a count that no longer matches is the
  confirmation's to say, not the tray's to refuse.
  The cost of the mode: after #718 a single-row bulk act is three
  presses, Select, the checkbox, the action, one more than the charter
  counted; the row's own Edit and Reset stay two, the ⋯ menu and the item.
- Below `md` the identity cell is today a shrinkable, single-line name cell,
  and nothing stacks. #711 builds the stacked cell: the checkbox beside the
  row's essential summary on two lines, while lower-priority columns keep
  dropping as `<responsive-table>` decides. This is #716's whole substance:
  the mobile organizer is the table's own personality, not a second screen.
- Keyboard: Space toggles the focused checkbox, Shift+Space extends from the
  last toggled row, Shift+click on a checkbox takes a range, the footer's
  check-all is a tri-state control, and the
  element announces the count through one live region it owns, because it
  owns the selection; the tray shows the same count and announces nothing.
  The contract is verified with Orca in #718, on the finished pages.
- Selection needs scripting. The server renders no checkbox and the footer
  renders its selection line hidden until the element connects, so a page
  with scripting off shows the table it shows today. The runner reads one shape, the selection
  statement below; a second, one-field-per-row shape for scripting off was
  rejected, because it doubles the runner's grammar for a reader that also
  never sees the selection line. After #718 such a reader has no per-row act either,
  and that is the accepted cost.

The selection travels as the **selection statement**: one hidden field
holding a JSON list of row keys, or `all` beside the list's filter JSON,
the count seen and the keys unchecked since, so an "all matching" selection
records exclusions rather than falling back to keys. It is always POSTed,
because a page of keys does not fit a URL. The confirmation resolves it
under the library into the keys the person saw, the exclusions taken out, at the instant the confirmation rendered, and from then on
the act names those keys and no others: a row gone by the act is counted
lost, never converted; a row that entered the filter after the confirmation
rendered is never touched.

One field, not one per row, is what closes #1125 with no settings change:
Django's cap counts fields, and 2,817 keys is 100 KB against a body limit of
2.5 MB. Acting on the filter and a count was considered and rejected,
because a row swapped for another between confirmation and act passes the
count and gets acted on unseen, and the act stops meaning "these rows".

## The tray

The tray is the footer's selection line, not a surface of its own. While
the mode is on the line is sticky to the viewport's bottom inside the
table's shell, so it takes its own height in the flow and nothing reserves
for it, and it stops sticking once the table has scrolled past. The shell's
`overflow-hidden` would make the shell the sticky containing block, so it
becomes `overflow-clip`, which clips the corners the same and is no scroll
container. The line sits under the menu stratum (`z-20`), so an actions
menu opens over it, and under the toasts (`z-50`). The toast stack is
fixed to the same bottom edge, so the element publishes the line's height
as `--selection-line` on the root while the mode is on, the tallest line
any connected table shows, and the stack reads it in its own classes for
its bottom offset. The version stamp is a
`<footer>` in the flow on every page's last line, moved out of the fixed
corner by #711, so nothing sticky covers it.
`StyledTable`'s footer slot holds one region today and refuses a second;
#711 makes it a composite the table builds: the selection line above the
pagination row, either alone, so a table with no pagination, Game detail's
playthroughs and records, gets the selection half by itself. #711 ships the
line with the count and scope, check-all, "Select all N matching" and Clear,
and an empty actions slot; #712 fills the slot with the actions the table's
view declares.

A `BulkAction` is a declaration, not a view: label, the confirmation
route, the per-row command, its inverse, and the aggregate the inverse
takes. One batch can append events under two aggregates: the
reclassification mints a record beside each session it marks, so its Undo
reads the batch's session events and not its record events. The tray
offers an action while at least one row is selected, and every action is
a `many` act: it POSTs the selection statement to its confirmation route
with the origin, so the act returns where the person stands (`?origin=`,
as every mutating link). The wave first planned a `one` cardinality, a
link to the row's own page offered while exactly one row was selected,
for Edit, Reset and Was-an-estimate. The user overturned it on the
shipped tray: no act in the Actions column must be single, because bulk
Edit is a different act from the row's Edit (it sets one value on every
selected row, #1211) and Finish is coherent over many running sessions.
What stays single, the row's own Edit form and Reset, lives in a ⋯ menu
on the row, not in the tray, so the tray renders no `one` path and
`Cardinality.ONE` leaves with #718.

The selection line is the same on every table, and the actions differ by
view. Nothing about it knows sessions.

## The runner

Every `many` action runs through one server-side runner,
`games/views/bulk.py`. It is a new flow, not a generalisation of
`confirm_and_apply`, whose one shape is "GET confirms, POST acts": the
runner's confirmation arrives by POST, so it tells its two POSTs apart by
the submission token.

1. **Confirm.** A POST without a token resolves the selection statement
   under the library and renders one `ConfirmPage` that leads with the act,
   its count and its scope, lists the rows to a cap, lists every refusal
   the resolve owns (a key outside the act's scope, a row the act already
   covered) with its reason in full, and carries a fresh token beside the
   resolved keys. An act that asks for a fact (#714's target run, #1211's
   value) declares a choice: its controls are built from the offered rows
   and may refuse the whole act there (a selection spanning games), its
   value settles once at the confirmation press, before the first chunk,
   into one runner-named hidden field beside the token, and `run` takes it
   as one string. The settle validates and writes nothing: a run the
   person needs is created ahead of the submit by #1080's create row, in
   its own request under its own correlation id, outside the batch, so no
   Undo can name it. A command's rule (a
   running session, a bucket, a last live run, a run a live session
   names) is read at the press, per row, under the lock, and the
   confirmation does not restate it; a forecast that imports the
   command's predicates to fill the "left as they are" block is #1209,
   parked until the interface is rethought after #599's epics. Today's review
   confirmation lists every row; an `all` statement over the session list
   resolves to thousands, which is megabytes on the page that exists to be
   read, so the cap is the accepted trade. The runner parses an `all` statement's filter itself and refuses
   one it cannot parse, with a sentence and no act. It does not reuse
   `apply_structured_filter`, which drops an invalid filter and renders
   the list unfiltered: harmless on a list page, and on a bulk act the
   scope widened to every row.
2. **Act.** A POST with a token dispatches the action's per-row command
   through the row's `games/writes/` wrapper, under `answered()`, one
   transaction per row as every dispatch is, each row's idempotency key
   derived from the token and the row key, every row under **one
   `correlation_id`**, which is the batch's identity. The token is that
   correlation id: it is minted once at the confirmation and resubmitted
   by every chunk, so a batch of two requests has one id and its Undo
   finds all of it. A refusal names its
   row and its sentence, and the next row runs. A **chunk** is the rows one
   request acts on inside a time budget of a few seconds; it is not a
   transaction. The budget is the runner's constant, `CHUNK_BUDGET` of
   three seconds. `make bench` measured a reclassification row at 9.1 ms
   at p95, the resolve and the dispatch together, so a chunk holds about
   300 rows; a move is one event a row against the reclassification's two,
   so it holds more. "Select all N matching" on the session list is about
   ten requests, so the progress page is the ordinary sight there.
3. **Continue.** Rows left when the budget is spent render a progress page
   that resubmits the token and the remaining keys with scripting off, and
   auto-submits with it on. Every real population above fits one request;
   "all matching" on the session list is the one that may not.
4. **Answer.** One toast counting done, unchanged, refused and lost, with
   the batch Undo, on the origin page.

A defect in one row's command is `answered()`'s: the batch ends there, as
the reclassification ends today and as `confirm_and_apply` admits no second
press after one, the rows already done stay done because each committed on
its own, and the toast says how many. The progress page does not follow a
defect.

The runner's route and the batch Undo's are classified `ORIGIN_AWARE` in
`games/views/returns.py`, as every restore route is: each is a POST that
acts and then redirects to the origin it carried. `CONFIRMATION` stays the GET-only bucket, and
`IN_PLACE` the partial swap that leaves the person where they are;
neither describes a route that acts on POST and leaves the page.
An overlay either page closes on Escape marks the press spent, as the
menus, tooltip, date pickers and toast stack do, because the selectable
table decides its own Escape in the task after the press.

### Batch Undo

One POST route keyed on the batch's `correlation_id`. The runner reads the
batch's events, applies the action's inverse to each row, and runs that as a
batch itself: chunked the same way, under its own correlation id, with its
own toast. A row whose inverse is refused, because its record was restated
since or its run removed, is named in the report and does not block the
rest. All-or-nothing was considered and rejected: one restated record would
leave 92 rows stuck, which is #1123's own complaint.

The inverses: reclassify → `UndoSessionReclassification`; remove → the
row's restore command; move → `MoveSessionToPlaythrough` back to the run
the session named before the batch. The move event carries its target only,
and the run before is the target of the session's latest earlier `moved`
event, or of its `created` payload. Reading that is new: nothing today reads
events by aggregate, and `aggregate_id` is unindexed. #713 adds one
migration with two indexes, `(library, correlation_id)` and
`(library, aggregate_id)`, and the one reader its own Undo calls, the
batch's events by `(library, correlation_id)`. The aggregate reader,
`aggregate_events(library, aggregate_id)`, lands in #714 beside the move
inverse, the only caller it has, so #713 merges no reader nothing runs.
The event's shape does not change and no column is added to the row.

The Undo is offered on the act's toast, as every removal's is (#695), through
`UndoOffer`, whose route takes the correlation id. The removal helper's
`restore_and_return` answers one command's result; the batch's undo answers
counts, so it has its own returner in `bulk.py`. A durable place to reach a
batch after its toast closes is the Trash's (#795), which inherits "recent
batches".

### Bulk Remove

"Remove N selected" is the action every selectable table declares. Its
per-row command is the row's own (`RemoveSession`, `RemovePlaythrough`,
`RemoveHistoricalPlaytime`) and its inverse the restore. The confirmation
summarises the scope, as the charter asks of a destructive act. It is added
because it is the one action valid on every table, its inverse is trivial,
and it proves the runner and the partial report on rows whose commands refuse
for their own reasons: `RemovePlaythrough`'s last-live-run and referrer
refusals surface per row here first. Measured on the anonymized
production sample after #712: of one library's 867 live ordinary runs,
852 are the sole run of their game and 722 are named by a live session,
so three are removable, and a batch of fifty runs answers "0 of 50
done". Sessions and records refuse far less. The act stays as the
runner's proof and the one act on the run tables; whether it earns a
place in the product is judged in the rethink #1209 is parked against,
not here. Without it a tray on runs or records
would hold single-row acts only, and selecting ten runs would enable
nothing.

## The organizer

The organizer is the Playtime page's session list narrowed to one game.
Game detail's Sessions section keeps its five-row preview and gains
"Organize" beside "view all"; both land on the list with `game` applied.
That list already has every column, the filter, the sort, presets and, after
#712, the tray. No new route, no second list, no rebuild of the preview.
From it a person:

- sorts by playthrough: #715 adds a Playthrough column, shown while the
  filter names one game, and a sort on it, the bucket sorting last under its
  own name, because `DISPLAY_ORDER` numbers ordinary runs only and the
  bucket has no number. `StyledTable` has no group-header rows and the
  column-drop classes address cells by position, so grouping is the column
  and the sort, not header rows;
- narrows by date and device, the session filter's own facets;
- selects rows and moves them: "Move to playthrough…" opens a confirmation
  hosting one `SearchSelect` with `create_url` (#1080, a prerequisite)
  over the game's live ordinary runs, no name field and no second
  control; a name typed there goes through `POST /api/playthrough/` ahead
  of the submit, so the choice is always an existing run key. That POST
  runs `RecordPlaythroughByName`, which names the game's placeholder (its
  sole live ordinary run, blank, never acted on, nothing naming it) rather
  than creating a second run beside it, and creates one otherwise. The
  Undo moves each session back, restoring the bucket first, and the run
  named or created ahead stays, which the answer says: the batch never
  wrote it. An abandoned confirmation leaves such a run, the cost #1080
  accepts by name;
- sees the session's day, duration, device and note in the row before
  moving it, as the charter asks. #714's confirmation lists rows to
  `CONFIRMATION_SAMPLE`, fifty, in five columns: Playthrough, through
  `run_labels_for` in `games/views/session.py`, the bucket included, then
  Day, Duration, Device and Note. No Game column, since the cross-game
  refusal fixes the game.

The action is declared on the session list whether or not the filter names
a game. A selection spanning games is refused at the confirmation with a
sentence naming the game count, rather than offered a two-step picker. The
charter's "select a date range" is the date facet followed by "Select all N
matching".

### The bucket

The bucket takes no new session and a move is the only way out (#702). When
the last session leaves it, the move's command sequence removes the bucket
under the same correlation id through `RemovePlaythrough`: its last-live-run
rule reads ordinary runs only, and its referrer check finds nothing, because
no session names the bucket any more and `RecordHistoricalPlaytime` refuses
the bucket, so no record ever did. The Library page's Playtime section
counts sessions in the bucket and links to the organizer when the count is
not zero. The charter says "archive the empty bucket"; the word here is
remove, as [Vocabulary](../../vocabulary.md) settles it.

### The question the sole-run rule never asked

`PlayerSessionFilter` gains `outside_playthrough_dates`, a boolean over
`effective_day` against the run's `started_lower` and `completed_upper`:
true where the day lies before the start or after the completion of a run
that states both. It is a handler-backed field with no column of its own,
the `is_running` pattern, and a quick facet of kind `bool`. The Library
page's count names it beside the bucket: "113 sessions fall outside their
playthrough's dates". No stored state: the facet is the suggestion, and a
row the person leaves is right where it is.

## Reclassification, rebuilt

#1098's confirmation becomes the runner's first consumer, in #713. The
Library page's "Move all N" button posts an `all` statement over the review
facet; the confirmation, chunks, token and Undo are the runner's, and the
page's copy, which today says moving all at once offers no Undo, starts
promising one. Once the tray ships (#712) the act moves there: the Playtime
list with the review facet applied selects "all N matching" and acts from
the tray. The Library page keeps the count and the link to the review and
loses the button.

## Retiring Actions columns

#718 retires the Actions column on every table on the two pages this wave
touches that has one: Game detail's playthroughs and historical playtime,
and the Playtime page's sessions and historical playtime, four columns.
Game detail's session preview has none. Every act that is coherent over
many rows is a tray action: Remove and Was-an-estimate (shipped), Finish
(#718 declares it, `EndSession` at now per running row, no form), and
Edit as set-one-value (#1211, after #714, whose move confirmation is the
form-over-a-selection precedent; its device control is the session
form's creating `SearchSelect` over `POST /api/devices/`, #1080's, so a
device the library does not hold yet is made at the confirmation). The
residue, the row's own Edit form
and Reset, moves into a ⋯ menu on the row, the user's preference over a
row of icons; a single running session is finished from the tray, from
the navbar, or from its own page. Games, Purchases,
Devices and Platforms keep their columns, each filed as a follow-up;
Purchases' is the Purchases wave's, which rebuilds that table.

The cost the charter accepted holds: a single-row bulk act is select,
then act, one press more than an icon, and the residue menu costs the
same two presses an icon row did. The Orca pass in #718 is where that
cost is judged.

## Delivery order

1. **#711** TABLE-01 — `<selectable-table>`: the Select toggle, the footer
   composite with the selection line's count, check-all, all-matching and
   Clear beside the pagination row, the checkbox in the identity cell, the
   selection statement, the keyboard contract, the stacked identity cell
   below `md`. Proven on a synthetic e2e page; nothing on `main` uses it
   yet. Absorbs #716.
2. **#713** TABLE-03 — the runner: `BulkAction`, the confirmation and
   progress pages, token and chunks, the two indexes and the batch
   reader, batch Undo with the partial report, the bulk `make bench`; the
   reclassification rebuilt on it, reached from today's Library button.
   Closes #1125 and #1123.
3. **#712** TABLE-02 — the selection line's actions slot and bulk Remove on
   the four tables and on the Playthrough list, which shares the run
   builder and its act and is the run table with a paginator; `many`
   actions only, the `one` link path landing with #718's actions; the
   reclassification moves into the line and the Library page keeps its
   count. The confirmation's row renderer becomes
   the act's and `BulkAction` generic over its row type, because
   `_sample` in `games/views/bulk_pages.py` renders session columns only,
   so no act on runs, records or platforms ships before it.
4. **#714** ORG-01 — bulk move, after #1080: the confirmation with
   #1080's creating `SearchSelect` over the game's runs, the bucket removed
   when emptied, cross-game selections refused, the aggregate reader
   beside the move inverse over the `(library, aggregate_id)` index #713
   shipped, and the confirmation's five columns.
5. **#715** ORG-02 — the organizer: the Playthrough column and sort on the
   session list, Game detail's "Organize" link, the mobile cell verified on
   the list. Absorbs #716.
6. **#717** ORG-04 — `outside_playthrough_dates`, the Library page's two
   counts and their links.
7. **#1212** TABLE-05 — the checkbox reserve while the mode is off,
   decided before the pages are judged.
8. **#718** ORG-05 — the four Actions columns retired into the tray's
   `many` acts (Finish declared here) and the row's ⋯ menu,
   `Cardinality.ONE` removed, the Orca pass.
9. **#1211** TABLE-04 — bulk Edit on the session tables, after #714.

`#711 → #713 → #712 → #714 → #715 → #717 → #1212 → #718 → #1211`. #713 needs no table, so it
runs beside #711. One prerequisite lies outside the wave: #1080, in the
Session wave, landed before #714 as stack #1226–#1228 (`main` at
63b5940f). Every issue merges alone and leaves `main` incomplete
rather than inconsistent: #711 a personality nothing uses, #713 a runner one
page uses, #712 a tray beside Actions columns it will replace. No stack.

Merged: #716 into #711 and #715. Closed by #713: #1123, #1125. Added: bulk
Remove, in #712.

## Cross-wave handoffs

- **The lists that stay** — Games (#1134), Devices (#1135) and Platforms
  (#1136) each inherit the personality and the retirement of their column
  after #718; Purchases' table is #725–#736's.
- **The Trash** — #795 inherits "recent batches": the batch's correlation id
  and the Undo route are what a Trash lists, and the correlation index is
  what it reads.
- **The union list** — #1100 inherits the selection statement and the tray;
  a row on the union declares its kind, and the action's per-row command
  reads it.
- **Import** — #798's inbox is a selectable table with bulk actions by
  construction; it inherits the runner.
- **Audit History** — the aggregate reader is the first per-aggregate read
  of the stream, which the Journal and the Trash both need.
- **The creating combobox** — #1080, in the Session wave, landed as
  #714's prerequisite: the move confirmation is its fourth consumer, and
  #1211's device control its fifth. Its picker is always visible and its
  create row names a placeholder run rather than doubling it, which #714's
  Undo sentence and #715's Playthrough column both inherit.
- **The rethink** — #1209, a confirmation that forecasts a command's
  refusal, waits for the interface work after #599's epics, which also
  judges whether bulk Remove on runs is kept at all.

## Verification contract

- The selectable table's keyboard contract is proven by e2e on the synthetic
  page and by an Orca transcript on the session list before #718 closes.
- The runner is proven by the reclassification and by bulk Remove: a batch
  of more than one chunk, an act after a row was removed (counted lost), a
  repeated POST of one token (idempotent, same counts), a row whose command
  refuses (named, the rest done), a defect (the batch ends, done rows stay).
  The runner's e2e cover drives the selection line's action from #712 on,
  since the Library button it drove until then is gone.
- Batch Undo is proven on each inverse: reclassify, remove, move; a move
  undone to the run the `created` payload named and to one an earlier
  `moved` named; a batch one of whose rows was restated since (named, the
  rest undone).
- A move of every session out of the bucket removes the bucket under the
  batch's correlation id; the Playthrough column shows no bucket after.
- `outside_playthrough_dates` answers 113 on the 2026-09-19 dump, the Elden
  Ring run 32.
- `make bench` times one bulk of 600 sessions through the runner against the
  100 ms per-command budget at p95, and records the rows written. #713
  ships it, because the chunk budget is the runner's constant and a
  constant nobody measured is a guess; the seeder extends
  `games/events/benchmark_workload.py`, which already dispatches 600
  records. That the reclassification's real population fits one chunk is
  why the bench, not production, is where the second chunk is first seen.
- `render_pages` before and after #718, every differing file attributed.
- Full `make check` green at every merged commit.

## What was applied

Merged: #716 into #711 and #715.

Pulled in: #1123 and #1125, closed by #713.

Added: bulk Remove as every table's action, in #712.

Reordered: #713 ahead of #712, because the tray's first action needs the
runner; #717 after #715, because its facet reads the organizer.

Amended in the charter's assumptions, on the evidence of the production
copy: the ambiguous population is one row, and the organizer's work is the
sole-run assignments the conversion made by rule, which the new facet
surfaces.

Corrected by the review of the first draft: the organizer is the session
list narrowed to a game, not Game detail's preview, which is five rows with
no note, no sort and no Actions column; a chunk is a budget of per-row
transactions, not one transaction; a defect ends the batch; the
confirmation is a two-POST flow the removal helper does not model; the move
inverse needs an aggregate reader and a second index; the stacked cell is
built, not inherited; run grouping is a column, not header rows; the
Library copy starts promising an Undo rather than stopping.

Amended after #711's planning: selection is a mode a footer toggle opens,
with no header checkbox, and the tray is the footer's selection line, so
the footer composite and the line's furniture moved from #712 into #711;
the live region is the element's; selection needs scripting; an "all
matching" selection records exclusions. Corrected by the review of #711's
spec: the element builds the checkboxes from a row key the server renders,
rather than revealing hidden ones, so the row builder stays unaware; no
all-matching control without a paginator; the sticky line needs the shell
to clip rather than hide, verified in a browser. Changed by #711's review
against the rendered table: a selection outlives the page as a stored
statement, two Select toggles bracket the table, every checkbox is built
at connect, and the version stamp left the fixed corner. Corrected by
#713's planning against the route table: the runner and the batch Undo are
`ORIGIN_AWARE`, the aggregate reader moved to #714 with its one caller, and
the runner refuses a filter it cannot parse rather than acting unfiltered.
Corrected by the review of #713's spec: the confirmation lists rows to a
cap, the token is the correlation id, and a `BulkAction` names the
aggregate its inverse takes. Recorded after #713 merged: a chunk is about
300 reclassification rows at 9.1 ms a row; the row renderer and
`BulkAction`'s row type are #712's; #714 writes the aggregate reader over
an index that exists and judges the confirmation's cap and columns.
Settled by #712's planning: the Playthrough list is selectable beside the
four tables, `one` actions render first in #718, and the confirmation's
rows are a columns spec the act declares. Found by #712's review in
#711's element: the slot latches the statement at the press and pulls it
at connect. Measured after #712 shipped: the confirmation lists only the
refusals the resolve owns, a command's rule is read at the press, and the
forecast of it is #1209, parked with the numbers. Overturned by the user
on the shipped tray: no `one` cardinality; bulk Edit (#1211) and Finish
are `many` acts, the residue is a ⋯ menu on the row, and the empty
checkbox reserve is #1212's to decide before #718.

Deviations recorded: the empty bucket is removed, not archived; Finish is
a tray act rather than the charter's inline control, beside the navbar's;
a cross-game move is refused rather than
picked; the organizer is reached from Game detail's Sessions section rather
than its Playthrough section, and a date range is selected through the date
facet and "all matching".
