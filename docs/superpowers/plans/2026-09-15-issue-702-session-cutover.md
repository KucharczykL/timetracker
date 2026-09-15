# Session cutover (#702) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Session write is a command and every Session read reads
the projection; nothing outside the allow list imports `Session`.

**Architecture:** Three stack members behind #1047 in stack #1072:
edges (member branch `feat/issue-702-session-reads`), cutover, sweep.
Each is green on full `make check` alone. The member that moves a
surface rewrites the tests that read or write it; rows are seeded with
`tests/session_rows.py` or a command, never `Session.objects.create`.

**Tech Stack:** Django 6, Django Ninja, pydantic, TypeScript custom
elements, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-15-issue-702-session-cutover-design.md`

## Global Constraints

- Drive everything through `make`; the gate is full `make check`.
- Comments name migrations, not issues; forward TODOs allowed.
- `make vale` on every doc and comment; refused words in
  `docs/vocabulary.md`.
- No dispatch inside a transaction; a view that dispatches carries no
  `@transaction.atomic`. Tests posting through such a view need
  `@pytest.mark.django_db(transaction=True)`.
- A refused command becomes an answer through `answered("session")`.
- Every new raise site states a `sentence`.
- A resolve inside a command goes through `library_row`.
- Name compound types and primitive roles.

---

## Member 1 — edges (`feat/issue-702-session-reads`)

### Task 1: `CreateSession` refuses the bucket; runs API answers a game

**Files:**
- Modify: `games/commands/playersession.py` (`CreateSession.build`,
  after `_live_run`)
- Modify: `games/api.py` (`PlaythroughOut`, `_readable_runs`,
  `list_playthroughs`)
- Test: `tests/test_playersession_command.py`, `tests/test_api.py`

**Interfaces:**
- Produces: `INTO_THE_BUCKET` sentence constant beside
  `INCONSISTENT_SESSION`; `CreateSession` raises `CommandRejected` with
  it when `run.kind == PlaythroughKind.IMPORTED_HISTORY`.
- Produces: `GET /api/playthrough/?game=<uuid>` narrows `_readable_runs`
  to `player_game__game_id`; `PlaythroughOut.display_name: str` resolved
  through `with_display_number` (`games/reads/playthrough_numbering.py`),
  so `_readable_runs` calls it and orders by `DISPLAY_ORDER`.

**Test cases:**
- A creation on the bucket is refused; its sentence names the game's runs.
- `?game=` answers that game's live ordinary runs only, each with
  `display_name` ("Playthrough 1" for a blank name, the name otherwise).
- `?game=` naming another library's game answers an empty list.

**Gotchas:** `with_display_number` filters `kind=ORDINARY` itself; keep
`library_runs` as the base so the library is stated twice.

- [ ] Write the failing tests
- [ ] Implement; `make test ARGS="tests/test_playersession_command.py tests/test_api.py -x"`
- [ ] Commit: `feat: refuse recording a session on the bucket; answer a game's runs (#702)`

### Task 2: the dormancy clock asks the run

**Files:**
- Modify: `games/reads/playthrough_activity.py`
  (`activity_day_expression`)
- Test: `tests/test_playthrough_activity.py`

**Interfaces:**
- The subquery reads `PlayerSession.objects.filter(playthrough=OuterRef("pk"),
  library=OuterRef("library"), removed_at__isnull=True)`, orders by
  `-effective_day`, values `effective_day`. No `TruncDate`, no zone.
- `ActivityClock.zone` stays: `boundary_day` needs it.

**Test cases:** rewrite the eleven run-condition tests to seed
`PlayerSession` rows through `tests/session_rows.py`; add: a session on a
sibling run of the same game moves no word; a session in the bucket moves
no word; a Duration-only row's stated day counts.

**Gotchas:** `test_the_clock_reads_the_viewers_zone` asserts the zone the
clock carries, not the day the subquery computes; keep it. The index is
`playersession_run_day` `(playthrough, effective_day)`.

- [ ] Write the failing tests
- [ ] Implement; `make test ARGS="tests/test_playthrough_activity.py -x"`
- [ ] Commit: `feat: read a run's own sessions on the dormancy clock (#702)`

### Task 3: `game_playtime_between`, and the playthrough page

