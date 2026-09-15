# Session gates implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three gates that run and fail: the replay gate over all three `CURRENT_STATE` tables, the statistics gate comparing every session figure across both tables, and a stated read budget in `make bench`; then the operator's run on the 2026-09-12 dump, recorded.

**Architecture:** The replay gate is the existing two-family gate widened to three. The statistics gate is a second parity protocol beside `PlaytimeSource`, its projection side being the readers `compute_stats` itself calls. The budget is three additions to the bench: a session event per seeded game, a `CreateSession` timing, and a read scenario over six named reads. A page-render command lands on `main` ahead of the stack so the "before" can be rendered.

**Tech Stack:** Django 6 / Python 3.14 / PostgreSQL 18, pytest + pytest-xdist, `gh stack`.

**Spec:** `docs/superpowers/specs/2026-09-15-issue-704-session-gates-design.md` — read it first; every "why" lives there and is not repeated here.

## Global Constraints

- Run everything through `make`. Never `direnv exec .`, never bare `uv run` / `pytest`.
- Iterate with `make check-fast`; the gate before push is the full `make check`, e2e included.
- Focused runs: `make test ARGS="tests/test_projection_replay_gate.py -x"`.
- Python 3.14 only; `except A, B:` is PEP 758, not a bug.
- `make vale` on every comment and document. Comments name no issue; a forward TODO may.
- A test that POSTs or dispatches through a view needs `@pytest.mark.django_db(transaction=True)`.
- The legacy `Session` import is refused outside `ALLOWED_FILES` in `tests/test_session_import_guard.py`; the new parity module is added there with a reason, and the test that fails on an exemption nothing needs stays green because the module imports the name.
- Never write to a `GeneratedField`. Never `QuerySet.iterator()`.
- `gh stack submit --remote origin`; never `--open` (it flips every member to ready). Merge only when the user says merge.
- Member 4's branch is `feat/issue-704-gates`, based on `feat/issue-702-session-sweep` (#1077). Task 1's branch is `feat/render-pages`, based on `origin/main`, its own PR.

---

### Task 1: `render_pages`, its own PR against `main`

**Files:**
- Create: `games/management/commands/render_pages.py`
- Create: `tests/test_render_pages.py`
- Modify: `Makefile` (a `render-pages` target beside `preflight-sessions`)
- Modify: `CLAUDE.md` commands table

