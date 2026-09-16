# CLEAN-01: Remove legacy Game status and mastered fields — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, the default here) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop `Game.status` and `Game.mastered`, the `Game.Status` enum and the letter map, with the tests stating words and the sample fixture regenerated.

**Architecture:** Three commits, each green under `make check-fast`; the last two are one `make check` gate. Tests first, so the column loses its last readers before it goes. Migration and fixture land together because the committed fixture is loaded by a test.

**Tech Stack:** Django 6 migrations, pytest + pytest-playwright, `scripts/db_dump.py`, `manage.py anonymize_sample`.

**Spec:** `docs/superpowers/specs/2026-09-16-issue-770-game-status-columns-removal-design.md`

## Global Constraints

- Every command goes through `make` (`make test ARGS=…`, `make test-e2e`, `make check`). Never `direnv exec`, never raw `uv run`.
- Gate is full `make check`, `e2e/` included, read from a log with its exit code.
- Identifiers are whole words; comments state present intent, no issue numbers except forward TODOs.
- `make vale` is part of `make check`: `docs/vocabulary.md` refuses `fold`, `seam`, `tombstone`, `archive`, `heal`, and `delete` in the domain sense.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Step 0 of everything: `git fetch origin && git rebase origin/main`.

---

## Task 1: Tests state the words (commit 1)

**Files:**
- Create: `tests/tracked_games.py`, `e2e/tracked_games.py` (identical body; the suites share no conftest)
- Modify: `tests/conftest.py:233-289`, `e2e/conftest.py:49-105` (the autouse hook)
- Modify: the 43 create sites listed below, and the tests named under *Tests that leave or change*
- Modify: `tests/test_field_widget.py:45` comment

**Interfaces:**
- Produces:
  ```python
  def create_tracked_game(
      library: UserLibrary,
      name: str,
      *,
      status: PlayerGameStatus = PlayerGameStatus.UNPLAYED,
      mastered: bool = False,
      **game_fields,
  ) -> Game:
  ```
  Creates the `Game` (`library=library, name=name, **game_fields`), then `PlayerGame.objects.filter(library=library, game=game).update(status=status, mastered=mastered)`; when that update touches no row it raises `RuntimeError("No PlayerGame row to state facts on: is this test marked untracked_games?")`. Returns the game. The `Playthrough` comes from the hook, so the factory creates none.
- The hook: `player_status_for(instance.status)` becomes `PlayerGameStatus.UNPLAYED`, `instance.mastered` becomes `False`; the two `playergame_status` imports go. Docstrings drop the sentences naming `0033_playergame_baseline_backfill` and `backfill_library()`; say instead "games/views/game.py dispatches TrackGame, load_sample_data rebuilds the projection from the fixture's events, and a test is the third source of a game".

**Site list** (`Game.objects.create(... status=/mastered=)`; hook runs unless marked):

| File | Lines | Action |
|---|---|---|
| `e2e/test_filter_builder_e2e.py` | 75, 78, 143, 146, 187, 190, 222, 225, 329, 510, 513 | factory: `'f'`→`COMPLETED`, `'p'`→`PLAYED` |
| `e2e/test_custom_elements_e2e.py` | 25, 130 | `'u'`: drop the kwarg |
| `e2e/test_quick_filter_e2e.py` | 51, 57 | factory (`FINISHED`→`COMPLETED`); `UNPLAYED` site drops the kwarg |
| `tests/test_stats_links.py` | 49, 56, 59, 112, 499, 510 | factory (`RETIRED`→`RETIRED`, `ABANDONED`→`ABANDONED`) |
| `tests/test_library_reconciliation.py` | 76, 83, 90, 97 | factory |
| `tests/test_stats_content_links.py` | 53, 67 | factory |
| `tests/test_library_api_isolation.py` | 68, 76 | factory |
| `tests/test_game_detail_links.py` | 39 | factory |
| `tests/test_playergame_game_views.py` | 65 (`disagreeing_game`, `'u'`/`False`) | drop kwargs |
| `tests/test_playergame_game_views.py` | 149 (marked untracked) | drop kwargs; the test asserts the form offers `unplayed` with no row, still true |
| `tests/test_playergame_game_views.py` | 245 | becomes the factory's test, see below |
| `tests/test_playergame_view_cutover.py` | 49, 85, 131, 212, 235, 348, 380, 456 (module marked) | drop kwargs |
| `tests/test_playergame_write_path.py` | 52 (module marked) | the whole test leaves |
| `tests/test_playergame_history_read.py` | 71 (module marked) | drop kwarg |

