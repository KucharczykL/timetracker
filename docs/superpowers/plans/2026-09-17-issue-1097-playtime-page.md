# Playtime Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Playtime page with Sessions and Historical tabs; the Historical tab lists `HistoricalPlaytime` records with filter, quick bar, sorts, presets, builder and an API.

**Architecture:** A new filter mode `historical_playtime` (model key `historicalplaytime`) joins every per-mode registry. The list view reads the shared scope `games/reads/historical_playtime_records.py`. A link-tab primitive joins the two list views; nothing about the Sessions list changes but its tabs.

**Tech Stack:** Django 6, Django Ninja, the Python component system, pytest + pytest-playwright, vitest.

**Spec:** [`docs/superpowers/specs/2026-09-17-issue-1097-playtime-page-design.md`](../specs/2026-09-17-issue-1097-playtime-page-design.md). Shared decisions: [`docs/review/2026-09-17-historical-playtime-parallel-specs.md`](../../review/2026-09-17-historical-playtime-parallel-specs.md) (D1–D6). Read both before Task 1.

## Global Constraints

- Drive everything through `make`; iterate with `make test ARGS="…"` / `make check-fast`; the gate is full `make check`, run by the controller, not per task.
- Rebase onto `origin/main` before starting and before the PR.
- `games/reads/historical_playtime_records.py` is D1's text on `main`, verbatim. If `main` already has it (a sibling merged first), use `main`'s file and skip creating it.
- Migration is `0010`. If a sibling merged a migration first, renumber and re-point `dependencies`.
- Mode key `historical_playtime`; model key `historicalplaytime`; route `historical-playtime/list`, name `games:list_historical_playtime`; view module `games/views/historical_playtime.py`.
- New test files only: `tests/test_historical_playtime_filter.py`, `tests/test_historical_playtime_api.py`, `tests/test_playtime_page.py`, `e2e/test_playtime_page_e2e.py`, helper `tests/historical_playtime_rows.py`.
- Default sort `-when,-created`. `when` filter is overlap (`temporal_interval_handler`), never containment.
- Complete-word identifiers; PEP 695 aliases for primitive roles; htpy builders; `ControlButton` for buttons; no `render()`.
- Comments: current intent only, no issue numbers. `make vale` covers new prose.
- Tests that dispatch commands need `@pytest.mark.django_db(transaction=True)` and the `untracked_games` marker, as `tests/test_historical_playtime_command.py` does.

## File map

| file | change |
|---|---|
| `games/reads/historical_playtime_records.py` | create (D1 verbatim) |
| `games/filters.py` | `HistoricalPlaytimeFilter`, parser, `MODE_PARSERS`, `_FILTER_LIST_URL`, both scope functions |
| `games/models.py` + `games/migrations/0010_…` | `FilterPreset.MODE_CHOICES` |
| `games/sorting.py` | `HISTORICAL_PLAYTIME_SORTS`, default, `MODE_SORTS` |
| `common/components/custom_elements.py` | `FILTER_MODE_LIST_URLS`, `FILTER_MODE_MODELS` |
| `games/views/filtering.py` | `BUILDER_MODES` |
| `common/components/quick_filter.py` | `QUICK_FACETS` |
| `common/components/primitives.py` + `__init__.py` | `PageTabs` |
| `common/components/domain.py` + `__init__.py` | `PlaytimeTabs` |
| `common/components/library_kit.py` | `StatisticCard(title=…)` |
| `games/views/historical_playtime.py` | create: `list_historical_playtime` |
| `games/views/session.py` | tabs above the quick bar |
| `games/views/general.py` | builder switcher derived from `BUILDER_MODES` |
| `games/views/library.py` | Playtime card |
| `games/views/returns.py`, `games/urls.py`, `games/management/commands/render_pages.py` | route |
| `games/api.py` | `historical_playtime_router` |
| `timetracker/settings_registry.py`, `docs/configuration.md` | relabel |
| `ts/elements/filter-tree/fixtures.json`, `tests/test_filter_tree_contract.py` | contract |
| `CLAUDE.md`, wave spec | one sentence each |

---

### Task 1: Scope and filter

