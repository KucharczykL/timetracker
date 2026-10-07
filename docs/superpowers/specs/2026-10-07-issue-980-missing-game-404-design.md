# A missing Game answers the catalog service with 404

Issue #980.

## Rule

A Game that is gone is an absence. It is not a refusal. The catalog service
answers it with `RowNotHeld`, and the boundary answers 404.

A `ValidationError` tells a person that the input is wrong. A Game that is gone
is no wrong input, so it carries no sentence. `Http404` in the service would put
HTTP into the service and log nothing.

## How a Game goes

A caller reads the Game, then the service locks it again. Two acts can destroy
the Game, or an add-on's parent, between those two reads:

- a whole-library purge;
- Add Game, which destroys its own Game when tracking fails after the graph
  committed.

## Where the service raises

Each lock that can miss a Game raises `RowNotHeld`. The argument names the row
and the library. No lock discards its answer.

- `state_addon()` in `games/catalog_addons.py` locks the edited Game and the
  stated parent. Add Game and Edit Game reach this lock first. A parent comes
  from the request body, so Add Game can miss it too.
- `save_game_columns()` in `games/catalog_submit.py` reads the edited Game
  again.
- `_writable_game()` in `games/catalog_writes.py`, which `state_catalog_graph()`
  calls.
- `release_on()` in `games/catalog_release.py` locks the Game first, then reads
  the Release back after the write. A Release goes only with its Game.

Add Game inserts its own Game in the same transaction, so no other transaction
can destroy that Game before the lock.

## Where the boundary answers

`absent_as_404(subject)` in `games/writes/answers.py` answers `RowNotHeld` with
`Http404` and one WARNING line, with no traceback. `answered()` uses it for the
command path.

The catalog callers do not use `answered()`. It catches every `django.db.Error`,
and `submitted_game_or_form_error()` must read the `IntegrityError` to give a
constraint sentence. Two callers use `absent_as_404("game")`:

- `submitted_game_or_form_error()` in `games/catalog_submit.py`, for Add Game
  and Edit Game;
- `release_on()`, for everything after the shared-game check, the read-back
  included.

`RowNotHeld` is not a `ValidationError`, so the `except ValidationError` clauses
inside the wrappers do not take it.

## The form dialog

A 404 in `<form-dialog>` is an answer, not a failure. The toast reads "This no
longer exists. Close this to reload the page." It carries no client error id,
because the server logged the 404. The dialog drops its unsaved-changes
baseline, so closing it asks nothing, and the close reloads the page.

## Path subjects

`RowNotHeld` governs an identifier in a request body. A row in a route's path
is the route's own subject, and `owned_or_404` scopes it. Edit Game's Game is a
path subject. A lock that misses a row the route held a moment ago is also an
absence, and it gets the same 404.

## An unsaved Game

`state_catalog_graph()` takes a saved Game. An unsaved Game is a defect, and the
verb raises `ValueError`. No person can cause it. An unsaved Game has a UUIDv7
key from its field default, so the lock would read no row and hide the mistake.

## Unchanged

A shared, foreign or removed Game keeps its `GraphRefused` sentence.

## Tests

A test destroys a Game with `Game.objects.filter(pk=...).delete()`. The test is
marked `untracked_games`, because a `PlayerGame` row has a `RESTRICT` key to its
Game.
