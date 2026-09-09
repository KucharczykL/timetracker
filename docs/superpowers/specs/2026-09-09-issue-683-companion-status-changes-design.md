# Offer a status change beside a lifecycle act

A person who records a run usually means something by it. The first start of a
game means the game is Played. A completion means it is Completed. This issue
offers that second statement beside the first one, checked where it is right
and unchecked where it is not, and appends both under one `correlation_id`.

Nothing is inferred. Every status event this issue appends is one a person
asked for, by leaving a box ticked or by pressing a button that says what it
does.

## What already ships

`PlaythroughForm` carries `mark_as_finished`, and both hosting views read it:
`add_playthrough` and `edit_playthrough` call `_record_completed` under the
submit's own `correlation_id`. That is the plumbing this issue was waiting for,
and its docstring names this issue as the owner of the rest.

Three things about it are wrong today:

1. the label reads `Set game status to Finished`, and the word is `Completed`
   since #672;
2. it fires whether or not the submit states a completion, so a run recorded
   with no finish day still states the status;
3. `initial={"mark_as_finished": True}` gives a `BooleanField` a dict. The
   value is truthy, so the box renders checked by accident rather than by
   declaration.

## The status is the strongest thing stated

A game completed once is Completed. A second run does not walk that back.

| the person states | the status | why |
|---|---|---|
| a first start on an Unplayed game | Played | the game was never played, and now it was |
| a completion | Completed | the objective was reached |
| a start on a game already Played or stronger | unchanged | nothing new is true of the game |

`Played` is therefore offered only where the status is `Unplayed`. On every
other status the box does not render: a game that is Completed, Retired,
Shelved or Abandoned learns nothing from a start, and a checked box there would
demote it.

`Completed` is offered wherever the submit states a completion, whatever the
status is. Where the status already reads Completed,
`RecordPlayerGameFacts` answers `Unchanged` and no event is appended.

Retired, Shelved and Abandoned are never offered beside an act. Each is a
judgement about the game that no run implies, and the compact status selector
states them directly, as the charter requires.

## The two boxes

`PlaythroughForm` carries two fields in place of `mark_as_finished`:

| field | label | rendered when | checked when |
|---|---|---|---|
| `also_mark_played` | Also mark this game Played | the status is `Unplayed` | always, when rendered |
| `also_mark_completed` | Also mark this game Completed | always | always |

Each acts only where the submit states the matching act. `also_mark_played`
states nothing where the draft states no start; `also_mark_completed` states
nothing where the draft states no completion. A box the form did not render
states nothing, whatever a posted body claims.

The form needs the current status to decide what to render. It reads the
`PlayerGame` row of the game it is bound to, through
`games/reads/playthrough_runs.py`, which the view already imports. A game the
library does not track yet has no status, so both boxes render and both are
checked: recording a run tracks the game, and a game tracked by this submit was
Unplayed a moment ago.

## The per-run acts

The Playthroughs section on Game detail renders one row for each live ordinary
run, with Edit and Remove. Each row gains the act its state allows, ahead of
those two:

| the run states | the action | what it appends |
|---|---|---|
| no start | Start | `library.playthrough.started`, today, plus Played where the status is Unplayed |
| a start, no completion | Complete | `library.playthrough.completed`, today, plus Completed |
| both | none | nothing is left to state |

Both actions state today's day. A day that is not today belongs in the edit
form, which holds every precision the grammar knows.

Both are POST routes, because they change state, and both are one press with
no confirmation: each is reversible through the correction commands #1010
shipped. Each redirects to its origin when it is done, so both classify as
`ORIGIN_AWARE` in `games/views/returns.py`. `IN_PLACE` is the bucket for a
route that answers with a partial swap, and neither of these does.

`RecordPlayerGameFacts` answers `Unchanged` where the status already holds, so
the companion is silent rather than refused on a game that needs no change.

## One human act, two dispatches

Each surface appends its lifecycle event and its status event under one
`correlation_id`, through two dispatches rather than one command.

`record_run` is already one to three dispatches, because a restatement states
each endpoint separately and each absorbs its own `Unchanged`. A command
appending both events would have to replace that whole path, and it could not
serve the form at all. The correlated pair is what the shipped code does, and
what `_record_completed` was written for.

The cost is stated rather than hidden: `run_in_transaction` refuses to nest, so
the two commits are separate. A refused status after a committed run leaves the
run recorded and the status not, and the refusal toasts. The person presses the
button again, or sets the status in the selector. No screen shows a half state.

No reader groups events by `correlation_id` yet. The grouping is a fact of the
stream that the Journal will read; this issue writes it correctly and renders
nothing from it.

## What this issue does not do

The compact status selector is untouched. The charter describes an optional
action beside it, and this issue puts that action on the run instead: the
selector's line is a metadata row, and the act belongs beside the run it acts
on, which #1012 renders four sections below. The verdict is recorded in the
wave document.

No activity signal renders. A game that is Completed with a second run in
flight reads Completed on every screen this issue touches. #1033 owns the
Playing and Dormant reads, and it is a read over sessions with a user-scoped
threshold, not a status and not an event.

## Verification

| what | how |
|---|---|
| a first start on an Unplayed game states Played | the form renders the box, the submit appends both events, one `correlation_id` |
| a start on a Completed game states nothing | the form renders no `also_mark_played` box, and a posted `also_mark_played=on` appends no status event |
| a completion states Completed | from the form and from the row action alike |
| a completion on a game already Completed | the lifecycle event alone; the status command answers `Unchanged` |
| the boxes act only on a stated act | a note-only edit with both boxes ticked appends no status event |
| the row actions | Start renders only with no start, Complete only with a start and no completion, neither with both |
| the pair shares a correlation | every surface, read off `LibraryEvent` |
| a refused status leaves the run | the run is recorded, the sentence toasts, the page returns to its origin |
| replay | the pair replays to the same two rows, in either projector order |
| routes | both new routes are classified, and the completeness guard passes |

`make check` is the gate, `e2e/` included.
