# State a start or a completion on many runs

A person selects runs on a playthrough table and states one endpoint at
today on each of them. The two tables are the Playthrough list and the
runs on Game detail. The acts are in `games/bulk_playthrough_acts.py`,
the rows they read in `games/bulk_runs.py`.

## Why the acts confirm

Each act states a second fact about a second row. A completion states
Completed on the game. A start states Played on a game that no stronger
word describes. An act with a side effect is never one press, which is
the rule for every act in the
[Selectable tables and Session organization wave](2026-09-19-selectable-tables-wave-design.md).

The row keeps its two items in the ⋯ menu, and each item posts a
selection statement that names that one row to `games:run_bulk_action`,
as the session menu's Move does. The act has one route, one set of
rules and one Undo, and the single row receives the confirmation, the
tally and the Undo that a per-row route never gave it.

`games/views/playthrough_acts.py` and the routes `games:start_playthrough`
and `games:complete_playthrough` are retired, with their two names in
`ORIGIN_AWARE`, the two request-shaped wrappers in
`games/views/playthrough_writes.py` and the first-statement helpers in
`games/writes/playthrough.py` that no caller keeps. `record_completed`
and `played_is_offered` stay: the run's form states both.

Each item reads the label of the act it posts to, so one act reads the
same in the tray and in the menu. The side effect is on the
confirmation, which is now the one screen before every write.

## The day the batch states

The acts declare a `BulkChoice`. Its `offer` reads `calendar_today` for
the library and puts that day in the confirmation's own HTML. Its
`settle` reads the day back and refuses text that is not one day.

The day is in the page because the runner fingerprints the input of each
command. A day read again in `run` differs between two posts of one
chunk across midnight, and each row that the first post stated is then
reported refused. A stamped day also keeps the chunks of one batch on
one day. A reconfirmation stamps again, as Finish's does, so a batch
reconfirmed after midnight states the new day for the rows that remain.

`settle` accepts every day the grammar reads. A person who writes
another day in the field states that day, as a person who writes another
instant in Finish's field states that moment. The act names today
because the page states today.

The library's calendar states the day, so the act asks the browser for
no zone. The sentence beside the stamped day states the day and the side
effect: each game is marked Completed, or each game that is not yet
played is marked Played.

## The acts

`run_scope` is the list's own read with the statement's filter, and
`run_resolution` numbers the rows across the live ordinary runs of the
games the keys name. They move to `games/bulk_runs.py` with `RUN_GONE`,
`RUN_PREVIEW` and the cells that write an endpoint, beside
`games/bulk_sessions.py`. The act table imports each act module at its
foot, so an act module that reads a name off a sibling fails for one
entry order alone.

The acts state no gate of their own. `StartPlaythrough` and
`CompletePlaythrough` refuse a run that states that endpoint already, and
refuse a day that reverses the two endpoints. A run that states the same
day and no note answers `Unchanged`, which the tally counts as already
so. The confirmation prints the Started and Completed column of every
row it resolved, so a person reads which rows the commands refuse.

## The status the act implies

`games/writes/playthrough_endpoints.py` states one endpoint and then the
status it implies. The endpoint is first, so the metadata of the first
event of the batch names the act.

It states the status where the dispatch appended an event and where it
replayed one. A replay is a chunk posted again, and the status of that
row can be the statement that the first post never reached. The status
command answers `Unchanged` where the game holds that word already, so
the second statement writes nothing.

The status carries a key derived from the row's key, as the move derives
the key of the bucket it empties. Without one the status is stated again
under a new key at each post.

A refused status is carried back in the answer where the refusal is a
conflict: the endpoint is stated, the row counts moved, and the act
writes one line in the log. A defect rises and ends the batch, as a
defect ends it everywhere else.

`record_facts` grows an idempotency key and source metadata for this, as
`end_session` grew them for the Finish act.

## The voids

No command unstates an endpoint before this issue.
`CorrectPlaythroughStart` and `CorrectPlaythroughCompletion` restate an
endpoint the run states, and refuse a run that states none, because an
unstated endpoint holds the values that a "played before" correction
states.

`VoidPlaythroughStart` and `VoidPlaythroughCompletion` retract the
record. A void is a retraction, which takes a verb of its own. Each
answers `Unchanged` where the endpoint is unstated, ahead of every
refusal, and each then refuses a removed run and a run under a removed
`PlayerGame`, as `RemovePlaythrough` and `RestorePlaythrough` answer in
that order.

`library.playthrough.start_voided` and `.completion_voided` carry an
empty payload and no day: the act retracts a record and describes no
day. The projector writes `started`, `start_recorded_at` and
`start_note` back to the values a run holds before any act, so a null
record column reads again as the act that did not occur. Each spec takes
a `CommandName` member, a handler in `Playthroughs.handles`, and a place
in the stream that the replay gate builds, which states every registered
type and counts them.

The two commands have no screen. The run's edit form corrects an
endpoint and clears none.

## The inverse

The inverse reads the events of the row and finds the latest event about
that endpoint: the statement, the correction and the void are one family
there. The void of an endpoint is right only where that latest event is
the event of this batch.

A row that this batch never stated is refused, as a row that is gone is
refused. A row whose endpoint another act states after the batch is
refused with a sentence, and the batch continues. A correction and a
second statement are one case: the value belongs to whoever wrote it
last. The rule is the wave's: an inverse that restates what the batch
wrote over reads the row as it stands and accepts that hazard, and an
inverse that destroys a value the batch never wrote refuses the row.

A row whose endpoint is unstated answers `Unchanged`, which the tally
counts as already so. An Undo pressed twice reads that answer, because
each press mints a token of its own.

The inverse then puts the status back. It reads the
`library.playergame.status_changed` event of this batch for the game of
the row, and states the status that stands before it, which is the most
recent earlier status event of that game or Unplayed, the word a tracked
row holds while its stream states none.

It says nothing where the game holds that earlier status already, and
nothing where this Undo states the status itself: two rows at one game
share one status event, and the second row would otherwise read the
restoration of the first as somebody's change. Every other status is a
person's, and it stays as that person stated it. The endpoint still
goes, because the endpoint is the fact of the row and the status is the
fact it implies. The batch log names the row, the game and both words.

One row of a game can be refused while its sibling is undone, and the
game then holds the earlier status beside a completion the refusal kept.
The refusal names the run, so the person reads which run to correct.

`inverse_aggregate` is `playthrough`, which names the rows of the Undo.
It does not name what the inverse may read.

## The tray and the menu

Both tables offer Started today, Completed today and Remove, in that
order: the act reached for most often first and the destructive act
last.

A run that states a completion is offered no start in the menu, and a
run that states no start is offered no completion. The tray offers both
acts at every time, and the commands refuse the rows that cannot take
them. The menu gate is the narrower of the two on purpose, and the
comment that reads it states what the gate is, not what the command
refuses: a start at today on a run completed today, on a day nobody
wrote down, or on a day a qualifier widens is a start the command takes.
