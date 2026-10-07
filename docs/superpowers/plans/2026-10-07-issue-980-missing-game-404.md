# Plan: a missing Game answers 404 (#980)

Spec: `docs/superpowers/specs/2026-10-07-issue-980-missing-game-404-design.md`.
Inline, TDD, one task at a time.

## Task 1 — `absent_as_404` in `games/writes/answers.py`

- Add `@contextmanager def absent_as_404(subject: SubjectNoun) -> Iterator[None]`
  holding today's `except RowNotHeld` clause (WARNING line, `Http404(f"No such
  {subject}.")`, `from error`). Log text unchanged.
- `answered()`: drop its `RowNotHeld` clause; nest `with absent_as_404(subject):
  yield` inside its `try`.
- Test: `tests/test_command_answers.py` existing `RowNotHeld` cases stay green;
  add one direct `absent_as_404` case (404, one WARNING, no traceback).

## Task 2 — `_writable_game` and the unsaved Game (`games/catalog_writes.py`)

- `_writable_game`: `.filter(pk=game_id).first()`; None → `RowNotHeld(f"Game
  {game_id} is not there to write; library {library.pk}.")`.
- `state_catalog_graph`: `if game._state.adding: raise ValueError(...)` before
  `_writable_game`.
- Tests in `tests/test_state_catalog_graph.py`, marked `untracked_games`:
  destroyed Game → `RowNotHeld`; `Game(library=..., name=...)` unsaved →
  `ValueError`.

## Task 3 — `state_addon` (`games/catalog_addons.py`)

- After the lock: `if persisted and stored is None: raise RowNotHeld(...)`,
  ahead of the kind branches.
- Test in the add-on tests file (`tests/test_catalog_addons.py`), `untracked_games`:
  inside `transaction.atomic()`, a fetched Game deleted, then `state_addon` →
  `RowNotHeld`, for main kind and add-on kind.

## Task 4 — `submitted_game_or_form_error` (`games/catalog_submit.py`)

- Wrap the whole `try` in `with absent_as_404("game"):`.
- Tests in `tests/test_catalog_submit.py` (already `transaction=True`), marked
  `untracked_games`: edit form bound and `is_valid()` first, Game deleted, then
  the call → `Http404`; once main, once add-on (`kind="dlc", parent=...`).
- Gotcha: the edit fixture may assume tracking; build the Game directly.

## Task 5 — `release_on` (`games/catalog_release.py`)

- Wrap the whole body (state, `try`, read-back) in `absent_as_404("game")`.
- Read-back: `.filter(pk=...).first()`; None → `RowNotHeld` naming the Release.
- Test: `release_on(library, game, platform)` after `game.delete()`
  (`untracked_games`) → `Http404`. Place beside existing `release_on` tests
  (`tests/test_release_api.py`).

## Task 6 — docs

- `docs/catalog.md` Permission: a Game that is gone is no refusal — the verb
  raises `RowNotHeld`, the callers answer 404; an unsaved Game is a
  `ValueError`.
- CLAUDE.md: `RowNotHeld` bullet notes the catalog's stale re-resolve.

## Gotchas

- `RowNotHeld` is a plain `Exception`: it passes `except ValidationError`
  clauses, which is why the wrappers enclose them.
- `answered()` catches `django.db.Error`; never use it around the catalog submit.
- Iterate with `make test ARGS=...` under the shared lock.
