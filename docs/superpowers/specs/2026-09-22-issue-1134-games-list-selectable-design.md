# Select games and remove them in bulk

The Games list is a selectable table. The tray offers one act, Remove. The
row's ⋯ menu offers Edit and Remove. The Actions column is gone. The status
selector stays in its cell as an immediate control. The act is
`REMOVE_GAME` in `games/bulk_removal.py`: name `playergame.remove`, subject
"game", title "Remove this game" and "Remove these games", colour red,
fallback `games:list_games`.

## The rows

The list reads `Game.objects.tracked_by(library)`. That read also holds
shared catalog games, which no library owns (`library` is null). The
selection names the Game key, as the row's links do. `game_scope` narrows
that read by the statement's filter through `narrowed` and
`parse_game_filter`. `game_resolution` reads the same base. It refuses no
key that it finds. A key it does not find is lost, with a sentence of its
own.

## Remove from my library

The act states the library's own fact. It does not state a rule about
sharing. One helper in `games/writes/playergame.py` does the act for one
game, and the act's `run` and `remove_game_for_request` both call it:

1. `untrack_game` dispatches `RemovePlayerGame`, which appends
   `library.playergame.removed`.
2. If the library owns the game, `remove(game)` stamps the catalog row.
   A shared catalog row gets no stamp.

The stamp writes no event. The event is the record of the batch. The
stamp runs under `answered("game")`, so a database error is a defect of
the batch and not a raw error.

`untrack_game` and `retrack_game` take `idempotency_key` and
`source_metadata`, and answer `CommandResult`, as `end_session` does. The
tally can then tell moved from already so. `untrack_game` still accepts
`PlayerGameNotTracked` for the per-row route. The `TrackGame` fallback in
`retrack_game` is for the per-row restore only.

If a defect stops the act between the two writes, the owned game is
untracked but has no stamp. It is not on the list. Only the per-row URL
finds it, and a second removal there completes it.

## The per-row routes

`remove_game` finds a live game that the library owns, or a shared game
that the library tracks. The first half keeps the halfway row reachable.
`restore_game` finds a game that the library owns, or a shared game that
the library holds a PlayerGame for. The per-row restore uses the same rule
as the inverse. Before this issue,
Remove on a shared row answered 404.

## The Undo

`inverse_aggregate` is `playergame`. The Undo reads PlayerGame keys from
`batch_aggregate_ids`. Each row of the list is tracked, so each row that
the batch removed has an event. A PlayerGame key is not a Game key. The
inverse finds the removed PlayerGame through the plain manager, scoped on
the library, and reads its `game`.

The inverse does the per-row restore in its order. If the library owns
the game, it clears the stamp under `answered("game")`. Then it dispatches
`RestorePlayerGame`. A catalog row that collides with a newer game on its
unique name gives a refusal with a sentence, and the row stays removed.
The per-row restore keeps its `retry=True`.

## The confirmation

The confirmation states what leaves with each game, as the per-row
ConfirmPage does. The preview columns are Game, Sessions, Purchases and
Playthroughs, in `sort_name` order. Each count is a correlated subquery
from `games/reads/`, with the scope of `_removed_with_game`:
`library_sessions`, live purchases, live ordinary runs. A join count is
not permitted, because it multiplies. `bulk_removal` does not import the
view.

## The row menu

`game_row_menu` in `games/views/game_menu.py` builds the items:

1. Edit, a link to `edit_game`. It is absent on a shared game, the rule
   that Game detail applies to catalog controls.
2. Remove, a link to the per-row ConfirmPage, with `REMOVE_GAME.label`
   and `danger=True`, on each row.

Remove keeps two entries, as on the session list (#1209 weighs this). The
label of the trigger is "`<name>` (`<platform>`) actions". A game with no
platform has no parenthesis.

The view states `menu_slot: True` and deletes the Actions column. The
column-priority contract test then exempts the table, because it has no
Actions header. The column picker goes into the slot by itself. Status is
an ordinary column that a person can hide. Only Name is `hideable=False`.

## Not in this issue

- A bulk status act. It is the set-one-value shape of #1211, and it is a
  follow-up after #1211.
- A per-row summary below `md`. That is #1241's.
- Game detail's Edit and Remove buttons. They are not a table.

## Proof

`make render-pages` before and after. Each differing file is a Games list
page, and each difference is the selection markup, the menu slot or the
removed Actions column. `e2e/test_return_to_origin_e2e.py` opens the menu
before it follows Edit. `e2e/test_pinned_column_e2e.py` still gets a
Games list that overflows.
