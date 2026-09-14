# Playtime reads implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every playtime figure comes from one interface with two sources;
every caller moves onto it; `Game.playtime`, its signal and its `_AFTER_STAMP`
entry are gone; a parity command compares the sources.

**Architecture:** `games/reads/player_sessions.py::library_sessions` is the one
projection scope. `games/reads/playtime/` holds `PlaytimeSource`,
`FilteredPlaytimeSource` and `FullPlaytimeSource` protocols, `legacy.py` over
`Session` (full), `projection.py` over `PlayerSession` (base only), and an
`__init__.py` that binds `SOURCE: FullPlaytimeSource = legacy` and states the
NULL policy once. Callers import only the package. #702 flips `SOURCE`; mypy
refuses the flip until `projection.py` is full.

**Tech Stack:** Django 6 / Python 3.14 / PostgreSQL 18, pytest + pytest-xdist.

**Spec:** [docs/superpowers/specs/2026-09-14-issue-697-playtime-reads-design.md](../specs/2026-09-14-issue-697-playtime-reads-design.md)
— read it first; every "why" lives there and is not repeated here.

## Global constraints

- Run everything through `make`. Never `direnv exec .`, never bare `uv run` /
  `pytest`. Focused runs: `make test ARGS="tests/test_playtime_sources.py -x"`.
- Iterate with `make check-fast`; the gate before "done" is the full
  `make check`, e2e included. Never run e2e while `make dev` is up.
- Python 3.14 only. `except A, B:` (PEP 758) is valid here; ruff formats to it.
- Never write to a `GeneratedField` (`duration_total`, `effective_duration`,
  `effective_day`, `sort_instant`).
- Nothing destroys a row: `remove()` / `restore()` from `games/removal.py`.
- No `QuerySet.iterator()`; `tests/test_iterator_guard.py` walks `games/`.
- Unabbreviated identifiers; named compound types (`type DayInterval = …`,
  `PlatformPlaytime`, `MonthPlaytime`).
- Comments explain intent only; no issue or PR references in code comments.
  Docstrings in the terse house style of `games/reads/playthrough_runs.py`.
- `make vale` is part of `make check`.
- Rebase onto `origin/main` before the first edit.

## Reference material

- `games/reads/playthrough_runs.py::library_runs` — the scope shape: library
  beside the parent's, every mark stated.
- `games/reads/playthrough_completions.py` — `YearScope`, correlated
  `Subquery` builders.
- `games/models.py:1148-1167` (`SessionQuerySet`), `:1730-1741`
  (`PlayerSessionQuerySet`), `:1787-1826` (the three generated columns).
