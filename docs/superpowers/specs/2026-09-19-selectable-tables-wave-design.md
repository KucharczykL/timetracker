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
2026-09-19, migrated to `0011`, and against the code.

## Product boundary

A person selects rows of a table and acts on the selection: removes them,
moves sessions to a playthrough, turns written-down sessions into historical
playtime records. The act runs as one batch the person can undo as one. Game
detail's session table, made selectable, is the organizer the charter
describes.

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
  a batch converted before this wave ships is reachable by the Undo it adds.

#1100 waits behind this wave, as filed. #481, #520 and #521 touch the same
table and stay outside.

## Selection

`StyledTable` gains a selectable personality, a custom element
`<selectable-table>` wrapping the scroll region beside `<responsive-table>`,
which keeps owning column dropping. The charter's rules hold, and this wave
settles the shape:

- The checkbox sits inside the pinned identity cell, first in reading order,
  so the cell stays the row's `<th scope="row">` and keeps its stack and
  shadow behaviour. Only the checkbox selects; the row's links and immediate
  controls keep their own meaning.
- The header checkbox selects the page. On a filtered list it is followed by
  "Select all N matching", N read from the paginator, which the tray shows
  as the selection's scope. Game detail's tables hold no filter and no
  paginator, so their page is their whole.
- Selection lives in the page and nowhere else. Navigating a page clears it.
  A selection that must outlive a page is the "all matching" statement.
- On a narrow screen the identity cell stacks the checkbox beside the row's
  essential summary, and the lower-priority columns keep dropping as
  `<responsive-table>` decides. This is #716's whole substance: the mobile
  organizer is the table's own personality, not a second screen.
- Keyboard: Space toggles the focused checkbox, Shift+Space extends from the
  last toggled row, the header checkbox is a tri-state control, and the tray
  announces the count through a live region. The contract is verified with
  Orca in #718, on the finished pages.

The selection travels as the **selection statement**: one hidden field
holding a JSON list of row keys, beside a submission token. A page selection
is its keys. "All matching" is resolved by the confirmation's GET, under the
list's filter, into the same list: the keys the person saw, at the instant
the confirmation rendered. A row gone by POST is counted lost, never
converted; a row that entered the filter after GET is never touched.

One field, not one per row, is what closes #1125 with no settings change:
Django's cap counts fields, and 2,817 keys is 100 KB against a body limit of
2.5 MB. Posting the filter and a count was considered and rejected, because a
row swapped for another between GET and POST passes the count and gets acted
on unseen, and the act stops meaning "these rows".

## The tray

One `<selection-tray>` per selectable table, rendered by the server beneath
the table and shown by the element once a row is selected: the selected count
and scope, a Clear control, and the actions the table's view declares.

A `BulkAction` is a declaration, not a view: label, allowed cardinality
(`one`, `many`), the confirmation route, and, for a `many` action, the
per-row command and its inverse. The tray offers a `one` action while exactly
one row is selected and a `many` action while at least one is. An action's
POST is the selection statement to its confirmation route, plus the origin,
so the act returns where the person stands (`?origin=`, as every mutating
link).

`one` actions are today's row actions: Edit links to the row's edit page,
Reset and Was-an-estimate to their pages. Finish stays in the row: a running
session is finished where it runs, the charter's named immediate control,
beside the game-status selector.

The tray is the same element on every table, and the actions differ by view.
Nothing about the tray knows sessions.

## The runner

Every `many` action runs through one server-side runner,
`games/views/bulk.py`, which is today's `reclassify_reviewed_sessions`
generalised:

1. GET resolves the selection statement under the library, lists the rows,
   and renders one `ConfirmPage` naming the act, its count, and what will be
   refused (a running session, a bucket, a last live run) with the reason.
2. POST reads the statement and token, then dispatches the action's per-row
   command in chunks: each chunk one `run_in_transaction`, each row's
   idempotency key derived from the token and the row key, every row under
   **one `correlation_id`**, which is the batch's identity. The chunk size
   and a time budget of a few seconds are the runner's constants,
   measured by `make bench`.
3. Rows left when the budget is spent render a progress page that
   resubmits the token and the remaining keys with scripting off, and
   auto-submits with it on. The budget makes this page rare: no population
   above reaches it but "all matching" on the session list.