**Files:**
- Create: `games/reads/historical_playtime_records.py`, `tests/historical_playtime_rows.py`, `tests/test_historical_playtime_filter.py`
- Modify: `games/filters.py` (new class after `PlaythroughFilter`; `parse_historical_playtime_filter`; `filter_queryset_for_library`; `filter_query_context_for_library`), `tests/test_filters.py` (`_ALL_FILTERS` near line 2615, `ALL_FILTERS` near line 5020)

**Interfaces:**
- Produces: `library_records(library) -> HistoricalPlaytimeQuerySet`, `readable_records(library)`, `game_records(library, game)`, `RECORD_ORDER`; `HistoricalPlaytimeFilter`; `parse_historical_playtime_filter(json_str) -> HistoricalPlaytimeFilter | None`; test helper `record_playtime(library, actor, run, **statement_changes) -> HistoricalPlaytime`.

- [ ] **Step 1: Test helper.** `tests/historical_playtime_rows.py`: `record_playtime` dispatches `RecordHistoricalPlaytime` with a `HistoricalPlaytimeStatement` built like `stated()` in `tests/test_historical_playtime_command.py:96` (defaults: one hour, `when` unknown, `estimated`, no device, not emulated, empty note; `playthrough_ids=(run.pk,)`), unique idempotency key, returns the row by the event's `aggregate_id` (not `.get()`, several rows exist). Add `run_for(library, actor, game)` that dispatches `TrackGame` and returns the default run.
- [ ] **Step 2: Failing scope tests** in `tests/test_historical_playtime_filter.py`: `library_records` excludes a removed record, a record under a removed `PlayerGame` (`RemovePlayerGame`), a record under a removed catalog game (`games.removal.remove(game)`), and another library's record.
- [ ] **Step 3: Failing filter tests**, each over `execute_filter(filter, library_records(library), filter_query_context_for_library(library))`:
  - `game` include/exclude; `device` include and `IS_NULL`; `emulated`; `note` includes;
  - `provenance` equals `externally_measured`; exclude-mode set;
  - `duration_hours` greater-than and between;
  - `when`: `EQUALS 2021-05-05` matches `2020/2022` and `2021`, not `2019`; `BETWEEN 2022-01-01..2022-12-31` matches `2020/2022`; `LESS_THAN` over an open range `2020..`; `IS_NULL` matches only unknown; `NOT_NULL` the rest;
  - `created_at` equals today;
  - `search` hits game name, platform name, device name, note;
  - `game_filter` (by game name) and `device_filter` (by device name);
  - `field_metadata(HistoricalPlaytimeFilter)` gives `provenance` three choices and `when` a date kind;
  - a builder-shaped filter with a `field_comparisons` entry over a multi-valued operand (a column through `player_game`/playthroughs as `comparable_columns(HistoricalPlaytime)` lists it) executes without `KeyError`.
- [ ] **Step 4: Run** `make test ARGS="tests/test_historical_playtime_filter.py -x"` — fails on import.
- [ ] **Step 5: Implement.** Copy D1 from `docs/review/…` verbatim into the reads module. Filter, modelled on `PlayerSessionFilter` (`games/filters.py:241`):

```python
@dataclass
class HistoricalPlaytimeFilter(OperatorFilter):
    """Filter for the HistoricalPlaytime projection."""

    AND: list[HistoricalPlaytimeFilter] = field(default_factory=list)
    OR: list[HistoricalPlaytimeFilter] = field(default_factory=list)
    NOT: list[HistoricalPlaytimeFilter] = field(default_factory=list)

    game: UUIDMultiCriterion | None = None
    provenance: ChoiceCriterion | None = None
    device: UUIDMultiCriterion | None = None
    emulated: BoolCriterion | None = None
    duration_hours: IntCriterion | None = None
    when: DateCriterion | None = None  # the interval the record states
    note: StringCriterion | None = None
    created_at: DateCriterion | None = None
    search: StringCriterion | None = None
    game_filter: GameFilter | None = None
    device_filter: DeviceFilter | None = None

    fields: ClassVar[dict[str, FilterField]] = {
        "game": FilterField("player_game__game__id", search_url="/api/games/search"),
        "provenance": FilterField(),
        "device": FilterField("device_id", search_url="/api/devices/search"),
        "emulated": FilterField(),
        "duration_hours": FilterField(
            handler=duration_hours_handler("duration"), label="Duration (hours)"
        ),
        "when": FilterField(
            handler=temporal_interval_handler("when", "when_lower", "when_upper"),
            metadata_lookup="when_lower",
            label="When",
        ),
        "note": FilterField(),
        "created_at": FilterField("created_at__date"),
    }
```

  `_comparison_model` returns `HistoricalPlaytime`. `_extra_q`: `search_q(search, "player_game__game__name", "player_game__game__platform__name", "device__name", "note")`; two `relation_to_q` blocks as `PlayerSessionFilter` has, `parent_field="player_game__game__id"` and `"device_id"`. Add `HistoricalPlaytime` branches to both scope functions, answering `library_records(library)` (context entry wrapped in `cache(lambda: …)`). Add to both hand-written filter lists in `tests/test_filters.py`.
