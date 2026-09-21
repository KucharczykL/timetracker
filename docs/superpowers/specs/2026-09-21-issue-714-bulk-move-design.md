# Move many sessions to one playthrough

A person selects sessions on the session list and moves them to one
playthrough. The batch is one act with one Undo. The code is in
`games/bulk_move.py`.

## The question an act asks

`BulkChoice` is a fact that an act asks for before it runs. `offer` gives the
control the confirmation shows, or a sentence that refuses the act. `settle`
gives the one string each row receives, or a refusal.

`games/views/bulk.py` states `CHOICE_FIELD`. The act's control carries that
name, and each later request posts the same field from the progress form.

`run_bulk_action` settles that field on each request that acts. A person can
change the field, and without a settle a wrong value reaches the command, which
answers `PlaythroughNotHeld` -- a defect.

`undo_bulk_action` does not settle, because its POST has no control. The
inverse leg's choice is the correlation id of the batch that it undoes.

A refused settle shows the confirmation again, on the same token and tally. A
new token would divide one batch into two correlation ids. If the act then
refuses the question, the batch ends and the rows that moved keep their Undo.

## The move

`offer_target` reads each resolved row, not the printed sample. If the rows are
at more than one game it refuses the act, because a playthrough is at one game.

`settle_target` accepts the key of a live ordinary run of this library. It does
not read the game, because the rows of a later chunk can be at two games.

`move_one` compares the row's game with the target's game. A different game is a
refusal with a sentence: that row stays as it is and the batch continues.

## The bucket

After a move, `move_one` reads the run the row came from. If that run is an
imported-history run that no registered referrer names, `move_one` removes it.
`rows_naming` also finds removed rows and rows of other libraries, and each of
these keeps the run.

It removes only the run it emptied: a run it did not empty is one its inverse
does not put back. `run_before` gives that run, because a chunk posted twice
answers `Unchanged` and the row then names the target.

A refused removal goes to the log and the row stays moved. A defect ends the
batch.

## The inverse

No column keeps the earlier run of a session. `run_before` reads the events of
the row, finds the move event of this batch, then reads the most recent earlier
event that states a run.

`move_back` restores a run only if this batch removed it. `RestorePlaythrough`
restores a run of any kind, so a run removed by hand after the batch stays
removed and that row receives a sentence.

The restore is before the move, because a move to a removed run is refused.

## The confirmation

The columns are Playthrough, Day, Duration, Device and Note. The resolve
attaches the playthrough name: a session carries its run without a number, a
bucket has no number, and `display_name` refuses both.

The page is wider because it shows a control, and its button takes the act's
colour.