**Files:**
- Modify: `games/reads/playtime/source.py` (protocol member),
  `legacy.py`, `projection.py`, `__init__.py`
- Modify: `games/reads/playtime_parity.py` (`COMPARED_MEMBERS`, a
  `FigureKind.GAME_IN_WINDOW` figure)
- Modify: `games/views/playthrough.py`
  (`_get_formatted_playtime_for_game_sessions_in_range`,
  `add_playthrough` seeding)
- Test: `tests/test_playtime_sources.py`, `tests/test_playtime_parity.py`,
  `tests/test_playthrough_view_cutover.py`

**Interfaces:**
- Produces: `game_playtime_between(library, game, days: DayInterval) -> timedelta`
  on both sources and the package.
- `add_playthrough` reads the game's latest and earliest session day
  through `library_sessions(library).filter(playthrough__player_game__game=game)`
  ordered by `sort_instant`; the note reads
  `game_playtime_between` over the two days.

**Test cases:** twin rows of each mode give equal figures across sources;
another library's session at a shared game is not summed; the seeded
start day is the day after the last completion, else the earliest
session's `effective_day`; a game with no session seeds "0h 00m".

**Gotchas:** the legacy read compared instants; the new one compares
days in the library's calendar. State the twin's zone as
`tests/test_playtime_sources.py` does (`TWIN_ZONE`).

- [ ] Write the failing tests
- [ ] Implement; `make test ARGS="tests/test_playtime_sources.py tests/test_playtime_parity.py tests/test_playthrough_view_cutover.py -x"`
- [ ] Commit: `feat: sum a game's playtime in a window from the projection (#702)`

### Task 4: audit, library page, device search, remove-game count

**Files:**
- Modify: `games/management/commands/audit_library_ownership.py`
- Modify: `games/views/library.py`, `games/views/game.py`
  (`_removed_with_game`), `games/api.py` (`search_devices`)
- Test: `tests/test_uuid_identity_audit.py` (or the audit's own test
  file), `tests/test_library_page_isolation.py`,
  `tests/test_removal_confirmation.py`, `tests/test_api.py`

**Interfaces:**
- Audit: derived count `PlayerSession.objects.filter(library_id__in=library_ids).count()`;
  the `Session.device` loop removed; docstring on
  `_cross_library_violations` says five loops.
- Library page: `library_sessions(library).count()`.
- Remove-game confirm: `library_sessions(library).filter(playthrough__player_game__game=game).count()`.
- Device search: `Max("player_sessions__sort_instant", filter=Q(player_sessions__removed_at__isnull=True))`.

**Test cases:** the audit reports a `PlayerSession.device` in another
library through the registry and counts projection rows; the library
page counts a projection row and not a removed one; a device last used
by a removed session sorts by its live sessions.

- [ ] Write the failing tests
- [ ] Implement; run the four files
- [ ] Full `make check`; commit: `feat: read the projection on the audit, library page and device search (#702)`
- [ ] `gh stack submit`, then `gh pr edit` with a body naming the member.

---

## Member 2 — cutover (`gh stack add feat/issue-702-session-cutover`)

### Task 5: a declared through-path for comparison operands

**Files:**
- Modify: `games/models.py` (`ProjectionModel.comparison_through`,
  `PlayerSession` declares `(("playthrough__player_game__game", "Game"),)`)
- Modify: `common/criteria.py` (`_comparison_relations`,
  `_comparison_operand_info`, `_comparison_multivalued_sources`)
- Test: `tests/test_filters.py` (the comparison sections),
  `tests/test_relation_algebra.py`

**Interfaces:**
- `comparison_through: ClassVar[tuple[tuple[str, str], ...]]` of
  `(path, label)`; each path is validated at class-check time to be
  to-one at every hop, or `games.E011` refuses it.
- The walk treats a declared path as one hop named by its label:
  `comparable_columns` lists the target's columns under that label, and
  `_comparison_operand_info` accepts `path__col` and `path__multi__col`.

**Test cases:** `playthrough__player_game__game__year_released` is a
comparable column of `PlayerSession` labelled "Game"; a two-segment
undeclared path is still refused; `playthrough__player_game__game__purchases__date_purchased`
is a multivalued operand.