- `games/views/game.py:150-180` (`list_games`'s `windowed_playtime`),
  `:608-627` (`_game_overview_metrics`), `:800-807` (the hours popover).
- `games/views/stats_data.py:140-150, 277-300, 305-315, 355-365`;
  `games/views/general.py:45-75` (`model_counts`).
- `games/sorting.py:95` (`GAME_SORTS["playtime"]`).
- `games/management/commands/preflight_sessions.py` — scope resolution and
  `--day-zone` for the parity command.
- `games/management/commands/anonymize_sample.py:679-681` — the gzip settings.
- `tests/test_playersession_projection.py` — building a projection row per mode.

## File structure

| path | change |
|---|---|
| `games/reads/player_sessions.py` | create: `library_sessions` |
| `games/reads/playtime/__init__.py` | create: `PlaytimeSource`, named types, `SOURCE = legacy`, public delegating functions |
| `games/reads/playtime/legacy.py` | create: the protocol over `Session` |
| `games/reads/playtime/projection.py` | create: the protocol over `PlayerSession` |
| `games/reads/playtime_parity.py` | create: `PlaytimeFigure`, `playtime_figures`, `differing` |
| `games/management/commands/verify_playtime_parity.py` | create |
| `games/models.py` | `GameQuerySet.annotated_for_filtering` registers the `playtime` alias; `Game.playtime` removed |
| `games/migrations/0003_remove_game_playtime.py` | generated |
| `games/sorting.py` | `GAME_SORTS["playtime"]` orders by the `total_playtime` alias |
| `games/views/game.py`, `games/views/stats_data.py`, `games/views/general.py` | callers onto the package; `StatsData`'s three playtime keys typed |
| `games/views/stats_content.py` | reads `PlatformPlaytime` / `MonthPlaytime` attributes instead of dict keys |
| `games/signals.py`, `games/removal.py` | the recalculation and its `_AFTER_STAMP` entry removed |
| `games/fixtures/sample.yaml.gz` | `playtime` key removed from `games.game` records |
| `Makefile` | `verify-playtime-parity` target |
| `tests/test_player_sessions.py`, `tests/test_playtime_sources.py`, `tests/test_playtime_parity.py` | create |
| `tests/test_signals.py`, `tests/test_removal.py`, `tests/test_api.py`, `tests/test_retention.py`, `tests/test_sorting.py:228` | restated |
| `CLAUDE.md` | swept |

Dispatch Tasks 1–3 to one implementer, Tasks 4–5 to a second. The controller
owns Tasks 6–7 and `make check`; a task runs `make check-fast` at most.

---

### Task 0: Land the documents

- [x] The spec and this plan are the first commit on the issue branch,
      approved before Task 1. Implementation commits land on the same branch,
      and one pull request, #1065, carries both.

---

### Task 1: The scope

**Files:** create `games/reads/player_sessions.py`; test `tests/test_player_sessions.py`.

```python
def library_sessions(library: UserLibrary) -> PlayerSessionQuerySet
```

- [ ] **Step 1: Failing tests**

| test | asserts |
|---|---|
| `test_the_scope_counts_a_live_session_of_each_mode` | three rows |
| `test_the_scope_hides_a_removed_session` | own mark |
| `test_the_scope_hides_a_session_under_a_removed_run` | run mark |
| `test_the_scope_hides_a_session_under_a_removed_tracked_game` | `PlayerGame` mark |
| `test_the_scope_hides_a_session_under_a_removed_catalog_game` | `remove(game)` |
| `test_the_scope_counts_a_session_in_the_imported_history_bucket` | run `kind` is not narrowed |
| `test_the_scope_reads_one_library` | a row whose `library` differs from its run's is not counted, and neither is the run-side mismatch |

- [ ] **Step 2: Implement** as `library_runs` does: `library`, `playthrough__library`, `removed_at__isnull`, `playthrough__removed_at__isnull`, `playthrough__player_game__removed_at__isnull`, `playthrough__player_game__game__removed_at__isnull`.
- [ ] **Step 3:** `make test ARGS="tests/test_player_sessions.py -x"`.

---

### Task 2: The interface and its two sources

**Files:** create the `games/reads/playtime/` package; test `tests/test_playtime_sources.py`.

**Interfaces produced:** the three protocols, `PlatformPlaytime`,
`MonthPlaytime`, `DayInterval` exactly as the spec's "The interface" states,
and the public functions of its NULL-policy table in `__init__.py`.

Module-as-protocol under this project's mypy is verified (spec review, mypy
1.20.2): a mismatched module is rejected with a per-member diff. No runtime
signature test.

- [ ] **Step 1: Failing tests.** Parametrize over both sources where a row of
      each table is built; build the legacy row and its projection twin in
      one helper per mode.

| test | asserts |
|---|---|
| `test_every_scalar_figure_is_zero_for_an_empty_library` | both sources' scalar members and the package's never-NULL functions; never `None` |
| `test_the_sum_is_null_for_an_unplayed_game` | `playtime_sort_key` and `playtime_matching` annotate NULL; `playtime_by_game` annotates zero |
| `test_a_twin_of_each_mode_gives_equal_figures` | every member, both sources; Corrected twin states the legacy total |
| `test_a_running_timed_row_counts_zero` | both sources |
| `test_the_projection_reads_the_stored_day` | Timed row started 2025-12-31 23:30 UTC with `day_zone="Europe/Prague"` is 2026; `timezone.override(UTC)` changes nothing |
| `test_a_duration_only_row_lands_on_its_written_day` | year, month, day window |
| `test_the_legacy_source_reads_the_active_zone` | the same instant moves year under `timezone.override` |
| `test_a_day_window_is_inclusive` | both ends, both sources |
| `test_playtime_by_game_never_counts_another_library` | two libraries tracking one shared catalog game, both sources |
| `test_the_legacy_source_honours_a_session_filter` | `SessionFilter(device=…)` narrows `summed_by_game_matching`; `playtime_matching(library, None)` equals the total |
| `test_summed_by_game_over_no_library_is_empty` | `library=None` compiles over `Session.objects.none()` / `PlayerSession.objects.none()` and sums nothing, even with a shared-catalog game holding sessions |
| `test_the_package_answers_from_the_legacy_source` | `games.reads.playtime.SOURCE is legacy` |