- [ ] **Step 6: Run** the new file and `make test ARGS="tests/test_filters.py -x"`. Pass. `make typecheck`.
- [ ] **Step 7: Commit** `feat: filter historical playtime records`.

### Task 2: Tabs and the Library entry

**Files:**
- Modify: `common/components/primitives.py`, `common/components/domain.py`, `common/components/__init__.py`, `common/components/library_kit.py`, `games/views/library.py`, `timetracker/settings_registry.py` (label at line 38, `empty_display` at line 321), `docs/configuration.md:198`
- Test: `tests/test_components.py` (PageTabs), `tests/test_library_ui_components.py` (title), `tests/test_library_page_isolation.py:65`, `tests/test_settings_registry.py:185`, `tests/test_settings_forms.py:132,143,164-165`, `tests/test_settings_page.py:111`

**Interfaces:**
- Produces: `type TabLabel = str`; `class PageTab(NamedTuple): label: TabLabel; href: str; current: bool`; `PageTabs(label: str, tabs: Sequence[PageTab]) -> Node`; `type PlaytimeTab = Literal["sessions", "historical"]`; `PlaytimeTabs(current: PlaytimeTab) -> Node`; `StatisticCard(label, value, *, href=None, title=None)`.

- [ ] **Step 1: Failing tests.** `PageTabs`: renders `<nav aria-label="…">`, one `<a>` per tab, exactly one `aria-current="page"` on the current tab, none elsewhere; escapes labels. `PlaytimeTabs("historical")`: hrefs are `reverse("games:list_sessions")` and `reverse("games:list_historical_playtime")` — this test waits for Task 3's route, so mark it in Task 3 instead and here test only `PageTabs`. `StatisticCard(title=…)` emits `title` on the card; without it, no `title`. Library page: card label "Playtime", accessible name `"1 Playtime"` for one session and no record (update line 65), `title="Sessions and historical records"`. Settings: every pinned "Sessions" landing label reads "Playtime".
- [ ] **Step 2: Run** the listed tests; they fail.
- [ ] **Step 3: Implement.** `PageTabs`: `Nav(aria_label=label)[Div(class_="inline-flex …")[…]]`, each tab a `ControlLink`/`ControlButton(href=…, variant="segmented")` with `aria_current="page"` and a current-state class on the current one; reuse the segmented look's classes rather than new colours (see `docs/visual-conventions.md`). `PlaytimeTabs` in `domain.py` builds two `PageTab`s. Library card value: `session_count + library_records(library).count()`, `title="Sessions and historical records"`. Relabel both settings strings and the docs sentence.
- [ ] **Step 4: Run** the tests; pass. **Commit** `feat: add page tabs and name the Playtime entry`.

### Task 3: The Historical list and the mode

