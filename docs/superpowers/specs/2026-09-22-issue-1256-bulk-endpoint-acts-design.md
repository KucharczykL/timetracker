# State a start or a completion on many runs

A person selects runs on a playthrough table. One act states one endpoint
at today on each of them. The tables are the Playthrough list and the runs
on Game detail. The acts are in `games/bulk_playthrough_acts.py`.

## The confirmation

Each act states a second fact. A completion states Completed on the game.
A start states Played on a game that no stronger word describes.

An act with a side effect is never one press. Thus the row's two items in
the ⋯ menu post a statement that names one row to the runner, as the
session menu's Move does. The act has one route and one set of rules. The
single row gets the confirmation, the tally and the Undo.

The items read the label of the act. The confirmation states the day and
the side effect.

## The day

`offer` reads `calendar_today` and puts that day in the confirmation.
`settle` reads the day back.

The runner makes a fingerprint of the input of each command. A day that
`run` reads again is different between two posts of one chunk at midnight.
Then each row of the first post is refused. A stamped day also keeps the
chunks of one batch on one day. A reconfirmation stamps again.

The calendar states the day. Thus the act asks for no zone.

## The acts

`run_scope` and `run_resolution` are in `games/bulk_runs.py`. The acts
state no rule of their own. `StartPlaythrough` and `CompletePlaythrough`
refuse a run that states that endpoint. The refusal is a sentence for that
row, and the batch continues.

`games/writes/playthrough_endpoints.py` states the endpoint and then the
status. It states the status for an appended outcome and for a replayed
one. A replay is a chunk that a person posts again, and the status can be
the statement that the first post did not make. The status has a key that
comes from the key of the row. A refused status is a log entry, and the
row counts as done.

## The voids

`VoidPlaythroughStart` and `VoidPlaythroughCompletion` take back the
record. The projector writes the day, the note and the marker back to the
values of a run before an act. Each command answers `Unchanged` if the
endpoint is unstated, before it reads the two marks.

No other command unstates an endpoint. `CorrectPlaythroughStart` and
`CorrectPlaythroughCompletion` refuse a run that states none.

## The inverse

The inverse reads the events of the row. The statement, the correction and
the void of one endpoint are one family. The inverse voids the endpoint
only if the event of this batch is the last event of that family. If it is
not, the row keeps its value and gets a sentence.

The inverse then reads the `library.playergame.status_changed` event of
this batch. It states the word before that event, which is the most recent
earlier word or Unplayed. It states nothing if a person changed the status
after the batch. The endpoint is the fact of the row. The status is the
fact that the endpoint implies.

`inverse_aggregate` names the rows of the Undo. It does not name what the
inverse reads.