- [ ] **Step 2: Implement.** Sources answer sums; only `__init__.py` coalesces.
      Legacy: `Session.objects.for_library(library)` (or `.none()` for no
      library), `timestamp_start__year`, `TruncMonth("timestamp_start")`,
      midnight ranges under the active zone as `model_counts` builds them,
      `Sum("duration_total")`, `summed_by_game_matching` compiling
      `session_filter.to_q(filter_query_context_for_library(library))`.
      Projection: `library_sessions(library)`, `effective_day__year`,
      `TruncMonth("effective_day")`, `effective_day__range`,
      `Sum("effective_duration")`, and no `summed_by_game_matching`.
      `summed_by_game` is
      `Subquery(scope.filter(<game path>=OuterRef("pk")).values(<game path>).annotate(total=Sum(…)).values("total"))`
      with `output_field=DurationField()`.
- [ ] **Step 3: Prove the flip guard.** In a scratch file, bind
      `SOURCE: FullPlaytimeSource = projection` and confirm `make typecheck`
      names the missing member; then remove the scratch file.
- [ ] **Step 4:** `make test ARGS="tests/test_playtime_sources.py -x"`, `make typecheck`.

---

### Task 3: Every caller onto the interface

**Files:** `games/models.py` (`annotated_for_filtering`), `games/sorting.py`,
`games/views/game.py`, `games/views/stats_data.py`,
`games/views/stats_content.py`, `games/views/general.py`.
Tests: `tests/test_filters.py`, `tests/test_sorting.py`, existing stats,
stats-link, rendered-page and navbar tests.

- [ ] **Step 1: Failing tests**

| test | asserts |
|---|---|
| `test_playtime_hours_reads_the_live_sessions` (test_filters) | `GREATER_THAN 1` through `filter_query_context_for_library` on `tracked_by(library)` keeps the played game; a removed session stops counting |
| `test_playtime_hours_zero_matches_an_unplayed_game` | `EQUALS 0` |
| `test_playtime_hours_is_null_matches_an_unplayed_game` | `IS_NULL` maps to `= 0` in `duration_hours_to_q`; `NOT_NULL` keeps only the played game |
| `test_playtime_hours_inside_a_game_filter_relation` | nested `game_filter` compiles and executes |
| `test_the_playtime_alias_is_not_selected` | the SQL of a bare `tracked_by(library)` names no session table |
| `test_the_playtime_sort_reads_one_library` (test_sorting) | a shared catalog game's other-library sessions do not move its rank |
| `test_an_unplayed_game_sorts_last_both_ways` (test_sorting) | `playtime` and `filtered_playtime`, ascending and descending |
| restate `tests/test_sorting.py:228` | sort `tracked_by(library)` with the `total_playtime` alias registered, not a bare `Game.objects.all()` |
| `test_view_game_states_the_interface_figure` (test_rendered_pages) | the popover equals `game_playtime(library, game)` and drops a removed session |
| `test_the_navbar_without_a_library_is_zero` | an anonymous page renders; no source call |

- [ ] **Step 2: Implement.** Replace each row of the spec's "The callers"
      table. `GAME_SORTS["playtime"]` becomes `SortSpec("total_playtime")`;
      `list_games` registers `total_playtime=playtime_sort_key(library)` with
      `.alias()` and annotates
      `filtered_playtime=playtime_matching(library, session_filter)`, passing
      the parsed `game_filter.session_filter` (or `None`) instead of the
      compiled `Q`. Top games annotate `Game.objects.visible_to(library)` with
      `playtime_by_game(library, year=year)` and keep it above zero. Type
      `StatsData`'s `top_10_games_by_playtime`, `total_playtime_per_platform`
      and `month_playtimes`; `stats_content` reads attributes. No view imports
      `legacy` or `projection` directly.
- [ ] **Step 3:** Focused runs green: `tests/test_filters.py -k playtime`,
      `tests/test_sorting.py`, `tests/test_stats_links.py`,
      `tests/test_rendered_pages.py`, `tests/test_quick_filter_bar.py`. The
      existing stats and stats-link tests are not edited: an edit there means
      a figure moved.