**Files:**
- Create: `games/views/historical_playtime.py`, `games/migrations/0010_alter_filterpreset_mode.py` (via `make makemigrations ARGS="games --name alter_filterpreset_mode"`), `tests/test_playtime_page.py`
- Modify: `games/models.py:1261` (`MODE_CHOICES` gains `("historical_playtime", "Historical playtime")`), `games/sorting.py`, `common/components/custom_elements.py:62-90`, `games/views/filtering.py:29`, `common/components/quick_filter.py:131`, `games/views/session.py:247` (tabs), `games/views/general.py:160-166`, `games/views/returns.py:27`, `games/urls.py:202`, `games/management/commands/render_pages.py:31`, `games/views/__init__.py` if it re-exports views
- Test (extend hand-written lists): `tests/test_filter_paths.py:88`, `tests/test_filter_widgets.py:317`, `tests/test_filter_builder_page.py:86`, `tests/test_sort_header_parity.py`, `tests/test_table_width_policy.py:36`, `tests/test_column_priority_contract.py:116`, `tests/test_action_origin_parity.py:69`, `tests/test_html_validity.py:159`, `tests/test_date_time_rendering_paths.py:143`, `tests/test_library_page_isolation.py:188`, `tests/test_paths_return_200.py`, `tests/test_filter_presets.py`, `tests/test_sorting.py`

**Interfaces:**
- Consumes: Task 1 (`readable_records`, `HistoricalPlaytimeFilter`, `parse_historical_playtime_filter`), Task 2 (`PlaytimeTabs`).
- Produces: `list_historical_playtime(request) -> HttpResponse`; `HISTORICAL_PLAYTIME_SORTS: SortMap`, `HISTORICAL_PLAYTIME_DEFAULT_SORT = "-when,-created"`; `historical_playtime_tabledata(records, library, presentation, durations, *, sort_terms, origin) -> TableData`.

- [ ] **Step 1: Failing page tests** in `tests/test_playtime_page.py`:
  - both routes 200; both render `PlaytimeTabs` with the right `aria-current`;
  - Historical row shows game (inside `<truncated-text`), `When` text (`Unknown` for null, `2020/2022` rendered by `TemporalText`), duration, provenance label, device or "No device", run names from `numbered_for`, and a "shared" mark on a two-run record only;
  - `?filter=` narrows; a bad filter shows the existing error message path; `?sort=` for each key orders as `HISTORICAL_PLAYTIME_SORTS` says; default order equals `RECORD_ORDER` over the same rows;
  - query count for a page of ten records does not grow with the number of runs (`django_assert_max_num_queries`);
  - the quick bar renders the six facets and an Advanced filter link to `filter_builder` with `historicalplaytime`;
  - a preset saved through `POST /api/presets/` with mode `historical_playtime` lists and loads; a stored `sessions` preset still loads on `list_sessions`;
  - the builder page for `historicalplaytime` renders, and its switcher lists Playthrough and Historical playtime.
  Also move the `PlaytimeTabs` href test from Task 2 here.
- [ ] **Step 2: Add the new route/filter to every hand-written list** named above, following each file's existing entry for `list_playthroughs` / `PlaythroughFilter`. Run `make test ARGS="tests/test_playtime_page.py -x"`; fails.
- [ ] **Step 3: Implement registries.** `MODE_CHOICES`, run `make makemigrations ARGS="games --name alter_filterpreset_mode"` (inspect: one `AlterField`). Sorts:

```python
HISTORICAL_PLAYTIME_SORTS: SortMap = {
    "name": SortSpec("player_game__game__sort_name"),
    "when": SortSpec("when_lower"),
    "duration": SortSpec("duration"),
    #: Stored value, not label order.
    "provenance": SortSpec("provenance"),
    "device": SortSpec("device__name"),
    "created": SortSpec("created_at"),
}
HISTORICAL_PLAYTIME_DEFAULT_SORT: SortString = "-when,-created"
```

  `MODE_SORTS`, `MODE_PARSERS`, `_FILTER_LIST_URL`, `FILTER_MODE_LIST_URLS`, `FILTER_MODE_MODELS`, `BUILDER_MODES` gain the mode. `QUICK_FACETS["historical_playtime"]`: `provenance`, `duration_hours` ("Duration (hrs)", placeholders "e.g. 1"/"e.g. 100"), `game`, `device`, `when` ("When"), `created_at` ("Created"). Builder switcher: build `items` from `BUILDER_MODES` via `FILTER_MODE_MODELS` and `apps.get_model`, sorted by label, with the existing `"Session"` label override kept for `playersession`.