- [ ] Write the failing tests
- [ ] Implement; `make test ARGS="tests/test_filters.py tests/test_relation_algebra.py -x"`
- [ ] Commit: `feat: let a projection declare a through-path for comparison operands (#702)`

### Task 6: aggregates always take the context scope

**Files:**
- Modify: `common/criteria.py` (`aggregate_to_q`)
- Test: `tests/test_aggregate_base_scope.py`, `tests/test_filters.py`

**Interfaces:** `matching = context.queryset_for(related_model)` is
built whenever `spec.scope_filter._comparison_model()` is not None;
scopes filter it further. `purchase_count` therefore counts
`Purchase.objects.for_library`.

**Test cases:** an unscoped `purchase_count` no longer counts a removed
purchase; an unscoped `session_count` on a shared catalog game counts one
library.

- [ ] Write the failing tests
- [ ] Implement; commit: `fix: scope every aggregate subquery on the library (#702)`

### Task 7: `PlayerSessionFilter`

**Files:**
- Modify: `games/filters.py` (rename `SessionFilter`; fields; handlers;
  `GameFilter.aggregates`; `GameFilter.session_filter` and
  `DeviceFilter.session_filter` lookups; `parse_session_filter` returns
  the new class; `filter_queryset_for_library` and
  `filter_query_context_for_library` branches; `model_field_registry`)
- Modify: `common/criteria.py` (`bool_running_handler`)
- Modify: `common/components/custom_elements.py`
  (`FILTER_MODE_MODELS["sessions"] = "playersession"`)
- Modify: `games/sorting.py` (`SESSION_SORTS`),
  `common/components/quick_filter.py` (`QUICK_FACETS`)
- Modify: `ts/elements/filter-tree/fixtures.json`,
  `ts/elements/filter-tree/serializer.test.ts`,
  `ts/elements/filter-tree/summary.test.ts`,
  `tests/test_filter_tree_contract.py`
- Test: `tests/test_filters.py`, `tests/test_filter_cross_entity.py`,
  `tests/test_relation_algebra.py`, `tests/test_sorting.py`,
  `tests/test_quick_filter_bar.py`, `tests/test_session_date_filter.py`,
  `tests/test_filter_bar_labels.py`, `tests/test_filter_paths.py`,
  `tests/test_filter_url.py`, `tests/test_filter_widgets.py`

**Interfaces:**
- `PlayerSessionFilter` fields: `game: UUIDMultiCriterion`
  (`playthrough__player_game__game__id`, search URL `/api/games/search`),
  `device`, `emulated`, `note`, `timing_mode: ChoiceCriterion`
  (`choices=TIMING_MODE_CHOICES`), `is_running: BoolCriterion`
  (`bool_running_handler()`), `day: DateCriterion` (`effective_day`),
  `started: DateCriterion` (`started_at__date`), `ended` (`ended_at__date`),
  `duration_hours: IntCriterion` (`duration_hours_handler("effective_duration")`),
  `created_at`, `search`, `game_filter`, `device_filter`.
- `_comparison_model()` returns `PlayerSession`.
- `GameFilter.aggregates`: `session_count` (count,
  `player_games__playthroughs__sessions`), `session_average` (avg,
  `effective_duration`, `duration_hours`), `session_playtime_hours` (sum,
  same), `purchase_count`, `playthrough_count`, `purchase_price_total`.
- `SESSION_SORTS`: `name` → `playthrough__player_game__game__sort_name`,
  `date` → `sort_instant`, `duration` → `effective_duration`, `device`,
  `created`.
- Builder URL becomes `/playersession/filter`; `_BUILDER_MODELS` derives it.

**Test cases:** every fixture case round-trips through the contract test;
`is_running` excludes a Corrected row and a finished Timed row;
`started` is null on a Duration-only row so `IS_NULL` matches it; the
drift guard over `aggregates` holds; `reachable_models("game")` names
`playersession`; a preset naming `is_manual` is refused as an unknown
field.

**Gotchas:** `filter_for_model` reads `globals()`; the class must be
named exactly `PlayerSessionFilter`. `fixtures.json` cases with
`"model": "session"` become `"playersession"` and the five game-column
comparisons take the through-path spelling from Task 5.
`make test-ts` regenerates `fixtures.canonical.json` before pytest.