Letter to word: `u`→`UNPLAYED`, `p`→`PLAYED`, `f`→`COMPLETED`, `r`→`RETIRED`, `a`→`ABANDONED`, the map `games/playergame_status.py` holds today. A site whose only letter is `u` with `mastered=False` needs no factory: the hook already states that.

**Tests that leave or change:**
- Leave: `tests/test_stats_reads_the_projection.py::test_a_completed_column_the_row_denies_counts_for_nothing` (25-44; also its "The only test that writes the column" comment), `tests/test_stats_links.py::test_a_link_lands_when_the_catalog_disagrees` (555-568), `tests/test_playergame_write_path.py::test_the_catalog_column_is_left_where_it_stood` (49-65).
- `tests/test_playergame_game_views.py::test_the_tracking_fixture_states_the_games_facts` (238-256) → rename `test_the_factory_states_the_games_facts`, body calls `create_tracked_game(owned_library, "Outer Wilds", status=PlayerGameStatus.COMPLETED, mastered=True)`, asserts the row; add beside it `test_the_factory_refuses_where_no_row_exists`, marked `untracked_games`, `pytest.raises(RuntimeError)`.
- `tests/test_playergame_view_cutover.py:143` `assert game.status == "u"` → `assert PlayerGame.objects.get(library=owned_library, game=game).status == PlayerGameStatus.UNPLAYED` (import `PlayerGame` if absent).
- `tests/test_library_api_isolation.py:283-284` → `shared_game` has no library, so the hook made it no row: `assert not PlayerGame.objects.filter(game=world["shared_game"]).exists()`; `game_b` was stated `COMPLETED` through the factory (line 76): `assert PlayerGame.objects.get(library=world["library_b"], game=world["game_b"]).status == PlayerGameStatus.COMPLETED`. Drop the two `refresh_from_db()` calls above them.
- `tests/test_playergame_write_path.py:64` and `tests/test_playergame_status_word_setters.py:48-50` (the `refresh_from_db` + tuple assert and its comment): remove the lines.
- `tests/test_playergame_status_word_setters.py:128` `Game.objects.filter(pk=game.pk).update(status="p")` and the docstring's "The catalog says played and" sentence: remove; the test keeps asserting the row.
- `tests/test_field_widget.py:45-46` comment → "status is a static enum: its six PlayerGameStatus words are pre-rendered,".

**Gotcha:** `tracked_game` is already a fixture name in three test modules; the factory is `create_tracked_game`, imported as a plain function, never a fixture.

**Steps:**
- [ ] Write `tests/tracked_games.py` and its two tests in `test_playergame_game_views.py`; run `make test ARGS="tests/test_playergame_game_views.py -x"` → the refusal test fails before the factory exists, passes after.
- [ ] Move every site in the table; run `make test ARGS="tests/test_stats_links.py tests/test_library_reconciliation.py tests/test_stats_content_links.py tests/test_library_api_isolation.py tests/test_game_detail_links.py tests/test_playergame_view_cutover.py tests/test_playergame_write_path.py tests/test_playergame_history_read.py tests/test_playergame_status_word_setters.py tests/test_stats_reads_the_projection.py -x"`.
- [ ] Copy the factory to `e2e/tracked_games.py`, move the three e2e files; run `make test-e2e` (whole e2e; `ARGS` does not scope it).
- [ ] Edit both hooks to constants; `grep -rn playergame_status tests e2e` returns only `tests/test_playergame_status_map.py`.
- [ ] `make check-fast` green; commit `test: state a game's facts through the projection, not the catalog letter`.

