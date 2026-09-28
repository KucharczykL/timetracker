# Excluded-from-unfinished readers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** State `PlayerGame.excluded_from_unfinished` through `RecordPlayerGameFacts`, make the unfinished and dropped statistics and their links honour it, and give it a filter, a list column, a form control and a detail note.

**Architecture:** State the flag through the existing facts command and retire the single-fact command. Readers add one clause beside `Purchase.infinite`. UI follows `mastered` everywhere.

**Tech Stack:** Django 6, event-sourced commands (`games/events`), Python component system, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-28-issue-1315-excluded-from-unfinished-readers-design.md`

## Global Constraints

- Step 0: `git fetch && git rebase origin/main` before any edit.
- Drive everything through `make`; wrap pytest targets in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"` when another worktree runs a suite.
- Iterate with `make test ARGS="…"` / `make check-fast`; the gate is one full `make check` at the end.
- Before every commit: `make format`, `make lint-fix`, `make format-check`.
- UI wording, every screen: "Excluded from unfinished lists" / "Included in unfinished lists"; column header "Unfinished lists", cell `Excluded`; facet label "Excluded from unfinished".
- Comments: no issue refs, explain intent only.
- `Purchase.infinite` clauses stay; #733 removes them.

---

### Task 1: One command states three facts; retire the single-fact command

**Files:**
- Modify: `games/commands/playergame.py` (remove `SetPlayerGameExcludedFromUnfinished` :123-149; `RecordPlayerGameFacts` :190-240)
- Modify: `games/events/dispatch.py` (drop member :86-88; add value to `RETIRED_COMMAND_NAMES` :270)
- Modify: `games/writes/playergame.py` (import :20; `record_facts` :310-357; delete `set_excluded_from_unfinished` :359-379)
- Modify: `games/views/playergame_writes.py:38-58` (`record_facts_for_request`)
- Modify: `games/bulk_game_edit.py` (import :46; `GameEditStatement.records_facts` :88-91 removed; `_state` :270-305 one dispatch)
- Modify: `docs/superpowers/specs/2026-09-28-issue-1270-bulk-game-edit-design.md:39-40`
- Test: `tests/test_playergame_command.py`, `tests/test_command_dispatch.py:707`, `tests/test_projection_replay_gate.py`, `tests/test_bulk_game_edit.py`

**Interfaces:**
- Produces:
  - `RecordPlayerGameFacts(game_id: UUID, status: PlayerGameStatus | None = None, mastered: bool | None = None, excluded_from_unfinished: bool | None = None)`; `ValueError` when all three facts `None`.
  - `record_facts(actor, game, *, status=None, mastered=None, excluded_from_unfinished: bool | None = None, correlation_id, idempotency_key=None, source_metadata=None) -> CommandResult`
  - `record_facts_for_request(request, game, *, status=None, mastered=None, excluded_from_unfinished: bool | None = None, correlation_id) -> WriteAnswer`
  - `set_excluded_from_unfinished` and `SetPlayerGameExcludedFromUnfinished` no longer exist.