- [ ] Rewrite the fixtures and TS tests; `make test-ts`
- [ ] Write the failing Python tests
- [ ] Implement; `make test-fast ARGS="-k 'filter or sort or quick' -x"`
- [ ] Commit: `feat: state the session filter on the projection (#702)`

### Task 8: the playtime source flip

**Files:**
- Modify: `games/reads/playtime/__init__.py` (`SOURCE = projection`),
  `projection.py` (`summed_by_game_matching`), `legacy.py` (member
  removed), `games/reads/playtime_parity.py` (reason string)
- Test: `tests/test_playtime_sources.py`, `tests/test_playtime_parity.py`

**Interfaces:** `projection.summed_by_game_matching(library, session_filter: PlayerSessionFilter, *, year=None) -> PlaytimeSum`
applies `session_filter.to_q(filter_query_context_for_library(library))`.
`legacy` no longer satisfies `FullPlaytimeSource`; the parity command
types it as `PlaytimeSource`.

**Test cases:** `playtime_matching` with a `timing_mode` scope sums one
mode; mypy accepts the binding (`make typecheck`).

- [ ] Commit: `feat: read every playtime figure from the projection (#702)`

### Task 9: the list, its row, and the row's components

**Files:**
- Modify: `games/views/session.py` (`list_sessions`, `session_row_data`)
- Modify: `games/formatting.py` (`session_time_range`),
  `common/components/domain.py` (`NameWithIcon(session=)`,
  `_resolve_name_with_icon`, `SessionActions`, `Duration` badge)
- Test: `tests/test_session_formatting.py`,
  `tests/test_session_time_range_timezones.py`,
  `tests/test_session_actions_component.py`, `tests/test_rendered_pages.py`,
  `tests/test_column_priority_contract.py`, `tests/test_table_width_policy.py`

**Interfaces:**
- `list_sessions` reads `library_sessions(library).select_related("playthrough__player_game__game__platform", "device")`;
  the run's display name comes from `numbered_for` over the page's
  tracked games, joined on `pk`.
- `session_time_range(session: PlayerSession, presentation)`: a
  Duration-only row formats `stated_day` as `date`; else `started_at` and
  `ended_at` in `started_at_zone`/`ended_at_zone` under "own".
- `SessionActions` reads `session.timing_mode == TIMED and session.ended_at is None`.
- `NameWithIcon(session=)` reads `session.playthrough.player_game.game`
  and takes `run_label: str | None`.

**Test cases:** a Duration-only row renders its day alone; a running
Timed row shows finish and reset, a Corrected row neither; the run label
renders only when the game holds two live runs; the list costs no query
per row.

- [ ] Commit: `feat: list sessions from the projection (#702)`

### Task 10: statistics and navbar

**Files:**
- Modify: `games/views/stats_data.py`, `games/views/stats_content.py`,
  `games/views/stats_links.py`, `games/views/general.py`
  (`model_counts`), `common/layout.py` (`recent_session_resumes`,
  `NavbarLogButton`, `Navbar` types)
- Test: `tests/test_stats.py`, `tests/test_stats_links.py`,
  `tests/test_stats_content_links.py`, `tests/test_navbar_log_button.py`,
  `tests/test_keyset.py`

**Interfaces:**
- `compute_stats` scopes `library_sessions(library)` by
  `effective_day__year`; `Game` counts cross
  `player_games__playthroughs__sessions` filtered on
  `player_games__library=library, ...removed_at__isnull=True`;
  `longest_session` orders by `effective_duration`; first/last order by
  `sort_instant` and expose `first_play_day: date | None`.
- `_session_bounds(year)` → `{"day__between": ...}`; `all_sessions`,
  `sessions_for_game`, `sessions_for_platform` build `PlayerSessionFilter`.
- `recent_session_resumes(request, limit) -> list[PlayerSession]` pages
  `library_sessions(...).select_related("playthrough__player_game__game")`
  by `("sort_instant", "id")`; resume posts the game's id, and the view
  resolves the latest live ordinary run (Task 12).

**Test cases:** the twelve link-parity tests hold; a Duration-only first
play prints its written day west of UTC; resumes skip a second session of
the same game and stop at `limit`.

