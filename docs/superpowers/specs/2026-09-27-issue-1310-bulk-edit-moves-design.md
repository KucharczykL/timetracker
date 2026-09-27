# Bulk Edit states the playthrough

Bulk Edit ([#1211](2026-09-25-issue-1211-bulk-edit-design.md)) gets a
Playthrough field, as the row's own Edit form has. The Move act
([#714](2026-09-21-issue-714-bulk-move-design.md)) leaves the act table. The
Undo of an old Move batch gets the runner's `UNKNOWN_ACT` answer, which is how
the runner ends a removed act.

`games/bulk_move.py` keeps the move of one row: the move, the removal of the
imported-history bucket that it emptied, and the move back. Each function
takes the act name for every `source_metadata` and log line. The runner reads
the act from the first event of the batch, which is the move.

## The statement

`EditStatement` gets a fourth fact, `playthrough`: a run key, or `None` to
keep. A session always names a run, so this fact has no "none". The run alone
is a statement.

## The question

Playthrough is the first field: a bare `SearchSelectWidget` with
`commit_sole_option=False`, so an empty picker keeps. Its queryset is
`library_runs(library)`, and its options come from the session form's run
resolver. When the rows are at one game, `params` give that game as a
literal, and the picker searches and creates runs there. It has no ⊘. The
placeholder keeps the run of the rows, compared by key.

When the rows are at more than one game, `offer_edit` renders the form
without the picker. In its place, a row shows the label and "These sessions
are at N games. Narrow the list by game to change the playthrough." The
settle form always has the field. A posted run on such a selection is
accepted, and each row at another game refuses with `ANOTHER_GAME`.

## The act

`edit_one` refuses a row at another game than the run before any write.
Then it moves, then it describes, with the batch's correlation id. Only the
stated facts are dispatched. The keys are `<key>-move`, `<key>-bucket` and
`<key>`. The row is `MOVED` when either write changed it. The bucket removal
reads the move's own outcome.

A description can fail after the move, for example on a device removed in
that moment. That is a defect: the batch ends, and its Undo moves the row
back.

A chunk posted twice and a second Undo give `Unchanged` in each command.

## The inverse

`edit_back` reads the facts that the batch changed: the move from
`run_before`, the others from `values_before`. When it finds none, it refuses
with `NOT_EDITED_BY_THIS_BATCH`. It restates the described facts first. Then
it restores the bucket that the batch removed and moves the row back. A
refused move-back refuses the row with a sentence that names the run.

## The confirmation

`labelled_session_resolution` in `games/bulk_sessions.py` stamps each row's
run label. Finish and Remove keep the plain resolve. The preview columns are
Game, Playthrough, Day, Duration, Device, Emulated and Note.

## The menus

The tray is Finish, Edit, Reclassify, Remove. The row menu loses its Move
item, because the row's Edit states the run.
