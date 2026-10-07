# A missing Game answers the catalog service with 404

Issue #980. Not a wave member; registered in #601 as a catalog follow-up.

## Problem

`_writable_game()` in `games/catalog_writes.py` reads the owning Game with
`Game.objects.select_for_update().get(pk=game_id)`. `state_catalog_graph()` is
the one verb left, and every write of a private catalog graph goes through it.

Two ways reach `Game.DoesNotExist`:

1. A **stale Game**: the caller fetched the row, then it was destroyed before
   the lock. Two acts destroy a Game a request can name: a whole-library purge,
   and Add Game's own `game.delete()` when tracking fails after the graph
   committed. The stake is a right status code and a WARNING line instead of a
   500 and a traceback.
2. An **unsaved Game**. Its pk is a fresh UUIDv7 (`UUIDv7Field` has a default;
   the issue's `pk=None` claim is wrong, checked in a shell), so the lock reads
   no row. `DoesNotExist` says nothing about the real mistake.

Which read fails first depends on the caller:

- **Edit Game**: `save_game_columns()` calls `state_addon()` first, which locks
  with `.filter()` and drops a missing Game silently. Under a purge, an add-on's
  private parent went too and reaches `_refuse_the_parent()` as `None`, which
  raises `RowUnreadable`: a 500 and an ERROR record. Otherwise the next
  unguarded `.get()` in `save_game_columns()` raises `DoesNotExist`.
- **Add Game**: the Game was inserted in the same uncommitted transaction. No
  other transaction can destroy it.
- **`POST /api/releases/`**: `release_on()` locks with `.filter().first()` and
  ignores the answer, so `_writable_game()` is the read that fails. After
  commit, `release_on()` reads the Release back with an unguarded `.get()`.

`docs/catalog.md` says every refusal is a `ValidationError` with one sentence.
The missing Game is the one exception, unstated.

## Decision

**A stale Game is an absence.** The issue's option 2, with the exception the
house already has: `RowNotHeld` in `games/events/dispatch.py`, "a row this
library does not hold; an absence", which `answered()` maps to `Http404` with
one WARNING line and no sentence. A purged Game is a row this library does not
hold.

- A `ValidationError` would tell a person their input is wrong when the row is
  gone.
- A new exception class would duplicate `RowNotHeld`.
- `Http404` raised in the service, as `release_on_platform()` does for a key
  that never resolved, puts HTTP into `catalog_writes` and logs nothing.

CLAUDE.md scopes `RowNotHeld` to an identifier in a request body; a path
subject is `owned_or_404`'s. Edit Game's Game is a path subject. This decision
extends the rule: a re-resolve under a lock that misses a row the route held a
moment ago is an absence too, and answers the same 404.

Each lock that can miss raises `RowNotHeld` naming the row and library keys:

- `state_addon()` when the Game is persisted and the lock returns none. This
  runs first on Edit Game. After it, the Game is locked, so the later `.get()`
  in `save_game_columns()` cannot miss and stays as it is.
- `_writable_game()`, through `.filter(pk=...).first()`.
- `release_on()`'s read-back of the Release, through `.filter().first()`.

**An unsaved Game is a defect.** `state_catalog_graph()` refuses a Game whose
`_state.adding` is true with `ValueError`. No sentence: no person can cause it.
Every caller passes a saved Game. A shell built as `Game(pk=<existing>)` is
`adding` too, and gets the `ValueError`: the verb takes a fetched row.

**The boundary maps `RowNotHeld` to 404.** The catalog callers are not under
`answered()`, which catches every `django.db.Error` and would swallow the
`IntegrityError` that `submitted_game_or_form_error()` reads for constraint
sentences. So `games/writes/answers.py` gets one context manager,
`absent_as_404(subject)`, holding the `RowNotHeld` clause `answered()` has
today; `answered()` delegates to it, keeping the log text byte for byte. Two
callers wrap their write in `absent_as_404("game")`:

- `submitted_game_or_form_error()`, its whole `try` (Add Game, Edit Game);
- `release_on()` in `games/catalog_release.py`, its whole body, the read-back
  included (`POST /api/releases/`). Ninja answers `Http404` with 404. A
  Release that is gone at the read-back went with its Game, so the subject is
  `"game"`; the logged argument names the Release.

`docs/catalog.md`'s Permission section states the absence and the defect.

Unchanged: a shared, foreign or removed Game keeps its `GraphRefused` sentence.

## Tests

The autouse tracking fixture gives every Game a `PlayerGame`, whose `RESTRICT`
key refuses `game.delete()`. A test marked `untracked_games` gets no
`PlayerGame`, so `game.delete()` destroys the Game and cascades its Editions
and Releases, and the library stays alive, as in Add Game's delete.

- `tests/test_state_catalog_graph.py`: a destroyed Game raises `RowNotHeld`; an
  unsaved Game raises `ValueError`.
- `tests/test_catalog_addons.py` (or the add-on tests' file): `state_addon()`
  on a destroyed persisted Game raises `RowNotHeld`.
- `tests/test_catalog_submit.py`: `submitted_game_or_form_error()` on an edit
  form whose Game was destroyed raises `Http404`, for a main game and an add-on.
- `release_on()` on a destroyed Game raises `Http404`.
- `tests/test_command_answers.py` stays green: `answered()` still maps
  `RowNotHeld`.

## Follow-up issues to file

None.