4. The answer is one toast counting done, unchanged, refused and lost, with
   the batch Undo. A refusal names its row and its sentence in the
   confirmation's log, and the count in the toast.

No dispatch inside a transaction the view opens, so the runner opens none:
`run_in_transaction` is the chunk. A defect in one row's command is
`answered()`'s, as today, and stops the chunk, not the batch: the progress
page offers the rest.

### Batch Undo

One POST route keyed on the batch's `correlation_id`. The runner reads the
batch's events, applies the action's inverse to each row, and runs that as a
batch itself: chunked, under its own correlation id, with its own toast. A
row whose inverse is refused, because its record was restated since or its
run removed, is named in the report and does not block the rest.
All-or-nothing was considered and rejected: one restated record would leave
92 rows stuck, which is #1123's own complaint.

The inverses: reclassify → `UndoSessionReclassification`; remove → the
row's restore command; move → `MoveSessionToPlaythrough` back to the run
the session's own events named before the batch, read off its stream. The
move event keeps its shape, and no column is added.

Reading a batch needs one migration: an index on `(library, correlation_id)`
on the event table, which nothing today indexes.

The Undo is offered on the act's toast, as every removal's is (#695). A
durable place to reach a batch later is the Trash's (#795), which inherits
"recent batches".

### Bulk Remove

"Remove N selected" is the action every selectable table declares. Its
per-row command is the row's own (`RemoveSession`, `RemovePlaythrough`,
`RemoveHistoricalPlaytime`) and its inverse the restore. The confirmation
summarises the scope, as the charter asks of a destructive act. It is added
because it is the one action valid on every table, its inverse is trivial,
and it proves the runner and the partial report on rows whose commands refuse
for their own reasons: `RemovePlaythrough`'s last-live-run and referrer
refusals surface per row here first. Without it a tray on runs or records
would hold single-row acts only, and selecting ten runs would enable
nothing.

## The organizer

The organizer is Game detail's session table made selectable. No new route,
no second list. From it a person:

- sorts by run, which groups the sessions under header rows naming each
  run, the bucket last;
- narrows by date and device, the session filter's own facets;
- selects rows and moves them: "Move to playthrough…" opens a confirmation
  hosting `<playthrough-select>` over the game's live ordinary runs and a
  "new playthrough" name field; naming a new one creates it first, then
  moves, under one correlation id;
- sees the session's day, duration, device and note in the row before
  moving it, as the charter asks.

The Playtime page's session list declares the same action, because the tray
is shared. A selection there may span games; the action refuses one with a
sentence naming the game count, rather than offering a two-step picker.

### The bucket