- [ ] Commit: `feat: compute statistics and navbar figures from the projection (#702)`

### Task 11: the API, read half

**Files:**
- Modify: `games/api.py` (`SessionOut`, `SessionListOut`,
  `list_sessions_api`, `get_session`)
- Test: `tests/test_api.py`, `tests/test_library_api_isolation.py`,
  `tests/test_session_endpoints.py`

**Interfaces:** `SessionOut` fields as the spec lists; zone labels
through `_endpoint_zone_label`; `game: GameOut | None` via
`Field(alias="playthrough.player_game.game")`.

**Test cases:** the list answers projection rows in `sort_instant` order;
another library's row is 404 on get; a `?filter=` with a dying field is 400.

- [ ] Commit: `feat: answer sessions from the projection on the API (#702)`

### Task 12: the form, the run picker, the write path, the views

**Files:**
- Create: `games/writes/playersession.py`
- Create: `ts/elements/playthrough-select.ts`; register
  `playthrough-select` in `common/components/custom_elements.py`
  (`PlaythroughSelectProps`: `game_field`, `api_url`, `selected`)
- Modify: `games/forms.py` (`SessionForm` → `forms.Form`, `clean()`,
  `TimingDraft`), `games/views/session.py` (every view),
  `games/views/returns.py`, `games/views/game.py` and
  `games/views/purchase.py` (the redirect target is unchanged; confirm)
- Test: `tests/test_session_finish_reset.py`,
  `tests/test_session_timezone_form.py`, `tests/test_datetime_field_binding.py`,
  `tests/test_date_time_picker.py`, `tests/test_action_origin_parity.py`,
  `tests/test_removal_confirmation.py`, `tests/test_library_form_isolation.py`,
  `tests/test_playergame_view_cutover.py`, `tests/test_playergame_status_word_setters.py`,
  `tests/test_view_authentication.py`; new `tests/test_session_form_derivation.py`,
  `tests/test_session_writes.py`; `ts/elements/playthrough-select.test.ts`

**Interfaces:**
- `SessionForm(data, *, library, presentation, instance: PlayerSession | None)`;
  fields `game`, `playthrough` (`ModelChoiceField` over
  `library_runs(library)`, widget the custom element wraps), `started_at`,
  `started_at_zone`, `ended_at`, `ended_at_zone`, `day`, `duration`,
  `device`, `note`, `emulated`, `mark_as_played`.