**Interfaces:**
- Produces: `manage.py render_pages --user NAME --out DIR`; `make render-pages ARGS="--user NAME --out DIR"`.
- `read_only_urls(user) -> list[RenderedUrl]` where `RenderedUrl(NamedTuple)` is `(name: UrlName, url: str, file_name: str)`; one entry per URL the spec lists: every `READ_ONLY` name of `games/views/returns.py`, list routes at every page (`?page=N` up to the count at the user's `DEFAULT_PAGE_SIZE`), `view_game`/`view_purchase` per live row of the user's library, `stats_by_year` per year `played_years` answers, `filter_builder` per key of `FILTER_MODE_MODELS`, the rest once. `file_name` is the URL with `/` and `?` replaced by `_`, ending `.html`.
- `normalise(html: str) -> str`: strips the CSRF token value (`value="..."` on `csrfmiddlewaretoken`, and `csrfToken` in any script) and the version footer text (the `version` and `version_modified_at` strings, matched by regex on the footer's parenthesised datetime).
- The command: `Client(SERVER_NAME="localhost")`, `force_login(user)`, `override_settings(INTERNAL_IPS=[])` around the run, writes `DIR/<file_name>` with the status code on the first line and the normalised body after, and prints a count of pages and of non-200 statuses. Refuses a `--out` that exists and is not empty.

**Gotchas:**
- The `Client` sends `testserver`; `ALLOWED_HOSTS` derives `localhost` from `APP_URL`. Pass `SERVER_NAME="localhost"`.
- `settings_kit_preview` is DEBUG-only; under `DEBUG=false` `reverse` raises. The command runs under `DEBUG`; do not special-case, let a `NoReverseMatch` fail loudly.
- `admin_settings` and `export_admin_settings_ini` answer 403 for a non-superuser; recorded, not skipped.
- `READ_ONLY` is guarded complete against the route table, so a new route lands here on its own; the command must not hold a second list of names. Iterate `READ_ONLY` and branch on the name for argument routes only.

- [x] **Step 1: Cut `feat/render-pages` from `origin/main`** in a fresh worktree (`git worktree add ../render-pages origin/main -b feat/render-pages`).
- [x] **Step 2: Failing tests** in `tests/test_render_pages.py` (`transaction=True` not needed; the command reads):
  - `test_every_read_only_route_is_rendered_once_or_per_row`: a user with two games, one purchase, one session in 2024 and one in 2025; `read_only_urls` names every `READ_ONLY` entry at least once, `view_game` twice, `stats_by_year` for 2024 and 2025, `filter_builder` once per `FILTER_MODE_MODELS` key.
  - `test_a_list_is_rendered_at_every_page`: 26 games at page size 25 gives two `list_games` URLs.
  - `test_the_csrf_token_and_the_version_footer_are_normalised`: two renders of one page with different tokens compare equal after `normalise`.
  - `test_the_command_writes_one_file_per_url_with_its_status_first`: run into `tmp_path`, count files, first line of `admin_settings`'s file is `403`.
  - `test_the_command_refuses_a_non_empty_directory`.
- [x] **Step 3: Implement** the command and the Make target. Under `DEBUG`, statics are unhashed; normalise only the two things the spec names.
- [x] **Step 4: `make check-fast`, then full `make check`.**
- [x] **Step 5: CLAUDE.md** commands row: "Render every read-only page as a user to files | `make render-pages ARGS="--user NAME --out DIR"` (the before/after rehearsal's instrument)".
- [x] **Step 6: Commit and open the PR** against `main`: `feat: render every read-only page to files`. Do not merge; the user merges. Record the PR number for Task 7. **Opened as #1078.** Lists render whole through `?per_page=0` rather than page by page, and a route mounted only under `DEBUG` is reported as unmounted rather than failing.

---

### Task 2: The replay gate over three tables

**Files:**
- Rename: `tests/test_playergame_playthrough_gate.py` → `tests/test_projection_replay_gate.py` (`git mv`)
- Modify: `tests/test_playersession_conversion.py` (the `UNREACHABLE_KINDS` import; the two-claimers test)
- Modify: `docs/superpowers/specs/2026-09-09-issue-688-replay-parity-gate-design.md:4`, `docs/superpowers/specs/2026-09-14-issue-697-playtime-reads-design.md:63`, `docs/superpowers/specs/2026-09-12-session-wave-design.md` (two mentions), `docs/superpowers/plans/2026-09-11-clean-02-legacy-table-removal.md` (two mentions), `CLAUDE.md` if it names the file

**Interfaces:**
- Consumes: `CreateSession(playthrough_id, timing, device_id, note, emulated)`, `EndSession(session_id, ended_at, ended_at_zone)`, `CorrectSessionTiming(session_id, timing)`, `DescribeSession(session_id, note, device: StatedDevice, emulated)`, `MoveSessionToPlaythrough(session_id, playthrough_id)`, `RemoveSession(session_id)`, `RestoreSession(session_id)` from `games/commands/playersession.py`; `TimedTiming`, `DurationOnlyTiming`, `CorrectedTiming`; `calendar_day_zone` from `games/reads/calendar.py`; `PlayerSessions` from `games/projectors/playersession.py`.
- Produces: `rows_of(library) -> tuple[ProjectionRows, ProjectionRows, ProjectionRows]` (tracked, runs, sessions); `empty_projections` deletes `PlayerSession` first; `row_versions` unions `games_playersession`; `registered_event_types` walks three `handles`.

**The stream additions** (after the run commands, before the removals; every key unique):
- `Device.objects.create(library=library, name="Deck")` for the device fact.
- `zone = calendar_day_zone(library).key`.
- `CreateSession` on `first_run`: `TimedTiming(started_at=<aware>, day_zone=zone)` running; `DurationOnlyTiming(day=date(2024,1,3), duration=timedelta(minutes=45))`; `CorrectedTiming(started_at, ended_at, duration=timedelta(hours=2), day_zone=zone)`. Read the three ids back from `PlayerSession.objects.filter(library=library).order_by("created_at")` or from the `CommandResult` as `games/writes/playersession.py:_created_id` does.
- `EndSession(session_id=timed, ended_at=<later aware>, ended_at_zone=None)`.
- `CorrectSessionTiming(session_id=duration_only, timing=TimedTiming(started_at=<aware>, day_zone=zone, ended_at=<aware>))`.
- `DescribeSession(session_id=corrected, note="Long one", device=StatedDevice(device.pk), emulated=True)`: three events.
- `MoveSessionToPlaythrough(session_id=corrected, playthrough_id=<second game's run>)`; the second game must still be live at this point, so dispatch before `remove-second-game`.
- `RemoveSession(timed)` then `RestoreSession(timed)`; `RemoveSession(duration_only)` left removed.
- `test_the_stream_leaves_a_removed_row_in_each_table` asserts one removed `PlayerSession`.

**Gotchas:**
- A session under the third game (removed at the end) would be hidden by `alive()` but still replayed; keep every session on the first two games so the removal leg's assertions stay simple.
- `test_the_guard_names_a_type_a_partial_stream_missed`: `13` becomes `22`.
- The rebuild leg's expected table list already names `games_playersession`; it stays four entries.
- The two-claimers test: add `assert reconcile(owned_library, counts) == []` after the existing assertions; `reconcile` and `codes` are already imported/defined in that module.

- [x] **Step 1: `git mv`; fix the conversion test's import; run `make test ARGS="tests/test_projection_replay_gate.py tests/test_playersession_conversion.py -x"`** — green before any change.
- [x] **Step 2: Failing first:** extend `registered_event_types` to three families and run the coverage test; it fails naming nine session types.
- [x] **Step 3: Extend `build_stream`, `rows_of`, `empty_projections`, `row_versions`, the removed-row test, the partial-stream count.** Run the file; every leg green.
- [x] **Step 4: Two-claimers `reconcile`.** Run the conversion file. The case now builds its runs from events (`tracked_game`, `stated_run`, `stated_second_run`, `untracked_games`), because the replay leg cannot reproduce rows the fixture wrote directly. The neighbour library gained one session, so the third table's `xmin` is watched.
- [x] **Step 5: Update the five documents' file name; `make vale`.**
- [x] **Step 6: `make check-fast`. Commit:** `test: replay every session event type through the gate (#704)`.

---

### Task 3: The page's session readers, deterministic

**Files:**
- Create: `games/reads/session_figures.py`
- Modify: `games/views/stats_data.py` (the superlatives, `unique_days`, `first_session`/`last_session`, `total_sessions` call the readers)
- Modify: `games/reads/player_sessions.py` (add `readable_sessions`), `games/api.py` (drop `_readable_sessions`, import it), `games/views/session.py:159` (call it)
- Modify: `games/views/game.py` (extract the queryset builder `list_games` uses)
- Test: `tests/test_session_figures.py` (new), `tests/test_stats_page.py` or wherever stats superlatives are tested today (grep `highest_session_average`)

**Interfaces (produced):**
```text
# games/reads/session_figures.py
type YearScope = int | None            # reuse games.reads.playthrough_completions.YearScope
class LongestSession(NamedTuple): session: PlayerSession; game: Game
class GameCount(NamedTuple): game: Game; sessions: int   # `count` would shadow tuple.count
class GameAverage(NamedTuple): game: Game; average: timedelta
class PlayDay(NamedTuple): day: date; game: Game

def scoped_sessions(library, year) -> PlayerSessionQuerySet     # library_sessions, effective_day__year
def session_count(library, year) -> int
def distinct_days(library, year) -> int
def longest_session(library, year) -> LongestSession | None     # order (-effective_duration, game sort_name, game id, id)
def most_sessions_game(library, year) -> GameCount | None       # order (-count, sort_name, id)
def highest_average_game(library, year) -> GameAverage | None   # Avg(effective_duration), same order
def first_play(library, year) -> PlayDay | None                 # order (effective_day, id)
def last_play(library, year) -> PlayDay | None                  # order (-effective_day, -id)
def has_sessions(library) -> bool

# games/reads/player_sessions.py
def readable_sessions(library) -> PlayerSessionQuerySet   # library_sessions + select_related(GAME + "__platform", "device")

# games/views/game.py
class GamesPage(NamedTuple): queryset: QuerySet[Game]; sort: SortResult
def games_for_list(library, *, game_filter: GameFilter | None, find: FindFilter) -> GamesPage
```
The stats page's `first_play_date`/`last_play_date` keep reading `effective_day`; the game beside them now comes from the reader's `(day, id)` order, which is the spec's page change for first/last. The `sort_instant` order the page used is replaced; state that in the commit body.

**Gotchas:**
- `most_sessions_game` counts through `GAME_SESSIONS` with `_counted_sessions_q`; move that `Q` into `session_figures.py` beside the reader, since the view no longer needs it.
- `highest_average_game` orders `-session_average` with NULLs: annotate over `games_in_scope` only, as today, so no NULL enters.
- `games_for_list` must take the sort, not the request; `list_games` parses the request and passes `find`.

- [x] **Step 1: Failing tests** in `tests/test_session_figures.py`: two games with equal longest durations pick the lower `sort_name`; two games with equal counts likewise; a year scope excludes the other year's row; `first_play` on a day holding a Duration-only and a Timed row picks the lower id; `has_sessions` false for an empty library and false when the only session is removed.
- [x] **Step 2: Implement the readers.** Run the file.
- [x] **Step 3: `compute_stats` calls them; `readable_sessions` lifted; `games_for_list` extracted.** Run `make test ARGS="tests/test_stats* tests/test_session_list.py tests/test_api.py tests/test_rendered_pages.py -x"`.
- [x] **Step 4: `make check-fast`. Commit:** `refactor: read the stats page's session figures through named readers (#704)`.

---

### Task 4: The statistics parity gate

**Files:**
- Create: `games/reads/session_parity.py`
- Rename: `games/management/commands/verify_playtime_parity.py` → `verify_session_parity.py`; `tests/test_playtime_parity.py` → `tests/test_session_parity.py`
- Modify: `tests/test_session_import_guard.py` `ALLOWED_FILES` (+ `"games/reads/session_parity.py": "The statistics gate's legacy side."`)
- Modify: `Makefile` (`verify-session-parity`), `CLAUDE.md` (table row, playtime paragraph, Session bullet), `docs/superpowers/specs/2026-09-12-session-wave-design.md` and `2026-09-14-issue-697-playtime-reads-design.md` (the target's name)

**Interfaces (produced):**
```text
# games/reads/session_parity.py
class SessionFigureSource(Protocol):
    def session_count(self, library, year) -> int
    def distinct_days(self, library, year) -> int
    def longest_session(self, library, year) -> LongestFigure | None   # (duration, game_id, session_id)
    def most_sessions_game(self, library, year) -> CountFigure | None  # (count, game_id)
    def highest_average_game(self, library, year) -> AverageFigure | None
    def first_play(self, library, year) -> DayFigure | None            # (day, game_id)
    def last_play(self, library, year) -> DayFigure | None
    def has_sessions(self, library) -> bool

class LegacySessionFigures: ...      # Session.objects.for_library; duration_total; TruncDate in the active zone
class ProjectionSessionFigures: ...  # wraps games.reads.session_figures, mapping rows to ids

type FigureValue = int | bool | LongestFigure | CountFigure | AverageFigure | DayFigure | None
class SessionFigure(NamedTuple): scope: FigureScope; legacy: FigureValue; projection: FigureValue
class SessionSourcePair(NamedTuple): legacy: SessionFigureSource; projection: SessionFigureSource
SESSION_SOURCES: Final = SessionSourcePair(LegacySessionFigures(), ProjectionSessionFigures())
COMPARED_SESSION_MEMBERS: Final = frozenset({...eight names...})
UNCOMPARED_SESSION_MEMBERS: Final[dict[str, str]] = {}

def session_figures(library, zone, *, sources=SESSION_SOURCES) -> list[SessionFigure]
    # per year of played_years union + all-time; under one_snapshot() and timezone.override(zone)
def differing_session_figures(figures) -> list[SessionFigure]
```
- `FigureScope`/`FigureKind` are reused from `games/reads/playtime_parity.py`; add kinds `SESSION_COUNT`, `DISTINCT_DAYS`, `LONGEST`, `MOST_SESSIONS`, `HIGHEST_AVERAGE`, `FIRST_PLAY`, `LAST_PLAY`, `HAS_SESSIONS`. `_one_snapshot` becomes public `one_snapshot` in `playtime_parity.py` and is imported.
- The command prints both figure lists per library, the split sentence about `--day-zone` unchanged, and fails on any difference in either.

**Legacy formulas** (in the active zone, `Session.objects.for_library(library)`, year on `timestamp_start__year`):
- longest: order `(-duration_total, game sort_name, game id, id)`;
- most sessions: `Game.objects.filter(sessions__in=scoped).annotate(Count)` ordered `(-count, sort_name, id)`;
- highest average: `Avg("sessions__duration_total")` filtered to the scope, same order;
- distinct days: `TruncDate("timestamp_start")`; first/last: `(TruncDate, id)`.

**Gotchas:**
- The twin helpers in `tests/session_rows.py` give the two rows different ids (`projection_row` mints `uuid7()` unless `id=` is in `columns`), so the `session_id` element of `LongestFigure` would never compare. Make the three twin builders create the legacy row first and pass `id=legacy.pk` into the projection row, as the conversion keeps the legacy id.
- `test_every_protocol_member_is_compared_or_exempt` uses `get_protocol_members`; add a second assertion over `SessionFigureSource`.
- Migration `0004` imports `playtime_parity`; do not rename it.

- [x] **Step 1: `git mv` both files; grep and replace the old names in Makefile, CLAUDE.md, docs, tests. `make test ARGS="tests/test_session_parity.py -x"` green.**
- [x] **Step 2: Failing tests** added to `tests/test_session_parity.py`: `test_every_session_figure_agrees_for_a_twin_of_each_mode`; `test_the_empty_projection_differs_on_every_non_empty_session_figure`; `test_a_tie_is_broken_the_same_way_on_both_sides` (two games, equal counts); `test_a_manual_row_counts_its_stated_time_on_both_sides` (a Duration-only twin is the longest on both); `test_every_session_protocol_member_is_compared_or_exempt`; the command tests assert the new lines print and a session difference exits non-zero.
- [x] **Step 3: Implement the module, the command, the guard entry.** Run `tests/test_session_parity.py tests/test_session_import_guard.py`.
- [x] **Step 4: `make check-fast`, `make vale`. Commit:** `feat: compare every session figure across both tables (#704)`. The tie test had to state the fixture game's `sort_name`: a blank one sorts first on both sides, which is the page's own rule.

---

### Task 5: The bench seeds a session per game

**Files:**
- Modify: `games/commands/playersession.py` (add `session_events`), `games/events/benchmark_workload.py` (seed, `_SEEDED_TABLES`), `games/events/benchmark_run.py` (`seed // 3`), `games/management/commands/benchmark_events.py` (refusal, estimate, help), `games/events/benchmark.py` (`SeedReport` docstring), `docs/event-benchmarks.md:15-17`
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
```text
# games/commands/playersession.py
def session_events(playthrough_id: uuid.UUID, *, day: date, day_zone: ZoneName) -> list[NewEvent]
    # one playersession_created: TimedTiming(started_at=noon in day_zone, ended_at=+1h, day_zone), no device, note "", emulated False
```
- `seed_library`: per game in a batch, `[*tracking_events(game), *session_events(tracking_events(...)[1].aggregate_id, day=today - (index % 730), day_zone=calendar_day_zone(library).key)]`; build the pair once per game, not twice. `events += 3 * len(batch)`.
- `_measure_scratch`: `games=seed // 3`; `benchmark_events`: refuse `0 < seed < 3` with a sentence naming three; estimate `seed // 3` catalog rows; help text "three events a game".

**Gotchas:**
- `playersession_created` needs `timing_payload(TimedTiming(...))` from the same module; keep `session_events` beside `CreateSession` so it reads the same helpers.
- `append` applies projectors in event order inside one batch; the run's row exists before the session's insert. Assert it in the test below.
- Tests to update: `test_seeding_writes_both_creation_events_and_both_projection_rows` (75 events, 25 sessions), `test_replaying_one_event_costs_one_statement` (slope over 60), `test_an_odd_seed_seeds_one_event_fewer` (seed 7 → 2 games, 6 events), `test_a_seed_of_one_is_refused` (seed 2 too), the `catalog_rows` arithmetic.

- [x] **Step 1: Failing test** `test_seeding_writes_a_session_on_each_seeded_run`: 25 games → 25 `PlayerSession` rows, each `playthrough_id` among the seeded runs, `timing_mode == "timed"`, `effective_duration == 1h`, `day_zone == calendar_day_zone(library).key`; distinct `effective_day` count is 25.
- [x] **Step 2: Implement; update the counts in the existing tests; `make test ARGS="tests/test_event_benchmark.py -x"`.**
- [x] **Step 3: Re-measure `SECONDS_PER_*`** (35, 29 and 12 per 100,000 on a 20,000-event run; the dev database had to be migrated to the stack's schema first, and the first run leaked a scratch user that `make purge-library` took) with `make bench ARGS="--seed 20000 --iterations 50"` and paste; update `docs/event-benchmarks.md` lines 15-17.
- [x] **Step 4: `make check-fast`. Commit:** `feat: seed a session per game in the benchmark (#704)`.

---

### Task 6: The session command budget and the read budget

**Files:**
- Modify: `games/events/benchmark.py` (`ReadTimings`, `READ_BUDGET_SECONDS = 0.020`, `read_budget`, `session_command_budget`, `BenchmarkReport.session_command`, `.reads`, `REPORT_SCHEMA = 3`)
- Create: `games/events/benchmark_reads.py` (the six reads)
- Modify: `games/events/benchmark_workload.py` (`run_session_command_scenario`, `run_read_scenario`), `games/events/benchmark_run.py` (both modes; `_measure_existing(library, *, iterations, warmup, count_replay)`), `games/management/commands/benchmark_events.py` (printing)
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
```text
# games/events/benchmark_reads.py
type ReadName = str
class NamedRead(NamedTuple): name: ReadName; execute: Callable[[UserLibrary], object]
READS: Final[tuple[NamedRead, ...]]   # session_page, game_playtime_sort, stats_totals, stats_by_platform, stats_by_month, stats_superlatives

# games/events/benchmark.py
class ReadTimings(NamedTuple): name: ReadName; timings: Timings
def read_budget(read: ReadTimings) -> Budget          # name f"read {name} p95", limit 0.020, gated at MINIMUM_GATED_SAMPLES
def session_command_budget(timings: Timings) -> Budget # name "session command p95", COMMAND_BUDGET_SECONDS

# games/events/benchmark_workload.py
def run_session_command_scenario(library, *, actor, runs: Iterator[Playthrough], iterations, warmup) -> Timings
    # dispatch CreateSession(DurationOnlyTiming(day, 30 min)) per run; warmup discarded
def run_read_scenario(library, *, iterations, warmup) -> tuple[ReadTimings, ...]
    # for each NamedRead: warmup executions discarded, then iterations timed with monotonic; list() the result
```
- Reads call: `readable_sessions(library).order_by("-sort_instant", "-id")[:25]`; `games_for_list(library, game_filter=None, find=FindFilter(sort="playtime")).queryset[:25]`; `total_playtime(library)`, `session_count(library, None)`, `distinct_days(library, None)`; `playtime_by_platform(library)`; `playtime_by_month(library, year=max(played_years))` (skip with zero samples when no year); the five superlative readers.
- `_measure_scratch`: `runs` for the session scenario are the seeded runs (`Playthrough.objects.filter(library=library).order_by("pk")` paged by key); `_measure_existing` runs the read scenario and the rebuild; `budgets` gains the session command budget (scratch) and six read budgets (both).
- Printing: `Session command: N sample(s), p50, p95, max.` and one `Read <name>: ...` line per read, before the budgets.

**Gotchas:**
- The `--library` mode must not dispatch. Only the read scenario and the rebuild run there.
- `test_the_report_carries_every_scenario_and_a_schema` and the JSON test assert `schema == 2`; bump to 3 and assert `reads` and `session_command` present.
- `test_too_few_samples_is_not_gated_but_is_still_measured` gains a read case.
- `stats_by_month` on the scratch library: the seed spans two years, so `played_years` is non-empty.

- [x] **Step 1: Failing tests**: `test_a_read_inside_the_budget_passes` / `..._over_the_budget_misses` (pure `read_budget`); `test_the_session_command_budget_is_the_charters` ; `test_the_read_scenario_times_every_named_read` (scratch seed 30, iterations 2 → six `ReadTimings`, each `samples == 2`); `test_library_mode_reads_without_dispatching` (event count unchanged after `run_benchmark(library=...)`); the schema and JSON tests at 3.
- [x] **Step 2: Implement; run the file.**
- [x] **Step 3: Full `make bench ARGS="--gate"`** on this machine; paste under "The #704 recording" in `docs/event-benchmarks.md` with the machine block. Every budget must print `passed`. **Decision on the run:** five reads missed 20 ms on the scratch library, which holds 33,543 sessions on 33,743 games, twelve times production and one session a game. The user chose: reads are measured and recorded on the scratch library as `not_gated`, and the 20 ms verdict is given under `--library` only (`read_budget(..., on_real_library=)`). The spec's Gate 3 wording is updated in the sweep.
- [x] **Step 4: `make check-fast`, `make vale`. Commit:** `feat: state a read budget and time the session command in the benchmark (#704)`.

---

### Task 7: The rehearsal on the 2026-09-12 dump

No code. The operator's run, recorded.

- [x] **Step 1:** `make restore-dump DUMP=.dumps/timetracker-2026-09-12.dump`; note the printed `DATABASE_URL`.
- [x] **Step 2 (before):** in a worktree at `origin/main` with Task 1's file copied in (or merged), `DATABASE_URL=<scratch> make render-pages ARGS="--user <each user> --out /tmp/.../before/<user>"`. Users: `psql` the scratch for `auth_user.username`.
- [x] **Step 3 (after):** in this worktree, `DATABASE_URL=<scratch> make migrate`, then `render-pages` into `after/<user>`, `make verify-session-parity ARGS="--all-libraries"`, `make verify-replay-parity`, `make bench ARGS="--library <id> --gate"` per library with sessions.
- [x] **Step 4:** `diff -r before after > diff.txt`; (the after render needed the command file copied into this worktree, since `render_pages` lives on #1078; `stats_superlatives` missed by 0.4 ms and its three aggregating readers were regrouped on the session table, a fix in Task 3's file) attribute every differing page: #702's superlative (a manual row wins), #689's `sort_instant` on first/last, a tie printed the other way, or a defect. A defect is fixed in a task above before this task closes.
- [x] **Step 5: Record.** Wave document `### #704 — the gates` gains a **Delivered.** block: page counts identical/differing with the attribution, parity figure counts per library, replay result, the `--library` bench lines pasted, and "the deployment constraint is lifted". `docs/event-benchmarks.md` gets the `--library` run under the #704 recording. Comment on #704 with the same numbers; comment on #772 (allow list gains `games/reads/session_parity.py`; `verify_session_parity` and `render_pages`' legacy-free).
- [x] **Step 6:** `make drop-dump`.
- [x] **Step 7: Commit:** `docs: record the gates' run on the 2026-09-12 dump (#704)`.

---

### Task 8: CLAUDE.md, the gate, the stack

- [ ] **Step 1: CLAUDE.md**: commands table (`verify-session-parity`, `bench` help text with three events a game and the read budget), the `PlayerSession` model bullet gains a #704 paragraph (three gates, the readers in `session_figures.py`, `readable_sessions`, `games_for_list`, the bench's third event and six reads at 20 ms, `render_pages`), the Session bullet's guard sentence names the parity module, the Playtime reads paragraph names `verify-session-parity`.
- [ ] **Step 2: Full `make check`** (e2e included). Green or fix.
- [ ] **Step 3:** `gh stack add` this branch after #1077 if not already a member; `gh stack submit --remote origin`; `gh pr edit` the body: what it does, the three gates' results, the rehearsal numbers, "member 4 of 4, never merged alone".
- [ ] **Step 4: Docs sweep**: delete this plan, rewrite the spec timeless (200–500 words, ASD-STE100), `make vale`, commit `chore: record the gates (#704)`.
- [ ] **Step 5: Pause.** Merge only when the user says merge.

## Follow-up issues to file

None. The budget's remedy is #909's and #913's shape; the legacy side leaves with #772.
