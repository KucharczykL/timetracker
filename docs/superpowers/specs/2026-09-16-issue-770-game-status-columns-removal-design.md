# CLEAN-01: Remove legacy Game status and mastered fields

**Date:** 2026-09-16
**Issue:** https://github.com/KucharczykL/timetracker/issues/770
**Parent phase:** #601
**Precedent:** [CLEAN-02](2026-09-11-clean-02-legacy-table-removal.md),
[CLEAN-03](2026-09-16-issue-772-session-storage-removal-design.md)
**Status:** Done

## Problem

`Game.status` and `Game.mastered` are two columns nothing writes and nothing
reads. #676 recorded each library's letters as events, #678 D2 moved every
read onto the `PlayerGame` projection, and #688's replay parity gate is green.
What remains is the schema, the five-letter `Game.Status` enum, the
letter-to-word map in `games/playergame_status.py`, and two test conftests
that seed the projection from the letters a test writes on the catalog row.
The sample fixture carries the two fields on every one of its 860 game rows,
and `loaddata` refuses a field the model does not have.

## Design

**The columns go.** Migration `0007_remove_game_status_and_mastered` removes
both fields; Django numbers on from the squash it follows. No index or constraint names them. The deployment's letters are
already events: #676 recorded them, and a database that never ran that
backfill cannot apply `0001_squashed_0006_remove_session` either, so no guard
stands in front of the drop. `Game.Status`, `games/playergame_status.py` and
`tests/test_playergame_status_map.py` go with the columns: no letter is read
off a `Game` after this. `PlayerGameStatus`'s docstring stops contrasting
itself with letters. `GameForm` is untouched: its `status` and `mastered` are
plain fields that state `PlayerGame` facts through `record_facts`.

**Tests state the words.** The autouse `_track_created_games` hook stays and
seeds `UNPLAYED`/`False` on every Game a test creates, a constant where it
read the letter. A factory, `tracked_game(library, name, *,
status=PlayerGameStatus.UNPLAYED, mastered=False, **game_fields)`, creates
the Game and then `update()`s the row the hook made, refusing when no row
exists: one code path, no second create under `unique_library_player_game`.
It lives in `tests/` and again in `e2e/`, because the two suites share no
conftest and already duplicate the hook. Both hooks' docstrings stop naming
migration `0033` and `backfill_library()`, neither of which exists.

43 Game creates in 12 files pass `status=` or `mastered=`. Where the hook
runs, the site moves onto the factory. Under `untracked_games`
(`tests/test_playergame_view_cutover.py`, `test_playergame_write_path.py`,
`test_playergame_history_read.py`, and one test in
`test_playergame_game_views.py`) the letter reached nothing, so the kwargs
drop and no row is created. One stray `update(status="p")` in
`test_a_session_marks_an_unplayed_game_played` drops; the test keeps its
projection assertion. Three `get_or_create` fixtures in `tests/test_filters.py`
carried a letter in `defaults`, and `TestChoiceCriterionAgainstDB` read the
column back: both now state and read `PlayerGame.status`.

Tests whose subject was the column leave:
`test_a_completed_column_the_row_denies_counts_for_nothing`,
`test_a_link_lands_when_the_catalog_disagrees`,
`test_the_catalog_column_is_left_where_it_stood`.
`test_the_tracking_fixture_states_the_games_facts` becomes the factory's own
test. Three assertions that the column stayed `u` after a refused write
(`test_playergame_view_cutover.py:143`,
`test_library_api_isolation.py:283-284`) become assertions on the
`PlayerGame` row; two that followed a successful write
(`test_playergame_write_path.py:64`,
`test_playergame_status_word_setters.py:50`) repeat the row assertion above
them and go. The comment in `tests/test_field_widget.py` naming "five
Game.Status options" names the six words instead. Component tests that pass
`status="u"` to a `SimpleNamespace` stay: they read no Game.

**The fixture is regenerated** from a fresh dump of the deployment, after
`0002` applies to the copy, and lands in the same commit as the migration:
`tests/test_library_commands.py` loads the committed fixture, and Django's
deserializer refuses a field the model lacks, so the two cannot be split.
The anonymizer needs no edit: the serializer stops emitting a column the
model lost. The fixture's letters were inert already; the loader rebuilds
the projection from its events.

**Docs close out the promise.** CLAUDE.md's Game row and its PlayerGame
convention, `docs/STATUSES.md`, and the three "#770" hand-offs in the #678
spec say the columns are gone. The #676, #677 and CLEAN-02 specs record
what was true when they ran and are left as they stand.

## Verification

Measured on the 2026-09-16 post-#772 dump of the deployment, 860 game rows
(letters u 258, p 95, f 194, r 22, a 291), every one with a `PlayerGame` row:

- Full `make check` green on each commit, `e2e/` included.
- `make loadsample` into an empty database from the regenerated fixture:
  12,299 objects, 7,066 events replayed into 860 `PlayerGame`, 874 runs and
  2,812 sessions; `make verify-replay-parity` and `make audit-uuid-identity`
  clean; a second load refused with a sentence.
- `make verify-dump` green: the dump restores and `0007` applies.
  `make verify-baseline ARGS="--normalize cutover.sql --migrate"` green,
  seven catalogs identical; the normalize file is the history statement in
  [Squashing](../../migration-squash.md), which the deployment still owes.
- `make render-pages ARGS="--user NAME --out DIR"` at `main` and after
  `0007` on the restored copy: 6 of 1,702 files differ, all six filter-builder
  pages, which lost the 14 comparison columns rooted at the two catalog
  columns (`status`, `mastered` and their twelve relation paths). No other
  page changed.

## Rollback

Not reversed after `0007` applies: Django's reverse re-adds two columns at
`u` and `false`, the letters do not return, and nothing reads them. Before
that, `git revert`.