- `SessionForm.timing_statement(day_zone: ZoneName) -> TimingStatement`
  after `is_valid()`; `clean()` raises `ValidationError` on `duration`
  for start+duration+no end ("Give an end as well, or leave the start
  empty and state the day.") and on `day` for day beside an instant.
- `games/writes/playersession.py`: `record_session(actor, draft: SessionDraft, *, correlation_id) -> PlayerSession id`,
  `restate_session(actor, session, draft, *, correlation_id)`,
  `end_session(actor, session, *, ended_at, ended_at_zone, correlation_id)`,
  `reset_session(...)`, `remove_session(...)`, `clone_session(actor, game, *, correlation_id)`;
  each `with answered("session")`, `Unchanged` swallowed; `SessionDraft`
  is a `NamedTuple` of `playthrough_id`, `timing`, `device_id`, `note`,
  `emulated`.
- Views: `add_session` and `edit_session` call the write path and
  `_record_played` as today; `finish_session`/`reset_session`/`remove_session`
  keep `confirm_and_apply`; `remove_session` no longer calls
  `confirm_and_remove`; `new_session_from_existing_session` takes a
  `game_id` and `clone_session` names the latest live ordinary run.
  `returns.py` reclassifies the renamed route.

**Test cases:** each derivation shape and the two refusals; edit of a
Timed row to Duration-only records one correction; an unchanged edit
records no event; a note-only edit records one description; moving the
run records one move; finish stamps the browser zone; reset on a
finished row is not offered (404 on POST); remove marks the row and the
list hides it; clone on a game whose latest row sits in the bucket lands
on the ordinary run; `mark_as_played` states Played under its own
`correlation_id`; the picker refills on game change and stays hidden for
one run (vitest with jsdom).

**Gotchas:** the form is no `ModelForm`; `FormFields` still renders it.
`DateTimeFieldWidget` and `TimeZoneRowWidget` stay. Tests posting the
form need `transaction=True`. The e2e files
`test_session_finish_e2e.py`, `test_session_reset_e2e.py`,
`test_time_zone_row_e2e.py`, `test_datetime_field_e2e.py` seed through
the command and move here.

- [ ] Commit: `feat: record every session through its commands (#702)`

### Task 13: the API, write half, and the device selector

**Files:**
- Modify: `games/api.py` (`SessionDeviceUpdate`, `SessionUpdate`,
  both PATCH routes), `common/components/domain.py`
  (`SessionDeviceSelector`)
- Test: `tests/test_api.py`, `tests/test_session_endpoints.py`,
  `e2e/test_device_clear_e2e.py`, `e2e/test_api_csrf_e2e.py`

**Interfaces:** `SessionUpdate(extra="forbid")`: `timing: TimedIn | DurationOnlyIn | CorrectedIn | None`,
`note`, `device_id`, `emulated`, `playthrough_id`; each named key is one
dispatch through the write path; answers 200 with `SessionOut`.

**Test cases:** an unknown key is 422; a timing off the calendar is the
command's sentence with 409; a device in another library is 404.

- [ ] Commit: `feat: write sessions through the API by command (#702)`

### Task 14: Game detail

**Files:**
- Modify: `games/views/game.py` (`_sessions_section`,
  `_game_overview_metrics`, `game` view)
- Test: `tests/test_game_detail_links.py`,
  `tests/test_game_detail_playthroughs.py`, `tests/test_rendered_pages.py`

**Interfaces:** `_game_overview_metrics(sessions: PlayerSessionQuerySet)`
averages `ended_at - started_at` over rows where it is nonzero;
`session_count`, `playrange_start`/`playrange_end` as `effective_day`.

- [ ] Commit: `feat: read Game detail's sessions from the projection (#702)`

### Task 15: every remaining test that seeds a legacy row

**Files:** the tests and e2e files the grep
`grep -rln "Session.objects.create\|Session(" tests e2e` lists, less those
Tasks 1–14 own and less `tests/test_session_preflight.py`,
`tests/test_playersession_conversion.py`, `tests/test_anonymize_sample.py`,
`tests/test_scrub_staging.py`, `tests/test_removable_models.py`,
`tests/test_removal.py`, `tests/test_generated_duration_columns.py`,
`tests/test_session_querysets.py`, `tests/test_session_identity.py`,
`tests/test_session_fk_uuid.py`, which test the legacy table and stay
until #772.

**Test cases:** unchanged in intent; seeds become `session_rows` helpers.
`tests/test_session_querysets.py` loses `without_manual`/`only_manual`
only when #772 drops the queryset; leave it.

- [ ] Rewrite; full `make check`
- [ ] Commit: `test: seed sessions through the projection (#702)`
- [ ] `gh stack submit`; PR body names the member and the three decisions.

---

## Member 3 — sweep (`gh stack add feat/issue-702-session-sweep`)

### Task 16: the import guard and the docs

**Files:**
- Create: `tests/test_session_import_guard.py` (shape of
  `tests/test_iterator_guard.py`: AST walk of `games/`, `common/`,
  `timetracker/`; `ALLOWED_FILES: dict[str, str]` with reasons)
- Modify: `docs/superpowers/specs/2026-09-12-session-wave-design.md`
  ("Delivered." paragraph under #702; both forms carry the button),
  `CLAUDE.md` (PlayerSession bullet: the cutover; `PlayerSessionFilter`;
  the builder key), `docs/superpowers/specs/2026-09-15-issue-702-session-cutover-design.md`
  (timeless)

**Interfaces:** the guard reports `from games.models import Session`,
`games.models.Session` attribute reads, and `import` of `SessionQuerySet`.

- [ ] Write the guard; it must pass on the member's tree
- [ ] `make vale`; full `make check`
- [ ] Commit: `chore: guard the legacy Session import; record the cutover (#702)`
- [ ] `gh stack submit`; `gh pr edit` each member's body; comment on #704 and #772 with what they inherit.

## Follow-ups filed

- #1074 `POST /api/session/`.
- #695 carries the restore surface.
