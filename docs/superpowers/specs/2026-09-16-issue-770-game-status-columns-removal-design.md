# CLEAN-01: Remove legacy Game status and mastered fields

**Date:** 2026-09-16
**Issue:** https://github.com/KucharczykL/timetracker/issues/770
**Parent phase:** #601
**Precedent:** [CLEAN-02](2026-09-11-clean-02-legacy-table-removal.md),
[CLEAN-03](2026-09-16-issue-772-session-storage-removal-design.md)
**Status:** Draft

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

**The columns go.** Migration `0002_remove_game_status_and_mastered` counts,
in raw SQL, the games with a library whose column states anything but
`u`/`false` and that have no `PlayerGame` row on that (library, game); it
refuses when the count is not zero, then removes both fields. The count cannot
be nonzero on the deployment, which #676 backfilled, so the guard exists for a
database that skipped that release. `Game.Status`, `games/playergame_status.py`
and `tests/test_playergame_status_map.py` go with the columns: no letter is
read anywhere after this. `PlayerGameStatus`'s docstring stops contrasting
itself with letters. `GameForm` is untouched: its `status` and `mastered` are
plain fields that state `PlayerGame` facts through `record_facts`.

**Tests state the words.** A factory, `tracked_game(library, name, *,
status=PlayerGameStatus.UNPLAYED, mastered=False, **game_fields)`, creates the
Game, its `PlayerGame` and its one ordinary `Playthrough`, in `tests/` and
again in `e2e/`, because the two suites share no conftest and already
duplicate the autouse hook. That hook stays for the plain-create case and
seeds `UNPLAYED`/`False`. The 46 sites in 14 files that pass `status=` or
`mastered=` to a Game create move onto the factory. Two tests whose only
subject was that the column is ignored leave:
`test_a_completed_column_the_row_denies_counts_for_nothing` and
`test_a_link_lands_when_the_catalog_disagrees`. Five assertions that the
column stayed `u` after a refused write become assertions on the
`PlayerGame` row. The comment in `tests/test_field_widget.py` naming "five
Game.Status options" names the six words instead.

**The fixture is regenerated** from a fresh dump of the deployment, after the
migration applies to the copy. The anonymizer needs no edit: the serializer
stops emitting a column the model lost.

**Docs close out the promise.** CLAUDE.md's Game row and its PlayerGame
convention, `docs/STATUSES.md`, and the #678 spec's two "#770" hand-offs say
the columns are gone.

## Verification

- Full `make check` green on each commit, `e2e/` included.
- `make loadsample` into an empty database from the regenerated fixture;
  `make verify-replay-parity` and `make audit-uuid-identity` clean on it.
- `make verify-dump` green on the fresh dump; `make verify-baseline
  ARGS="--migrate"` green.
- `make render-pages` before and after on the restored dump: zero files
  expected to differ, because no page read the columns; any difference is
  attributed in the PR.

## Rollback

Not reversed after `0002` applies: Django's reverse re-adds two columns at
their defaults and the letters do not return, and nothing reads them. Before
that, `git revert`.