## Task 2: The columns go, the fixture follows (commit 2)

**Files:**
- Modify: `games/models.py:365-388` (delete `class Status` and both columns), `:1396-1400` (`PlayerGameStatus` docstring: "Full words, so a recorded payload never needs upcasting.")
- Delete: `games/playergame_status.py`, `tests/test_playergame_status_map.py`
- Create: `games/migrations/0007_remove_game_status_and_mastered.py` via `make makemigrations ARGS="games --name remove_game_status_and_mastered"`; expect exactly two `RemoveField` operations and a dependency on `0001_squashed_0006_remove_session`
- Regenerate: `games/fixtures/sample.yaml.gz`

**Interfaces:** none produced; `Game` loses two attributes, `Game.Status` stops existing.

**Fixture regeneration** (needs `PROD_SSH_HOST` and `PROD_DB_CONTAINER` in `.env`; the user fetches):
1. `make fetch-dump` → `.dumps/<newest>`.
2. `make restore-dump` → prints `DATABASE_URL` of `timetracker_restore_verify`.
3. `make migrate DATABASE_URL=<that url>` → applies `0007` to the copy.
4. `make anonymize-sample USER=<prod username> DATABASE_URL=<that url>` → rewrites `games/fixtures/sample.yaml.gz`. `zcat games/fixtures/sample.yaml.gz | grep -c '^    status:'` must be 0 and `grep -c '^    mastered:'` 0; `grep -c 'model: games.game$'` is the deployment's game count.
5. `make drop-dump`.

**Verification in this task:**
- `make test ARGS="tests/test_library_commands.py -x"` green on the new fixture (it loads the committed file).
- `make loadsample USER=<dev user>` into an empty database (`make ensure-postgres` fresh, or drop and recreate), then `make verify-replay-parity` and `make audit-uuid-identity` clean.
- `grep -rn "Game.Status\|playergame_status" games common timetracker tests e2e` returns nothing.
- `make check-fast` green; commit `feat: remove the Game status and mastered columns`.

**Gotcha:** the migration and the fixture are one commit; a commit holding one without the other is red on `tests/test_library_commands.py`. `makemigrations` runs with `--noinput` through the Make target; if the autodetector asks anything, the model edit is wrong.

## Task 3: Docs and the gate (commit 3)

**Files:**
- Modify: `CLAUDE.md:155` (Game row: drop the sentence from "`status` (u/p/f/r/a)" on), `CLAUDE.md:947-952` (convention: "never assign `Game.status`" → the columns no longer exist; the command is the only way to state either fact)
- Modify: `docs/STATUSES.md:29-31, 39` (the column "which #770 drops" → is gone; drop "Do not assign `Game.status` directly")
- Modify: `docs/superpowers/specs/2026-08-28-issue-678-playergame-read-cutover-design.md:9, 343-344, 410-411` (each "#770 removes/inherits" → "#770 removed them")
- Modify: the #770 spec's `**Status:** Draft` → `Done`, and its Verification section gets the measured figures (dump date, files rendered, files differing)
- Leave alone: #676, #677, CLEAN-02 specs.

**Evidence to collect (on the restored dump, before dropping it in Task 2 step 5 — order the tasks' commands accordingly):**
- `make render-pages ARGS="--user <prod username> --out /tmp/…/before"` at `main`, same at the branch head with `0007` applied; `diff -r` → expected empty.
- `make verify-dump` green. `make verify-baseline ARGS="--migrate"` green.

**Steps:**
- [ ] Edit the four docs; `make vale` clean.
- [ ] Full `make check 2>&1 | tee /tmp/…/check.log; echo exit=$?` → exit 0, read the log's tail, not a grep.
- [ ] Commit `docs: record the Game status column removal (#770)`; push; PR titled "Remove the legacy Game status and mastered columns (#770)" with the evidence table in the body.
