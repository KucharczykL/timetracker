# Move many sessions to one playthrough

Issue: [#714](https://github.com/KucharczykL/timetracker/issues/714). Part of
the [Selectable tables wave](2026-09-19-selectable-tables-wave-design.md).
Prerequisite: [#1080](https://github.com/KucharczykL/timetracker/issues/1080),
which supplies the confirmation's one control.

A person selects sessions on the session list and states the run they belong
to. The act is the bulk form of `MoveSessionToPlaythrough`, the command #692
ships. It is no second way to reassign a session.

## What the act asks for

Every act the runner holds today reads its rows and needs nothing else. This
one needs a target run, which no row states and no filter names. The runner
gains one concept for it, because #1211 sets one value over a selection the
same way and is ordered after this issue for that reason.

## The choice

`games/bulk_actions.py` states `type ChoiceValue = str` and one more value
beside `BulkAction`:

```python
@dataclass(frozen=True, slots=True)
class BulkChoice[RowT: Model]:
    """A fact the act asks for, read on every request that acts."""

    offer: Callable[[UserLibrary, Sequence[RowT]], Node | str]
    settle: Callable[[UserLibrary, Sequence[RowT], QueryDict], ChoiceValue]
```

`offer` answers the controls the confirmation hosts, or one sentence refusing
the whole act. `settle` answers one string, and raises a refusal for anything
it cannot read. `BulkAction.choice` holds one or none.

The runner owns the wire and the act owns the meaning. `games/views/bulk.py`
states `CHOICE_FIELD = "choice"` beside `TOKEN_FIELD` and `PROGRESS_FIELD`, and
no act names a field of its own. One string carries any grammar an act needs:
#1211 states a device and a flag together, as JSON, the way the selection
statement already rides in one field.

### Settled on every request, not once

The confirmation's press carries the controls' own fields. Every later chunk
carries `CHOICE_FIELD`, which the progress form states again. The runner calls
`settle` on **both**, and the act reads whichever of the two its POST holds.
Reading the carried field once and trusting it afterwards was rejected: a
tampered continuation would then reach the command, whose scope miss is
`PlaythroughNotHeld`, which the runner reads as a defect and answers with a 500
page that blames the app. Settling every chunk costs one indexed read against a
three-second chunk budget and turns that into a sentence.

The gate is `action.choice is not None`, never the field's truth: the empty
string is a value, and `request.POST.get` cannot tell it from an absent field.

The two legs both carry one string, so `Leg` states a `choice` and
`_run_a_chunk` passes it. **The inverse's choice is the batch it undoes.**
`_backward` states `str(correlation_id)`, the route's own argument, because
`_run_a_chunk` derives its correlation id from the undo's fresh token
(`games/views/bulk.py:379`) and the batch's own id otherwise never reaches
`action.inverse`. One slot, one meaning per direction: forward it is where the
rows go, backward it is which batch they came from.

### The blast radius

`RunRow` and `UndoRow` each take the choice as a fifth argument. Eight
production callables carry it (`games/bulk_removal.py`, six;
`games/bulk_reclassification.py`, two), five of which ignore it, together with
roughly twenty call sites in `tests/test_bulk_removal.py` and
`tests/test_bulk_actions.py` and three `BulkAction` constructions in the
latter. One uniform signature is taken over binding the value into a closure
for the acts that read it: two shapes of `run` would make `Leg` hold a
callable whose arity depends on a field of the act.

## The move

`games/bulk_move.py` declares one act, `session.move`, labelled
"Move to playthrough…" and coloured blue: the hours stay where they are, so
this is no removal.

Its scope and its resolve are the session pair `games/bulk_removal.py` already
states, which read `library_sessions` narrowed by the statement's filter and
report a key they do not find as lost. The resolve gains `"device"` to its
`select_related`, because the confirmation reads a device per row and fifty
rows would otherwise be fifty reads; the removal act's three columns never
touched it.

### The columns

The confirmation lists rows to `CONFIRMATION_SAMPLE`, fifty, in five columns:
Playthrough, Day, Duration, Device, Note. There is no Game column, because the
act refuses a selection spanning games and the one game is named in the
sentence above the table.

Fifty stands. The population this act exists for is one session, and a person
who wants to read more than fifty rows has the list, which holds the filter,
the sort and the paginator. The "and N more" line is the honest answer for a
selection nobody reads in one screen.

The page is wider than a confirmation's default. `ConfirmPage` states its box
as `FORM_MAX_WIDTH_CLASS`, 576px, into which five columns carrying free text do
not fit, so it takes the width as a parameter and the runner states a wider
one. `details` centres its content and colours it as a heading, which suits the
list of rows a removal states and not a labelled control, so `ConfirmPage` also
takes the choice's controls in a block slot of its own.

### The label a row reads

`run_labels_for` in `games/views/session.py` answers a label only where a game
holds more than one live run: its last comprehension keeps a run whose game has
siblings and drops the rest. That is right for the list, where a label on an
unambiguous row is noise, and wrong here, where the column exists to say what
each session moves **from** — most of all for a game holding one ordinary run
and the bucket, which is the shape this act exists for.

So the reader moves to `games/reads/session_run_labels.py` and answers two
questions: every session's label, which this act reads, and the list's
narrower one, built on it, which `games/views/session.py` keeps reading.
`IMPORTED_HISTORY_LABEL` moves with it.

The move is not a tidy-up. `games/views/session.py` imports
`games.bulk_reclassification` and `games.bulk_removal` at its top, and
`games/bulk_actions.py` imports each act module at its foot, so an act module
importing the view closes a cycle. A read belongs in `games/reads/` anyway, as
the records' own labels already do in `games/reads/historical_playtime_page.py`.

## The control

`offer` reads the distinct games of the rows it is given — every resolved row,
not the fifty the table prints, so the count is the selection's. More than one
game is refused whole, with a sentence naming the count: a selection at two
games has no one run to state, and a two-step picker is not what this screen
is. The sentence names the `game` facet, which the session list's quick bar
carries, so the remedy it states exists.

One game renders one `SearchSelect` with `create_url`, over
`GET /api/playthrough/?game=`, which answers the library's live ordinary runs
and no bucket. A run the person types and no option matches is created by
#1080's create row, ahead of the submit, so the posted value is always the key
of a run that exists.

**The control is always shown.** #1080's picker hides itself at one option or
none, which suits the add-session form. Here it must not: a game holding
exactly one ordinary run is the common case for a game whose history sits in
the bucket, and a hidden control leaves the person unable to state a run at
all. The hide rule stays in that form's own element and never in
`SearchSelect`.

`settle` resolves the posted key against `library_runs(library)` **narrowed to
the game the rows name**. Library-wide is not enough: `library_runs` spans
every game and `MoveSessionToPlaythrough` permits a run at another game by
design, so a stale or edited key would move the whole selection onto another
game's run and silently restate what game those sessions belong to, after a
confirmation that refused a cross-game selection on the grounds that one game
must be fixed. This is why `settle` takes the rows.

### A refusal keeps the selection

A settle that refuses re-renders the confirmation, with `ConfirmPage`'s
`refusal` slot carrying the sentence and the rows re-resolved from the tally's
keys, and the posted token kept. `_act_refused` is not used here: it renders a
page with no submit and no fields, and the confirm POST carries no selection
statement, so a person refused there loses every row they ticked and starts
again at the list. The keys are in the progress field, so keeping them costs
one resolve.

Mid-batch the tally's keys are the rows **left**, and the re-rendered
confirmation counts those. That is the page's honest reading: the rows already
moved are done and keep their Undo, and the person picks a run again and
finishes the rest. The realistic cause is a target another tab removed while
the batch ran.

## The bucket

The bucket takes no new session and a move is the only way out. When no session
names it any more, it is removed.

This is per row, not a step of its own, and it is asked about the **game**, not
about the run the session left. After a move that moved or was already so, the
act reads the imported-history run of that session's player game and removes it
when nothing names it. Keying the question on the row's earlier run was
rejected: a chunk that dies between the move and the removal, a progress form
the browser posts twice, or a row the person had already moved by hand all
reach `MoveSessionToPlaythrough` with source and target equal, which answers
`Unchanged`, and a source-keyed check would never fire again. The bucket would
stay, live and empty, with nothing left to empty it.

`RemovePlaythrough`'s last live run rule reads ordinary runs only, so a bucket
is always removable, and no `HistoricalPlaytime` can name one, because both the
record's command and the reclassification refuse a bucket.

**Any session, not only a live one.** `blocking_referrer` reads `alive()`, so a
session someone removed on its own does not block the removal — and once the
bucket is removed, `RestoreSession` refuses that session for ever, because it
refuses a session under a removed run. So the act asks the plain manager: a
bucket named by any session, removed or not, is left alone. This is stricter
than the command's own rule on purpose, and it costs nothing, since a bucket is
in no list to clutter.

**Its refusals are the bucket's, never the row's.** The removal is a second
dispatch inside one `run`, and the runner counts per row: a refusal raised
there would mark a session that moved as refused, and a `RowUnreadable` — which
`_refuse_a_foreign_referrer` raises and `answered()` answers at 500 — would end
the whole batch on a defect page over bucket hygiene. So the act catches the
bucket removal's answer, records it, and goes on. The move is what the person
asked for and it succeeded.

**Two dispatches, two keys.** The runner states one idempotency key per row,
`f"{leg.name}-{token}-{row}"`. Two commands under one key raise
`IdempotencyKeyMismatch`, which answers 409, so the second act would be refused
after the first committed. The act suffixes: `-move` and `-bucket` forward,
`-restore` and `-move` backward. Neither dispatch nests inside the other's
transaction; each opens its own, which is what the no-nested-dispatch rule
requires.

## The run before

The inverse states each session's earlier run. Nothing projects it: the move
event carries its target only.

`games/reads/events.py` gains `aggregate_events(library, aggregate_id)` beside
`batch_events` and `batch_aggregate_ids`. It reads the `library_event_aggregate`
index migration 0012 shipped, so there is no migration here. #713 left the
reader out on purpose, because its only caller is this issue.

The answer is exact, not the latest. The batch's own `moved` event for that
session — found through the correlation id the leg's choice carries — states a
sequence; the newest event below it whose type is
`library.playersession.created` or `library.playersession.moved` states the
answer in its payload's `playthrough` key. Both payloads carry that key, and a
sequence counts within one library's stream, so the comparison is total. A
session restated by something else after the batch therefore does not confuse
the inverse.

### The order the inverse keeps

`MoveSessionToPlaythrough` refuses a removed target, so a session whose earlier
run was the bucket cannot go back until the bucket is live. The inverse
restores first and moves second, per row, under one correlation id.
`RestorePlaythrough` answers `Unchanged` for a run already live, so the second
row and every repeat cost one dispatch that states nothing.

The run created ahead of the batch stays. It was created in its own request,
outside the batch, so `batch_aggregate_ids` never names it and no Undo can
reach it. The answer says so. A game may hold a run with no session — tracking
a game makes one — and removing it would be a second act with an Undo of its
own. An abandoned confirmation leaves such a run too, which is the cost #1080
accepts by name.

## Refusals

| what | where | what a person reads |
|---|---|---|
| a selection at two or more games | `offer`, whole act | the count of games, and the facet that narrows to one |
| a target that is no live ordinary run of this game | `settle`, every chunk | the confirmation again, its rows kept, the sentence above them |
| a session already on the target | the command | nothing; counted "already done" |
| a session under a removed game or run | the command, per row | the command's sentence; the batch goes on |
| a target removed between two chunks | `settle`, whole act | the confirmation again, as above |
| a session gone since the confirmation | the resolve, per row | counted lost |
| the emptied bucket refuses removal | swallowed | nothing; the move stands and the log names it |

The first two refuse before anything is written.

## What the runner already supplies

The two-POST token flow, the progress page, Stop, the chunk budget, the batch
Undo, the tally that counts moved, already so, refused and lost apart, and the
answer. This issue adds no page and no route.

`move_session` in `games/writes/playersession.py` gains the `idempotency_key`
and `source_metadata` keywords #712 gave the six removal wrappers, and answers
the command's result, so the runner tells a row that moved from a row already
there.

The session list adds the act to its `tray_actions` call. The act is declared
whether or not the filter names a game; the game is the confirmation's
question, not the list's.

## What proves it

**The choice.** A token POST with no choice on an act that declares one is
refused. A chunked batch settles the same choice on each of three requests. An
edited choice on a continuation chunk is a sentence, not a defect page. An act
that declares none still runs, and never settles.

**The control.** `offer` refuses two games with the count, over every resolved
row rather than the printed fifty. `settle` refuses a key that is no uuid, one
of another library, a removed run, a bucket, and a live ordinary run **at
another game**. The control renders for a game holding one run. A refused
settle re-renders the confirmation with its rows and its token.

**The label.** Every row of the confirmation reads a label, including a session
whose game holds one ordinary run and the bucket. The session list's own column
is unchanged.

**The move.** Rows move. A row already on the target counts as already done. A
row under a removed run is refused by name and the rest of the batch moves.

**The bucket.** The last session out removes it, under the batch's correlation
id. A batch whose rows were all moved by hand first still removes it. A stopped
batch leaves it holding the rest. A bucket named by a removed session is left
alone, and that session still restores. A refused bucket removal leaves the
row counted as moved and the batch running. An ordinary source run that empties
is left alone.

**The inverse.** The Undo moves each session back to the run its `created`
payload named, and to the run an earlier `moved` named, reading the batch
through the correlation id its leg carries. It restores the bucket first. It
leaves the run created ahead of the batch, and says so. A key that is not this
batch's comes out lost.

One browser pass: two sessions selected in the bucket, moved to a run, the
bucket gone from the list, the Undo putting both back and the bucket with them.

Full `make check` green at the merged commit.

## What this issue does not do

The Playthrough column and its sort are #715's. `outside_playthrough_dates` and
the Library page's two counts are #717's. Bulk Edit is #1211's, which inherits
the choice this issue builds.