The bucket takes no new session and a move is the only way out (#702). When
the last session leaves it, the move's command sequence removes the bucket
under the same correlation id, through `RemovePlaythrough`, whose last-live-run
rule does not apply to a bucket. The Library page's Playtime section counts
sessions in the bucket and links to the organizer sorted by run when the
count is not zero. The charter says "archive the empty bucket"; the word
here is remove, as [Vocabulary](../../vocabulary.md) settles it.

### The question the sole-run rule never asked

`PlayerSessionFilter` gains `outside_playthrough_dates`, a boolean over
`effective_day` against the run's `started_lower` and `completed_upper`:
true where the day lies before the start or after the completion of a run
that states both. It is a quick facet on the session list and a sort on Game
detail, and the Library page's count names it beside the bucket: "113
sessions fall outside their playthrough's dates". No stored state: the facet
is the suggestion, and a row the person leaves is right where it is.

## Reclassification, rebuilt

#1098's confirmation becomes the runner's first consumer, in #713. The
review's "Move all N" posts the review facet's resolved keys as one selection
statement; the confirm page, chunks, token and Undo are the runner's. Once
the tray ships (#712) the act moves there: the Playtime list with the review
facet applied selects "all N matching" and acts from the tray. The Library
page keeps the count and the link to the review, loses the button, and its
copy stops promising an Undo it does not offer until #713, when it offers
one.

## Retiring Actions columns

#718 retires the Actions column on every table on the two pages this wave
touches: Game detail's sessions, playthroughs and historical playtime, and
the Playtime page's sessions and historical playtime. Edit, Remove, Reset and
Was-an-estimate become tray actions; Finish stays inline. Games, Purchases,
Devices and Platforms keep their columns, each filed as a follow-up;
Purchases' is the Purchases wave's, which rebuilds that table.

The cost the charter accepted holds: a single-row act is select, then act,
one press more than an icon. The Orca pass in #718 is where that cost is
judged.

## Delivery order

1. **#711** TABLE-01 — `<selectable-table>`: the checkbox in the identity
   cell, page and all-matching selection, the selection statement, the
   keyboard contract, the stacked identity cell. Proven on a synthetic e2e
   page; nothing on `main` uses it yet. Absorbs #716.
2. **#713** TABLE-03 — the runner: `BulkAction`, the confirmation and
   progress pages, chunks and token, the correlation index, batch Undo with
   the partial report; the reclassification rebuilt on it, reached from
   today's Library button. Closes #1125 and #1123.
3. **#712** TABLE-02 — `<selection-tray>` and bulk Remove on the five
   tables; the reclassification moves into the tray and the Library page
   keeps its count.
4. **#714** ORG-01 — bulk move: the confirmation with `<playthrough-select>`
   and the new-run field, the bucket removed when emptied, cross-game
   selections refused.
5. **#715** ORG-02 — Game detail's session table selectable, the run sort
   with header rows, the mobile cell verified there. Absorbs #716.
6. **#717** ORG-04 — `outside_playthrough_dates`, the Library page's two
   counts and their links.
7. **#718** ORG-05 — the five Actions columns retired, the Orca pass.

`#711 → #713 → #712 → #714 → #715 → #717 → #718`. #713 needs no table, so it
runs beside #711. Every issue merges alone and leaves `main` incomplete
rather than inconsistent: #711 a personality nothing uses, #713 a runner one
page uses, #712 a tray beside Actions columns it will replace. No stack.

Merged: #716 into #711 and #715. Closed by #713: #1123, #1125. Added: bulk
Remove, in #712.

## Cross-wave handoffs

- **The lists that stay** — Games, Devices and Platforms each get a
  follow-up issue for the personality and the retirement of their column;
  Purchases' table is #725–#736's.
- **The Trash** — #795 inherits "recent batches": the batch's correlation id
  and the Undo route are what a Trash lists.
- **The union list** — #1100 inherits the selection statement and the tray;
  a row on the union declares its kind, and the action's per-row command
  reads it.
- **Import** — #798's inbox is a selectable table with bulk actions by
  construction; it inherits the runner.

## Verification contract

- The selectable table's keyboard contract is proven by e2e on the synthetic
  page and by an Orca transcript on Game detail before #718 closes.
- The runner is proven by the reclassification and by bulk Remove: a batch
  of more than one chunk, a POST after a row was removed (counted lost), a
  repeated POST of one token (idempotent, same counts), a row whose command
  refuses (named, the rest done).
- Batch Undo is proven on each inverse: reclassify, remove, move; and on a
  batch one of whose rows was restated since (named, the rest undone).
- A move of every session out of the bucket removes the bucket under the
  batch's correlation id; the run sort shows no bucket after.
- `outside_playthrough_dates` answers 113 on the 2026-09-19 dump, the Elden
  Ring run 32.
- `make bench` times one bulk of 600 sessions through the runner against the
  100 ms per-command budget, and records the rows written per chunk.
- `render_pages` before and after #718, every differing file attributed.
- Full `make check` green at every merged commit.

## What was applied

Merged: #716 into #711 and #715.

Pulled in: #1123 and #1125, closed by #713.

Added: bulk Remove as every table's action, in #712.

Reordered: #713 ahead of #712, because the tray's first action needs the
runner; #717 after #715, because its facet is a sort on the organizer.

Amended in the charter's assumptions, on the evidence of the production
copy: the ambiguous population is one row, and the organizer's work is the
sole-run assignments the conversion made by rule, which the new facet
surfaces.

Deviation recorded: the empty bucket is removed, not archived; Finish stays
inline as an immediate control; a cross-game move is refused rather than
picked.
