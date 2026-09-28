# Set status on many games

The Games list tray gets a "Set status…" act. One confirmation asks for one of
the six `PlayerGameStatus` words and states it on every selected game, under
one correlation id. The row's inline `GameStatusSelector` stays the control for
one row, so the row menu does not change. The act follows the
[wave](2026-09-19-selectable-tables-wave-design.md) and the runner of
[#713](2026-09-20-issue-713-bulk-runner-design.md). Status is the only fact:
mastered and the other PlayerGame facts are not offered.

## The act

`games/bulk_status.py` declares `playergame.set_status`: label "Set status…",
title "Set this game's status" / "Set the status of {count} games", submit
"Save", colour blue, subject "game". Its inverse takes the `playergame`
aggregate and reads `PlayerGame` keys, as `playergame.remove` does, because
the event is appended under the PlayerGame's key.

The scope is `game_scope` from `games/bulk_removal.py`, the list's own read
through `tracked_by`. The resolve reads the same rows with their platform,
orders them by `sort_name` and key, and answers a key it does not find as
lost, with `GAME_GONE`. It does not read departures, and it has no
partly-removed sentence: both are the removal's. The preview columns are Game,
Platform ("Unspecified" where none) and Status, the label of
`PlayerGameStatus(tracked_status)`.

The module is imported at the foot of `games/bulk_actions.py`, which is what
declares the act.

The tray states Set status, then Remove: the destructive act is last. Set
status has no row-menu item, so `tray_actions`' docstring changes: the tray
follows the row menu's order for the acts both offer.

## The question

One fact, so the plain `BulkChoice`; the choice is the status word. The
control is one required `ChoiceField` over the six words, named `field_name`
with no prefix, in a form rendered through `FormFields`, so the widget's media
reaches the page. The runner posts the settled word under the same name on
every progress POST, so `settle` reads one name on both posts. The widget is
a `ChoiceSearchSelectWidget`; required, so it has no none row. Its placeholder
names the word the rows hold now, "Now: Played", or "Now: mixed". It never
says "Keep": an empty post (the × can empty the field) is refused with "Choose
a status.", not kept. `settle` refuses a word that is not one of the six with
the same sentence. No rows: `AsksNothing`.

## Forward

Each row calls `record_facts(actor, game, status=word, ...)` with the runner's
key and correlation id, and `{"bulk": {"action": "playergame.set_status"}}`
as its source. A game that states the word already answers `Unchanged`. A
choice that is absent or not a word at run time is `RowUnreadable`: the runner
settled it in this request, so the fault is ours.

`record_facts` dispatches `RecordPlayerGameFacts`, which writes the same
`status_changed` event as `SetPlayerGameStatus`. No write path dispatches
`SetPlayerGameStatus`; #1313 retires it.

`record_facts` tracks an untracked game and retries, under the batch's
correlation id. The act cannot reach that branch: every resolved row comes
from `tracked_by`, and nothing but a purge destroys a PlayerGame.

`RecordPlayerGameFacts` does not refuse a removed PlayerGame. The runner
resolves each chunk again, so only a removal between that read and the
dispatch reaches the command; the status is then written on the removed row.
That race is accepted.

## The inverse

`status_before(library, player_game_id, batch_id)` in
`games/reads/playergame_status.py` reads the row's stream:

- No `status_changed` of the batch: `None`.
- The latest earlier `status_changed`: its word.
- No earlier one, and the creation earlier: `UNPLAYED`, the word a tracked row
  starts with.
- No creation earlier: `RowUnreadable`. Every stream starts with its creation,
  so this is a guard, not a path.

The inverse turns `None` into a refusal: "That game's status was not changed
by this batch, so it was left as it is." It reads the PlayerGame with the
plain manager and the library. A removed game is refused: "That game is
removed. Restore it first." Then `record_facts(status=before)` runs under the
Undo's key and correlation id.

It does not check whether somebody changed the status after the batch. It
states the earlier word, as #1211's inverse does. A second Undo press answers
`Unchanged` for each row. The gate of #1256 refuses a second press
([#1284](https://github.com/KucharczykL/timetracker/issues/1284)) and is not
used here.

`_status_before` in `games/bulk_playthrough_acts.py` calls `status_before`, so
it gets the creation check too. `None` there still means "skip": most rows of
a start or completion batch changed no status. Its `_stated_since` gate is
#1284's to change.

## Proof

- `tests/test_bulk_status.py`: forward on several games under one correlation
  id; already-so counted unchanged; settle refusals; Undo to an earlier word;
  Undo to Unplayed on a creation-only stream; a second Undo unchanged; Undo on
  a removed game refused; a row the batch did not change refused; a stream
  with no creation is a defect; the confirmation with no rows asks nothing.
- `e2e/`: select two games, set Completed, read the tally, press Undo.
- `make render-pages`: only the Games list tray differs.
