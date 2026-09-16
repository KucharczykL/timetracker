# CLEAN-01: Remove legacy Game status and mastered fields

**Date:** 2026-09-16
**Issue:** https://github.com/KucharczykL/timetracker/issues/770
**Parent phase:** #601
**Precedent:** [CLEAN-02](2026-09-11-clean-02-legacy-table-removal.md),
[CLEAN-03](2026-09-16-issue-772-session-storage-removal-design.md)
**Status:** Done

## Problem

`Game.status` and `Game.mastered` had no writer and no reader. The
`PlayerGame` projection is the record of both facts. The five-letter
`Game.Status` enum, a letter-to-word map and two test hooks kept the columns
alive. The sample fixture carried both fields on every game row, and
`loaddata` refuses a field the model does not have.

## Design

Migration `0007_remove_game_status_and_mastered` removes the two fields. It
has no guard. A database that did not run the #676 backfill cannot apply
`0001_squashed_0006_remove_session`, so it cannot reach `0007`.

`Game.Status`, `games/playergame_status.py` and its test are removed. No code
reads a letter off a `Game`. `GameForm` keeps its `status` and `mastered`
form fields. They state `PlayerGame` facts through `record_facts`.

Tests state words. The autouse hook `_track_created_games` seeds each created
game one `PlayerGame` row, `UNPLAYED` and unmastered, and one run.
`create_tracked_game(library, name, *, status, mastered, **game_fields)`
creates the game and updates that row. It refuses when no row exists. It
lives in `tests/tracked_games.py` and again in `e2e/tracked_games.py`,
because the suites share no conftest. Under `untracked_games` the hook does
not run, so those sites only lose their kwargs. Tests whose subject was the
column are removed. Assertions that read the column after a refused write
read the `PlayerGame` row. `TestChoiceCriterionAgainstDB` and the bool
comparison-column examples read `PlayerGame`.

The sample fixture is regenerated from a dump of the deployment after `0007`
applies to the copy. The anonymizer needs no edit. The migration and the
fixture land in one commit, because a test loads the committed fixture.

CLAUDE.md, `docs/STATUSES.md` and the #678 specification say the columns are
gone.

## Verification

Measured on the 2026-09-16 post-#772 dump, 860 game rows:

- Every game with a letter had a `PlayerGame` row.
- `make render-pages` at `main` and after `0007`: 6 of 1,702 files differ.
  All six are filter-builder pages. Each lost the 14 comparison columns
  rooted at the two catalog columns.
- `make loadsample` into an empty database: 12,299 objects, 7,066 events
  replayed. Replay parity and the identity audit are clean. A second load is
  refused.
- `make verify-dump` is green. `make verify-baseline ARGS="--normalize
  cutover.sql --migrate"` is green. The normalize file is the history
  statement in [Squashing](../../migration-squash.md).
- Full `make check` is green, `e2e/` included.

## Rollback

`git revert` before `0007` applies. After it applies, the reverse re-adds
two columns at `u` and `false`. The letters do not return, and nothing reads
them.