---

### Task 4: Remove the column, the signal, the entry, the fixture key

**Files:** `games/models.py` (`Game.playtime`), `games/signals.py`,
`games/removal.py`, `common/components/domain.py` (the docstring sentence),
`games/api.py:694` (the comment), `games/fixtures/sample.yaml.gz`; migration
via `make makemigrations ARGS="games --name remove_game_playtime"`.
Tests: `tests/test_signals.py`, `tests/test_removal.py`, `tests/test_api.py`,
`tests/test_retention.py`.

- [ ] **Step 1: Restate the tests first**

| test | becomes |
|---|---|
| `test_signals.py::RawFixtureLoadTest::test_playtime_from_the_fixture_survives_the_load` | removed; nothing recomputes on load |
| `test_removal.py::test_removing_a_session_drops_the_playtime` | `game_playtime(library, game)` drops to zero |
| `test_api.py::test_session_patch_recalcs_playtime_via_signal` | the PATCH grows `game_playtime` |
| `test_retention.py:313` `LibraryState.other_game_playtime` | reads `game_playtime` for the bystander; check `populate()` has the bystander's library in scope, and pass it through if not |
| new in `test_removal.py` | `_AFTER_STAMP` has no `Session` entry; `remove(session)` issues one `UPDATE` |

- [ ] **Step 2: Remove and migrate.** Drop the field, both signal functions
      and their now-unused imports, the `Session` entry and its import in
      `removal.py`. Read the generated migration: one `RemoveField`.
      `make migrate`.
- [ ] **Step 3: Strip the fixture key.** A scratch script in the session
      scratchpad, never committed: `gzip.decompress`, drop the `playtime:`
      line inside each `games.game` record's `fields` at the text level,
      `gzip.compress(payload, compresslevel=9, mtime=0)`. Check the
      decompressed diff removes exactly 859 lines and nothing else.
      `make loadsample` into an empty database with the loader unchanged.
- [ ] **Step 4:** `make check-fast`. `grep -rn "\.playtime\b\|recalculate_playtime" games common timetracker --include=*.py` is empty.

---

### Task 5: The parity figures and the command

**Files:** create `games/reads/playtime_parity.py`,
`games/management/commands/verify_playtime_parity.py`; `Makefile` beside
`verify-replay-parity`; test `tests/test_playtime_parity.py`.

```python
class PlaytimeFigure(NamedTuple):
    scope: str            # "all-time", "year 2025", "game <name>", "platform <name> 2025", "month 2025-03", "today", "last 7 days"
    legacy: timedelta
    projection: timedelta

def playtime_figures(library: UserLibrary, zone: ZoneInfo) -> list[PlaytimeFigure]
def differing(figures: Sequence[PlaytimeFigure]) -> list[PlaytimeFigure]
```

`playtime_figures` calls both source modules through the protocol only, under
`timezone.override(zone)`; years are the union of `played_years`, games and
platforms the union of what either source reports, missing entries zero.

- [ ] **Step 1: Failing tests**

| test | asserts |
|---|---|
| `test_every_figure_agrees_for_a_twin_of_each_mode` | `differing(...) == []` |
| `test_a_day_across_a_year_boundary_is_named` | one twin's `stated_day` in the next year → the differing scopes name both years |
| `test_the_empty_projection_differs_on_every_non_zero_figure` | no twins |
| `test_the_command_exits_non_zero_on_a_difference` | `CommandError` |
| `test_the_command_reads_the_day_zone_override` | `--day-zone Asia/Tokyo` moves the legacy year of a 23:30 UTC row |

- [ ] **Step 2: Implement.** Scope resolution copied from `preflight_sessions.py`.
      One line per figure, both values, then `N figures differ`; `CommandError`
      when N > 0. Makefile:

```make
# Read-only: every playtime figure from both sources.
# Usage: make verify-playtime-parity ARGS="--all-libraries"
verify-playtime-parity: ensure-postgres
	uv run --frozen python manage.py verify_playtime_parity $(ARGS)
```

- [ ] **Step 3:** `make test ARGS="tests/test_playtime_parity.py -x"`.

---

### Task 6: Rehearse on a restored copy (controller)

**Files:** none committed.

- [ ] `make fetch-dump` if `.dumps/` is empty (needs `PROD_SSH_HOST` /
      `PROD_DB_CONTAINER` in `.env`); `make restore-dump`, note the URL.
