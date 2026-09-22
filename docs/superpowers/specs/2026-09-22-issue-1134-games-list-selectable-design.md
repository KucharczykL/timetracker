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
sharing. Two helpers in `games/writes/playergame.py` hold the rule for one
game: one removes and one restores. The act's `run`, the act's inverse and
the two per-row routes call them. The ownership gate is in the helpers, so
no caller can stamp or clear a shared catalog row. `_stamp` recounts every
purchase of a game and writes its wikidata mirror, so a shared row must
never reach it.

To remove a game:

1. `untrack_game` dispatches `RemovePlayerGame`, which appends
   `library.playergame.removed`.
2. If the library owns the game, `remove(game)` stamps the catalog row
   under `answered("game")`, so a database error is a defect and not a
   raw error.

The stamp writes no event. The event is the record of the batch.

In a batch, `PlayerGameNotTracked` is a refusal with a sentence, and the
helper stamps nothing: a stamp with no event is a row that the Undo
cannot see. Only the per-row route accepts that exception and stamps,
through an explicit argument.

If a defect stops the act between the two writes, the owned game is
untracked but has no stamp. It is not on the list. The per-row URL finds
it, and a second removal there completes it. The event is in the batch,
so the batch's Undo also restores it.

## Restore

The restore helper does the per-row order: the stamp, then the dispatch.

1. If the library owns the game, the helper first looks for a live game
   of the library that the two partial unique constraints would refuse:
   the same name, platform and year, or, for a game with no platform, the
   same name and year with no platform. One `Q` states both. If it finds
   one, it refuses with 409 and a sentence that names the newer game, and
   changes nothing. A database refusal answers 500 and would end the whole
   Undo as a defect. The check is a forecast, not the rule: a game created
   between the check and the update still meets the constraint, and the
   `db.Error` backstop of `answered` answers that defect.
2. It clears the stamp under `answered("game")`.
3. It dispatches `RestorePlayerGame`. If that is refused after the stamp
   is clear, the sentence says that the game is back in the catalog but
   not tracked yet. The per-row route states that sentence today. It moves
   into the helper, so a batch row says it too.

`untrack_game` and `retrack_game` take `idempotency_key` and
`source_metadata`, and answer `CommandResult`, as `end_session` does. The
tally can then tell moved from already so. The `TrackGame` fallback in
`retrack_game` never takes the caller's key: a second command under one
key is an `IdempotencyKeyMismatch`. It mints its own. It is for the
per-row restore only, because the Undo restores a PlayerGame that it
found.

## The per-row routes

`remove_game` finds a live game that the library owns, or a shared game
that the library tracks. The first half keeps the halfway row reachable.
`restore_game` finds a game that the library owns, or a shared game that
the library holds a PlayerGame for. Before this issue, Remove on a shared
row answered 404.

Each rule is stated once, on `GameQuerySet` beside `tracked_by`:
`removable_by(library)` and `restorable_by(library)`. The two routes read
them. The act reads the list's own `tracked_by`, and the Undo reaches the
game through the library's own PlayerGame. Neither needs a second guard.

## The Undo

`inverse_aggregate` is `playergame`. The Undo reads PlayerGame keys from
`batch_aggregate_ids`. Each row of the list is tracked, so each row that
the batch removed has an event. A PlayerGame key is not a Game key. The
inverse finds the removed PlayerGame through the plain manager, scoped on
the library, reads its `game`, and calls the restore helper. A game that
a person restored between the batch and the Undo answers `Unchanged`.

## The confirmation

The confirmation states what leaves with each game, as the per-row
ConfirmPage does. The preview columns are Game, Sessions, Purchases and
Playthroughs, in `sort_name` order. Each count is a correlated subquery
from `games/reads/`, scoped on the library:

- sessions through `library_sessions`;
- purchases through `Purchase.objects.for_library(library)`, as Game
  detail counts them. `game.purchases.alive()` also counts the purchases
  of other libraries on a shared game, so `_removed_with_game` changes to
  this read as well;
- runs correlated on `player_game__game` and `player_game__library`,
  live and ordinary.

A join count is not permitted, because it multiplies. `bulk_removal` does
not import the view. The runner resolves each row again in each chunk, so
the three subqueries run once for each row. That cost is accepted.

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

- A bulk status act, #1270. It is the set-one-value shape of #1211, and it is a
  follow-up after #1211.
- A per-row summary below `md`. That is #1241's.
- Game detail's Edit and Remove buttons. They are not a table.

## Proof

`make render-pages` before and after. Each differing file is a Games list
page, and each difference is the selection markup, the menu slot or the
removed Actions column. `e2e/test_return_to_origin_e2e.py` opens the menu
before it follows Edit. `e2e/test_pinned_column_e2e.py` still gets a
Games list that overflows.

The parametrised cases of `tests/test_bulk_removal.py` take the fourth
act. The tests that read the Games list's Actions cells or the `actions`
key change with it: `test_column_keys`, `test_column_picker`,
`test_rendered_pages`, `test_html_validity`,
`test_library_page_isolation` and `test_playergame_game_views`.