- [ ] **Step 1: Tests first.**
  - `test_playergame_command.py`: add `pytest.param({"excluded_from_unfinished": True}, …, id="exclusion")` to `FACTS` (read the existing two params' shape: fact dict, column read, event type). Every parametrised fact test now covers it. Delete the six `SetPlayerGameExcludedFromUnfinished` tests (:394-525) and the import; their cases (untracked, other library, unchanged, one key) are what `FACTS` already runs. Add: one command stating all three appends three events in order status, mastered, exclusion; all-`None` raises `ValueError`.
  - `test_command_dispatch.py::test_the_retired_names_are_pinned`: add `"library.playergame.set_excluded_from_unfinished"`.
  - `test_projection_replay_gate.py:166-183`: state the three flag changes through `RecordPlayerGameFacts(game_id=…, excluded_from_unfinished=…)`; drop the import.
  - `test_bulk_game_edit.py`: replace `set_excluded_from_unfinished(...)` calls (:378, :486, :517) with `record_facts(..., excluded_from_unfinished=...)`. Add: a row stating all three facts writes one idempotency record under the row's key (none under `<key>-excluded`); a row whose PlayerGame is missing gets tracked and the flag stated.
- [ ] **Step 2:** `make test ARGS="tests/test_playergame_command.py tests/test_command_dispatch.py tests/test_projection_replay_gate.py tests/test_bulk_game_edit.py -x"` → FAIL.
- [ ] **Step 3: Implement.**
  - Give all three fact fields `= None`. `__post_init__` checks all three; message names all three.
  - `build()`: third `if` after mastered, `PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.new(aggregate_id=tracked.pk, payload={"excluded_from_unfinished": …})`, no `effective_time` (the old command stated none).
  - Update the class docstring: status, mastery, exclusion.
  - `_state` in bulk edit: one `RowOutcome.of(record_facts(..., status=, mastered=, excluded_from_unfinished=, idempotency_key=idempotency_key, …))`; docstring "One dispatch". Keep `RowOutcome.either` (sessions use it).
  - Update the #1270 spec's two lines about `<key>-excluded`.
- [ ] **Step 4:** Rerun Step 2 → PASS. `make typecheck`.
- [ ] **Step 5:** Commit `refactor(playergame): state the exclusion through RecordPlayerGameFacts (#1315)`.

**Gotchas:**
- The fingerprint moves for every `RecordPlayerGameFacts`: expected, no `FINGERPRINT_VERSION` bump.
- `grep -rn "SetPlayerGameExcludedFromUnfinished\|set_excluded_from_unfinished\|PLAYERGAME_SET_EXCLUDED" games tests e2e` must be empty after (docs under `docs/superpowers/` may keep history).
- Refused-word check: `make vale` over changed files.

---

### Task 2: Filter field, quick facet, list column

**Files:**
- Modify: `games/filters.py:119, :167` (`GameFilter`)
- Modify: `common/components/quick_filter.py:91-115` (`QUICK_FACETS["games"]`)
- Modify: `games/views/game.py:229-285` (`game_list_columns`, `list_games` cells)
- Modify: `games/sorting.py:95-108` (`GAME_SORTS`)
- Test: `tests/test_filters.py` (or the GameFilter test file holding `mastered`), `tests/test_quick_filter_bar.py:639`, `tests/test_column_choice_lists.py`

**Interfaces:**
- Produces: `GameFilter.excluded_from_unfinished: BoolCriterion | None`; column key `unfinished_lists`; sort key `unfinished_lists`.

- [ ] **Step 1: Tests first.**
  - Filter: `GameFilter(excluded_from_unfinished=BoolCriterion(value=True))` over a library with one flagged and one plain game returns the flagged one; JSON round-trip via `parse_game_filter`. Mirror the existing `mastered` test.
  - `test_quick_filter_bar.py`: append `"excluded_from_unfinished"` to `ORDERS["games"]`; a filter naming it is quick-editable.
  - Column: games list hides `unfinished_lists` by default; shown after choosing it, a flagged row's cell reads `Excluded`; `?sort=unfinished_lists` orders flagged last/first without the unknown-sort warning.
- [ ] **Step 2:** `make test ARGS="<those files> -x"` → FAIL.
- [ ] **Step 3: Implement.** Field + `FilterField("tracked__excluded_from_unfinished", metadata_lookup="player_games__excluded_from_unfinished")`; `QuickFacet("excluded_from_unfinished", "Excluded from unfinished")` last in games list; `Column("Unfinished lists", "unfinished_lists", key="unfinished_lists", hidden_by_default=True)` after Created; cell `"Excluded" if game.tracked_excluded_from_unfinished else ""` appended after the Created cell (cell count must equal column count: `drop_columns` raises otherwise); `"unfinished_lists": SortSpec("tracked_excluded_from_unfinished")`.
- [ ] **Step 4:** Rerun → PASS; `make test ARGS="tests/test_filter_paths.py tests/test_paths_return_200.py tests/test_filter_tree_contract.py"`; `make ts-check` if element props changed (they should not).
- [ ] **Step 5:** Commit `feat(games): filter and list the exclusion from unfinished lists (#1315)`.

**Gotchas:**
- Builder field lists, facet templates and `games.E011` read `FilterField` metadata; run `make shell ARGS='-c "from django.core.management import call_command; call_command(\"check\")"'` or `make check-fast` to catch a check failure early.
- The filter-tree contract fixtures (`ts/elements/filter-tree/fixtures.json`) list no GameFilter fields by enumeration as far as reviewed; if a test enumerates fields, extend it rather than skip.

---

### Task 3: Statistics and their links leave an excluded game out

**Files:**
- Modify: `games/views/stats_data.py:216-311` (`compute_stats`)
- Modify: `games/views/stats_links.py:231-253` (`purchases_dropped`, `purchases_unfinished`, plus one helper)
- Modify: `tests/tracked_games.py`, `e2e/tracked_games.py` (`create_tracked_game` gains `excluded_from_unfinished: bool = False`, written in the same `update`)
- Modify: `docs/STATUSES.md:93-122`
- Test: `tests/test_stats_links.py`, `tests/test_stats_reads_the_projection.py` (or whichever of the `test_stats_*` files asserts figure values; pick the one that already asserts `purchased_unfinished_count`)

**Interfaces:**
- Consumes: `PlayerGame.excluded_from_unfinished` (column), `Game.objects.tracked_by`, `GameFilter.excluded_from_unfinished` (Task 2).
- Produces: `stats_links._not_excluded_from_unfinished() -> PurchaseFilter` (private helper); `create_tracked_game(..., excluded_from_unfinished=False)`.

- [ ] **Step 1: Tests first.**
  - `world` fixture in `test_stats_links.py` (~:87): add a playing game `create_tracked_game(..., status=PLAYING, excluded_from_unfinished=True)` with its own in-year single-game purchase; an abandoned flagged game with a purchase (dropped case); a two-game bundle purchase `games.set([flagged, playing_other])`. Existing `test_dropped_matches_count` and `test_unfinished_matches_count` then prove parity, per year and all-time; add `test_unfinished_leaves_out_a_bundle_holding_an_excluded_game` asserting the bundle's pk is absent from both the stat queryset and the link's.
  - Figure test: a flagged game's purchase leaves `purchased_unfinished_count`, `purchased_unfinished` and `dropped_count`; the same purchase with the flag off counts.
  - `test_stats_parity.py` needs no edit (every key stays `_unchanged`); run it.
- [ ] **Step 2:** `make test ARGS="tests/test_stats_links.py tests/test_stats_parity.py -x"` → FAIL.
- [ ] **Step 3: Implement.**
  - `compute_stats`: `excluded = _games_at_status`-style helper `_games_excluded_from_unfinished(library)` returning `Game.objects.tracked_by(library, tracked__excluded_from_unfinished=True)`; add `.filter(~Q(games__in=excluded))` to `unfinished` and `dropped`.
  - `stats_links`: helper returning `PurchaseFilter(game_filter=GameFilter(excluded_from_unfinished=BoolCriterion(value=True), match=RelationMatch.NONE))`; append to `purchase_filter.AND` in both builders (dropped already sets `AND = [_abandoned_or_refunded()]` — append, don't replace). Uses Task 2's `GameFilter.excluded_from_unfinished`.
  - `docs/STATUSES.md`: Unfinished and Dropped rules and summary table name the flag beside `infinite`.
- [ ] **Step 4:** Rerun → PASS; also `make test ARGS="tests/test_stats_content_links.py tests/test_stats_finish_reads.py tests/test_library_api_isolation.py"`.
- [ ] **Step 5:** Commit `feat(stats): leave excluded games out of unfinished and dropped (#1315)`.

**Gotchas:**
- Do not touch `_not_finished_game`: its `ANY` match would keep a bundle the figure drops.
- Confirm the NONE relation compiles through `context.queryset_for(Game)` = `tracked_by(library)` (`games/filters.py:~1085`); an untracked game is then kept, as the figure keeps it.
- New world rows may shift other counts in the same file (total purchases, games played). Put the flagged purchases where no other assertion counts them, or update those expected numbers deliberately.

---

### Task 4: Game form checkbox and detail note

**Files:**
- Modify: `games/forms.py:2100-2123` (`GameForm`)
- Modify: `games/views/game.py:364-369, :487-492` (Add/Edit call `record_facts_for_request`), `:970-983` (detail Status row)
- Test: `tests/test_game_form_page.py`, `tests/test_rendered_pages.py` (or the detail-page test that asserts the crown), `e2e/test_game_form_catalog_e2e.py` (or a new `e2e/test_excluded_from_unfinished_e2e.py`)

**Interfaces:**
- Consumes: `record_facts_for_request(..., excluded_from_unfinished=...)` from Task 1; `create_tracked_game(..., excluded_from_unfinished=...)` from Task 3.

- [ ] **Step 1: Tests first.**
  - Form page: Edit Game for a flagged game renders the box checked; posting with it unchecked appends one `excluded_from_unfinished_changed` event with `False` in the same correlation as any status change; Add Game with it checked creates a flagged row.
  - Detail: a flagged game's Status row contains "Excluded from unfinished lists"; a plain game's does not.
  - e2e: open Edit Game, tick the box, save; detail shows the note (wait on the redirected page before any ORM read); stats page for the year no longer lists the game's purchase under unfinished.
- [ ] **Step 2:** Run the focused tests → FAIL.
- [ ] **Step 3: Implement.** `excluded_from_unfinished = forms.BooleanField(required=False, label="Excluded from unfinished lists")`; append to `field_order` after `mastered`; `self.initial.setdefault("excluded_from_unfinished", tracked.excluded_from_unfinished)`. Both views pass `excluded_from_unfinished=form.cleaned_data["excluded_from_unfinished"]`. Detail: `_meta_row`'s one extra slot takes `Fragment("👑" if mastered else "", Span(class_=<muted text class used nearby>)["Excluded from unfinished lists"] if flagged else "")`.
- [ ] **Step 4:** Rerun → PASS; `make test-e2e ARGS="-k 'game_form or excluded'"`.
- [ ] **Step 5:** Commit `feat(games): state the exclusion from unfinished lists for one game (#1315)`.

**Gotchas:**
- Never run e2e while `make dev` is up.
- `make ts` only if a `.ts` changed (none planned).
- Look at the rendered page in the browser pane (light + dark) for the note's spacing, not only the assertion.

---

### Task 5: Gate and docs sweep

- [ ] `make vale`, `make format`, `make lint-fix`, `make format-check`.
- [ ] Full `make check` under the heavy-tests lock; read the exit code from the log, not a grep.
- [ ] CLAUDE.md: the PlayerGame model line and the #1270 bulk paragraph mention the flag's readers only if they now misstate something; otherwise leave them.
- [ ] Docs sweep per the usual rule after merge review: delete this plan, rewrite the spec timeless.
- [ ] Open the PR (merge-commit style), body closes #1315, links #1334 and #733.
