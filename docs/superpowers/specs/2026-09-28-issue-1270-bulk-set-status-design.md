# Set status on many games

The Games list tray has a "Set status…" act. One confirmation asks for one of
the six `PlayerGameStatus` words. The act states that word on each selected
game, under one correlation id. The row's `GameStatusSelector` stays the
control for one row, so the row menu has no status item. Status is the only
fact: mastered is not offered. The act runs through the runner of
[#713](2026-09-20-issue-713-bulk-runner-design.md), in the
[wave](2026-09-19-selectable-tables-wave-design.md).

## The act

`games/bulk_status.py` declares `playergame.set_status`. Its scope is
`game_scope`, the list's own read through `tracked_by`. The resolve reads the
same rows and gives a key it does not find as lost, with `GAME_GONE`. The
preview shows Game, Platform ("Unspecified" when none) and Status. The Undo
takes `PlayerGame` keys, because the event goes on the PlayerGame's stream.

The tray shows Set status, then Remove. The destructive act is last.

## The question

The choice is one status word, through the plain `BulkChoice`. The form has
one required field with the runner's field name and no prefix. Thus the
confirmation and each progress POST use the same name. The widget is a
`ChoiceSearchSelectWidget` with no "none" row and no clear button. Its
placeholder shows the word that the rows have now: "Now: Played", or "Now: mixed". An empty
value or an unknown word gets the refusal "Choose a status." No rows: the
confirmation asks nothing.

## Forward

Each row calls `record_facts` with the word, the runner's key and the batch
source. A game that has the word already answers `Unchanged`. A choice that
is not a word when the row runs is `RowUnreadable`, because the runner
settled it in the same request.

`record_facts` writes the same `status_changed` event as
`SetPlayerGameStatus`, which no application code calls; #1313 retires it.
Its retry that tracks an untracked game cannot occur here, because each row
comes from `tracked_by`. The command does not refuse a removed PlayerGame. A removal
between the chunk's resolve and the dispatch is an accepted race.

## The inverse

`status_before(library, player_game_id, batch_id)` in
`games/reads/playergame_status.py` reads the row's stream:

- No `status_changed` from the batch: `None`.
- The latest earlier `status_changed`: its word.
- The latest earlier event is the creation: `UNPLAYED`.
- No earlier event: `RowUnreadable`.

The inverse refuses `None` ("not changed by this batch"). A game that has
the earlier word answers `Unchanged`; only then is a removed game refused.
Then it calls `record_facts` with the earlier word. Like the #1211 inverse,
it writes over a later change and logs it, so a second Undo answers
`Unchanged`. The #1256 gate refuses a second press
([#1284](https://github.com/KucharczykL/timetracker/issues/1284)).

The #1256 Undo reads `status_before` too, before its void, so a defect
leaves no half-undone row. There, `None` means "skip". A test that undoes a
status tracks its games through `track_game`: a row written directly has no
stream.

## Proof

`tests/test_bulk_status.py` and `e2e/test_bulk_game_status_e2e.py`.
