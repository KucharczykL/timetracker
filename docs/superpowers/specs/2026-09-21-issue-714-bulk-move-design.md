# Move many sessions to one playthrough

A person selects sessions on the session list and moves them to one
playthrough. The batch is one act with one Undo. The code is in
`games/bulk_move.py`.

## The question an act asks

`BulkChoice` is a fact that an act asks for before it runs. It has two
functions.

| Function | Result |
|---|---|
| `offer` | The control the confirmation shows, or a sentence that refuses the act |
| `settle` | One string for every row, or a refusal |

`BulkAction.choice` holds one `BulkChoice` or `None`. A `ChoiceValue` is text.
One string holds any grammar that an act needs.

`games/views/bulk.py` states `CHOICE_FIELD`. The act's control carries that
name. The confirmation posts the control. Each later request posts the same
field again from the progress form.

`run_bulk_action` settles that field on each request that acts. It does not trust the
carried value. A person can change the field, and a wrong value goes to the
command. The command answers `PlaythroughNotHeld`, and
the runner shows that as a defect.

`undo_bulk_action` does not settle. Its POST has no control. The inverse leg's
choice is the correlation id of the batch that it undoes.

A refused settle shows the confirmation again. The token and the tally stay the
same. A new token would divide one batch into two correlation ids.

## The move

`offer_target` reads each resolved row, not the printed sample. If the rows are
at more than one game, it refuses the act. A playthrough is at one game.

`settle_target` accepts the key of a live ordinary run of this library. It does
not read the game. The rows of a continuation can be at two games.

`move_one` compares the row's game with the target's game. A different game is a
refusal with a sentence. That row stays as it is, and the batch continues.

## The bucket

After a move, `move_one` reads each imported-history run of the game. A game can
have more than one. `move_one` removes each run that no registered referrer
names. `rows_naming` also finds removed rows and rows of other libraries. Each
of these keeps the run.

A refused removal goes to the log. The row stays moved.

## The inverse

No column keeps the earlier run of a session. `run_before` reads the events of
the row. It finds the move event of this batch. Then it reads the most recent
earlier event that states a run.

`move_back` restores a run only if this batch removed it. `RestorePlaythrough`
restores a run of any kind. A run a person removed after the batch stays
removed, and that row gets a sentence.

The restore is before the move, because a move to a removed run is refused.

## The confirmation

The columns are Playthrough, Day, Duration, Device and Note. The resolve
attaches the playthrough name to each row. `display_name` refuses a run that has
no name and no number, and the run of a session has no number.