- [ ] **Step 4: Implement the view**, shaped like `list_playthroughs` (`games/views/playthrough.py:133`): `readable_records(library).prefetch_related(Prefetch("runs", queryset=HistoricalPlaytimeRun.objects.order_by("playthrough_id")))`; `apply_structured_filter` + `execute_filter`; `apply_sort(..., HISTORICAL_PLAYTIME_SORTS, HISTORICAL_PLAYTIME_DEFAULT_SORT)`; `warn_unknown_sort(entity="historical playtime")`; `paginate`; one `numbered_for(library, {record.player_game_id …})` mapped to `{run.pk: display_name(run)}`. Columns: `Column("Name", "name", shrinkable=True)`, `When`/`when`, `Duration`/`duration`, `Provenance`/`provenance`, `Runs` (no sort key), `Device`/`device`, `Created`/`created`; priorities matching the session list's so `test_column_priority_contract` holds. Name cell `NameWithIcon(game=…)`; `When` cell `TemporalText(record.when, presentation)`; duration `Duration(record.duration, …, id_scope=f"record-{record.pk}")`; provenance a `Pill` whose colour differs for `externally_measured`. Content: `ContentContainer()[PlaytimeTabs("historical"), quick_bar, table]`, title "Historical playtime". Add `PlaytimeTabs("sessions")` to `list_sessions`. Route, `READ_ONLY`, `LIST_ROUTES`.
- [ ] **Step 5: Run** the new file plus every file edited in Step 2, then `make check-fast`. Pass.
- [ ] **Step 6: Commit** `feat: list historical playtime on the Playtime page`.

### Task 4: API

**Files:**
- Modify: `games/api.py` (schemas beside `SessionOut`, router after `session_router`)
- Create: `tests/test_historical_playtime_api.py`
- Modify: `tests/test_library_api_isolation.py` if it walks routers by hand

**Interfaces:**
- Produces: `HistoricalPlaytimeOut`, `HistoricalPlaytimeListOut`; `GET /api/historical-playtime/` (`list_historical_playtime_api`), `GET /api/historical-playtime/{record_id}` (`get_historical_playtime`).

- [ ] **Step 1: Failing tests:** list envelope fields and `PAGE_SIZE`; item fields (`when` as canonical text via `.serialize()`, null when unknown; `when_lower`/`when_upper`; `playthrough_ids` sorted; `duration_seconds` integer; `game` and `device` nested as `GameOut`/`DeviceOut`); filter narrows; bad filter → 400 and a `games` WARNING log; unknown sort → 400; detail 200; detail for a removed record, a record under a removed game and another library's record → 404; anonymous → 401 as other routers.
- [ ] **Step 2: Run**; fails. **Step 3: Implement** as `list_sessions_api` / `get_session` (`games/api.py:607-660`), over `readable_records(library).prefetch_related("runs")`, `@regex_timeout_api`, `owned_or_404`. Resolvers: `resolve_when` → `None if obj.when is None else obj.when.serialize()`; `resolve_duration_seconds`; `resolve_playthrough_ids` → sorted `run.playthrough_id`s. Mount `api.add_router("/historical-playtime", historical_playtime_router)`.
- [ ] **Step 4: Run**; pass. **Commit** `feat: serve historical playtime records over the API`.

### Task 5: Cross-language filter contract

**Files:**
- Modify: `ts/elements/filter-tree/fixtures.json`, `tests/test_filter_tree_contract.py` (`FILTER_FOR_MODEL`)

