# Select games and remove them in bulk

The Games list is a selectable table. The tray offers one act, Remove. The
row's ⋯ menu offers Edit and Remove. The Actions column is gone. The status
selector stays in its cell as an immediate control. The act is
`REMOVE_GAME` in `games/bulk_removal.py`.

## The rows

The list reads `Game.objects.tracked_by(library)`, so each row is a catalog
Game and the library tracks it. The selection names the Game key, as the
row's links do. `game_scope` narrows that read by the statement's filter
through `narrowed` and `parse_game_filter`. `game_resolution` reads the
same base. It refuses no key that it finds. A key it does not find is lost,
with a sentence of its own.

## Two writes for one row

A game leaves the library in two writes. `untrack_game` dispatches
`RemovePlayerGame`, which appends `library.playergame.removed`. Then
`remove(game)` stamps the catalog row. The stamp writes no event. The
event is the record of the batch.

`run` does the two writes in the order of the per-row route. The runner
makes the key from the token and the row. If a defect stops a chunk
between the two writes, the game is untracked but has no stamp. When the
person posts the chunk again, the dispatch replays under the same key and
the stamp follows. The per-row route has the same halfway.

`untrack_game` and `retrack_game` take `idempotency_key` and
`source_metadata`, and answer `CommandResult`, as `end_session` does. The
tally can then tell moved from already so. `untrack_game` still accepts
`PlayerGameNotTracked`, for the per-row route. The fallback `TrackGame` in
`retrack_game` states a key of its own, which comes from the row's key.

## The Undo

`inverse_aggregate` is `playergame`. The Undo reads PlayerGame keys from
`batch_aggregate_ids`. Each row of the list is tracked, so each row that
the batch removed has an event. A PlayerGame key is not a Game key. The
inverse finds the removed PlayerGame through the plain manager, scoped on
the library, and reads its `game`.

The inverse does the per-row restore in its order: it clears the stamp,
then it retracks. If the retrack is refused, the stamp is already clear.
The row gets the sentence that the per-row restore states.

## The confirmation

The confirmation states what leaves with each game, as the per-row
ConfirmPage does. The preview columns are Game, Sessions, Purchases and
Playthroughs. The counts come from annotations over the resolved keys,
with the scopes of `_removed_with_game`: `library_sessions`, live
purchases, live ordinary runs. Three queries per row are not permitted.

## The row menu

`game_row_menu` in `games/views/game_menu.py` builds the items:

1. Edit, a link to `edit_game`.
2. Remove, a link to the per-row ConfirmPage, with `REMOVE_GAME.label`
   and `danger=True`.

Remove keeps two entries, as on the session list (#1209 weighs this). The
label of the trigger is "`<game name>` actions".

The view states `menu_slot: True` and deletes the Actions column. The
table leaves `tests/test_column_priority_contract.py`. The column picker
goes into the slot by itself. Status is an ordinary column that a person
can hide. Only Name is `hideable=False`.

## Not in this issue

- A bulk status act. It is the set-one-value shape of #1211, and it is a
  follow-up after #1211.
- A per-row summary below `md`. That is #1241's.
- Game detail's Edit and Remove buttons. They are not a table.

## Proof

`make render-pages` before and after. Each differing file is a Games list
page, and each difference is the selection markup, the menu slot or the
removed Actions column.