- [ ] Before migrating, the column-drift probe: per game, `Game.playtime`
      against `legacy.game_playtime`. Record every differing game in the issue.
- [ ] Before migrating, record every figure `legacy` states for the library
      on `main`'s code; after checking out the branch and migrating, record
      them again. The two lists are equal — the production form of "every
      figure equal before and after".
- [ ] `make verify-playtime-parity ARGS="--all-libraries"` against the copy:
      every non-zero figure differs, projection side zero. Drop the copy.

---

### Task 7: Documentation, the gate, the wave follow-through (controller)

- [ ] `CLAUDE.md`: the `Game` model entry (no `playtime`), Signals (no Session
      recalculation), the removal paragraph (`_AFTER_STAMP`), the Commands
      table (`verify-playtime-parity`), a Key-patterns line for
      `games/reads/playtime/`. The wave review's #697 section marked
      **Delivered**. `make vale`.
- [ ] Full `make check`; then `make verify-replay-parity`.
- [ ] Sibling comments (bare `#NNN` in lists):
  - #700 — the parity command is its reconciliation; seed `day_zone` and a
    Duration-only `stated_day` from the library's display zone;
    `duration_manual IS NULL` is refused.
  - #702 — playtime surfaces reduce to flipping `SOURCE` and implementing
    `session_filter` in the projection source; its readers state
    `library_sessions`; `GameFilter`'s scoped session aggregates and the
    playthrough range read join the interface when restated.
  - #704 — the statistics gate is `make verify-playtime-parity`; correct the
    body's "seeding `day_zone` from `settings.TIME_ZONE`" paragraph: reads
    group in the viewer's display zone and #700 seeds `day_zone` from it.
  - #772 — drop the `_AFTER_STAMP` line from its scope; #697 removed it.
  - #1047, #1054, #748 — already restated on 2026-09-14: #1047 decides the one
    zone a library counts days in and the act that changes it, and blocks
    #1054, #748 and #702's dormancy-clock member. Nothing to post unless
    #697's delivery changes that premise.
  - #710 — the Historical Playtime column of the classification table in the
    #697 spec is its to implement, as a `PlaytimeSource` member.
- [ ] Repair the charter link in #697, #700, #702, #704, #710 and #770 to
      `blob/main/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md`.
- [ ] Push, mark #1065 ready for review, `gh pr merge --merge`.

---

## Gotchas

- **The projection is empty.** Every projection-source test builds its own
  `PlayerSession` rows. A caller bound to `projection` today prints zero.
- **The autouse `_track_created_games` fixture** gives every created game a
  `PlayerGame` and a `Playthrough`; use that run for twins, and
  `@pytest.mark.untracked_games` only where a bare catalog game is the point.
- **`alias()` not `annotate()`** for `playtime` and `total_playtime`.
- **The sum and the figure.** Sources never coalesce; `__init__.py` does, and
  only for figures. The filter needs the figure (`IS_NULL` and `EQUALS 0` both
  mean "= 0" there); both sorts need the sum, or an ascending sort puts
  unplayed games first.
- **Import the package inside `GameQuerySet.annotated_for_filtering`.** A
  module-level import from `games/models.py` cycles.
- **`library=None` is not an empty queryset** on the legacy manager:
  `for_library(None)` compiles `game__library IS NULL`. State `.none()`.
- **Corrected twins state the legacy total**, never the manual part.
- **`timezone.override` moves the legacy source only.** A test that overrides
  the zone builds its projection twin with the matching `day_zone`, or it
  tests the zone delta rather than parity.
- **`session_filter`, not `Q`.** A compiled `Q` carries the legacy table's
  field names across the interface.
- **Do not hand-edit the gzip** and do not round-trip it through a YAML
  dumper; the text-level removal keeps the diff reviewable.
- **`make test-e2e ARGS=…` does not scope** — it appends to `pytest e2e/`.
- **`PYTEST_WORKERS=0`** when debugging a parity test.

## Follow-up issues to file

None new. The review settled the zone question against the #704 and #1047
bodies (Task 7 corrects them), and the four playtime `StatsData` fields carry
their classification in the spec. Still to record:

- **Record the stored-total drift.** Task 6's list of games whose
  `Game.playtime` disagreed with their sessions goes into #697.