- [ ] **Step 1:** Add a `historicalplaytime` registry entry (relations `game_filter → game`, `device_filter → device`, following the `playersession` entry's shape) and four cases with `"model": "historicalplaytime"`: a `provenance` leaf; a `when` `BETWEEN`; a `NOT` over `duration_hours`; a `game_filter` relation. If `device` is not yet in the registry, add the minimal entry the serializer needs.
- [ ] **Step 2:** `FILTER_FOR_MODEL["historicalplaytime"] = HistoricalPlaytimeFilter`.
- [ ] **Step 3:** `make test-ts` then `make test ARGS="tests/test_filter_tree_contract.py -x"`; pass (the contract skips when the canonical file is absent — confirm it ran, not skipped).
- [ ] **Step 4: Commit** `test: cover the historical playtime filter in the filter-tree contract`.

### Task 6: Browser tests

**Files:**
- Create: `e2e/test_playtime_page_e2e.py`
- Modify: `e2e/test_table_width_e2e.py:151`, `e2e/test_responsive_table_e2e.py:144`; `e2e/test_quick_filter_e2e.py` only if it enumerates modes

- [ ] **Step 1:** Tests: from the Library page, the Playtime card opens the Sessions tab; the Historical tab link opens the list with `aria-current` moved; the provenance facet selects "Externally measured", Apply navigates, only that row remains, and the facet shows the choice after reload; the Advanced filter link opens the builder on `historicalplaytime`; no console errors. Seed records with `tests/historical_playtime_rows.py` helpers (or an `e2e/` twin if `e2e/` cannot import `tests/`, as `e2e/tracked_games.py` shows).
- [ ] **Step 2:** Add the new route to both e2e route lists.
- [ ] **Step 3:** `make ts` then `make test-e2e` (ARGS does not scope it — run the whole suite; never with `make dev` up). Pass.
- [ ] **Step 4: Commit** `test: drive the Playtime page in the browser`.

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md` (HistoricalPlaytime entry, the sentence "Nothing reads or writes it from a page yet."), `docs/superpowers/specs/2026-09-17-historical-playtime-wave-design.md` (Screens, "The nav entry "Sessions" becomes…")

- [ ] **Step 1:** CLAUDE.md, per D5: if `main` still holds the sentence, replace it with one sentence: the Playtime page lists records under the Historical tab through `HistoricalPlaytimeFilter`, mode `historical_playtime`, and `/api/historical-playtime/`. If a sibling already replaced it, keep theirs and append this one. Add `historical_playtime` wherever CLAUDE.md enumerates filter modes or API routes (REST API list).
- [ ] **Step 2:** Wave spec: the Screens sentence names the three entries (Library card, landing page, `index` redirect) instead of a nav entry.
- [ ] **Step 3:** `make vale`; pass. **Commit** `docs: name the Playtime page`.

### Task 8 (conditional): Row actions and "View all"

Only if #706 is on `main` when this branch rebases for its PR (review D4). Otherwise #706 carries it; skip.

**Files:** `games/views/historical_playtime.py`, `games/views/game.py` (`_game_section` call of #706's section), `tests/test_playtime_page.py`, `tests/test_action_origin_parity.py`, `tests/test_column_priority_contract.py`

- [ ] **Step 1: Failing tests:** each row has Edit (to #706's restate route) and Remove (to its confirm route), both carrying `?origin=` equal to the list URL; Game detail's section has "View all" to `filter_url(HistoricalPlaytimeFilter.where(game=[game.id]))`.
- [ ] **Step 2: Implement:** `Column("Actions", align="right", priority=4)`; a `ButtonGroup` of `ControlButton(href=action_url(<706 route>, record.pk, origin=origin), variant="segmented")`; pass `view_all_url=` to `_game_section`. Use #706's route names as `main` has them.
- [ ] **Step 3: Run**; pass. **Commit** `feat: act on historical playtime from the list`.

### Final: gate and PR

- [ ] `git fetch && git rebase origin/main`; resolve per the review (shared module from `main`, D5 for CLAUDE.md, migration renumber). Re-decide Task 8.
- [ ] `make check > log 2>&1; echo $?` — read the exit code, not a grep. Green, e2e included.
- [ ] Docs sweep: delete this plan file; rewrite the spec timeless.
- [ ] PR body links the spec and the review; ends with the attribution line.

## Self-review notes

- Spec sections → tasks: entry points (T2), tabs (T2, T3), scope (T1), mode registries (T3), filter (T1), quick bar and sorts (T3), table (T3), row actions (T8), API (T4), tests (T1–T6), parallel work (Global Constraints, Final), wave amendment and CLAUDE.md (T7).
- Names used across tasks: `library_records`, `readable_records`, `RECORD_ORDER`, `HistoricalPlaytimeFilter`, `parse_historical_playtime_filter`, `PageTab`, `PageTabs`, `PlaytimeTabs`, `HISTORICAL_PLAYTIME_SORTS`, `HISTORICAL_PLAYTIME_DEFAULT_SORT`, `list_historical_playtime`, `record_playtime`, `run_for`.
