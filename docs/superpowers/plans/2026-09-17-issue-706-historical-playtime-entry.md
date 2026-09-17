# Historical playtime entry implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person records, restates, removes and restores a historical playtime record from Game detail.

**Architecture:** Screens over #705's four commands. A shared read module scopes records (review D1). A request-free writes module dispatches one command per act under `answered()`. One form page serves Add and Edit; removal goes through `confirm_and_apply` with Undo; a new section on Game detail lists the records.

**Tech Stack:** Django 6 / Python 3.14 / PostgreSQL 18, Python component system (`common/components`), pytest + pytest-xdist, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-17-issue-706-historical-playtime-entry-design.md`. Read it first, with `docs/review/2026-09-17-historical-playtime-parallel-specs.md` (D1 to D6, "#706: findings"). The reasons live there and are not repeated here.

## Global Constraints

- Run everything through `make`. Never `direnv exec .`, never bare `uv run` or `pytest`.
- Iterate with `make check-fast`. The gate before "done" is the full `make check`, e2e included, read by exit code.
- Focused runs: `make test ARGS="tests/test_historical_playtime_form.py -x"`.
- Any test that dispatches, or POSTs through a view that dispatches: `pytest.mark.django_db(transaction=True)` and `pytest.mark.untracked_games`. Track the game with `dispatch(TrackGame(...))` and add runs with `CreatePlaythrough`, as `tests/test_historical_playtime_command.py` does.
- No `@transaction.atomic` on a view that dispatches, and no helper that opens one.
- Every full page renders through `render_page()`. UI is built from `common.components`, in htpy form.
- Every mutating link is `action_url(name, *args, origin=...)`. Every mutating view ends in `redirect(return_url(request, fallback=...))`. No route mutates on GET.
- Widgets render to text: the form view passes `scripts=` with `ModuleScript("dist/elements/temporal-field.js")` and `ModuleScript("dist/elements/search-select.js")`.
- Complete-word identifiers. Name compound types. Comments state intent only, with no issue references.
- Never `Model.objects.get()` in a command; never `QuerySet.iterator()`.
- `make vale` covers new comments and docstrings.

---

### Task 1: The shared record scope

**Files:**
- Create: `games/reads/historical_playtime_records.py`
- Test: `tests/test_historical_playtime_records.py`

**Interfaces produced:**
- `RECORD_ORDER` (tuple of order expressions)
- `library_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet`
- `readable_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet`
- `game_records(library: UserLibrary, game: Game) -> HistoricalPlaytimeQuerySet`

- [ ] **Step 0: Check main.** `git fetch origin`. If `origin/main` already holds `games/reads/historical_playtime_records.py` (#709 or #1097 merged first), rebase onto it and skip Steps 2 and 3. Keep this task's tests only where they add a case main's tests lack.
- [ ] **Step 1: Write the failing tests.** Records are made through `RecordHistoricalPlaytime`. Cases:
  - `library_records` lists a live record;
  - it omits a removed record;
  - it omits a record whose `PlayerGame` is removed (`RemovePlayerGame`);
  - it omits a record whose catalog game is removed (`games.removal.remove(game)`). This is the case `alive()` misses;
  - it omits another library's record;
  - `game_records` narrows to one catalog game;
  - `RECORD_ORDER`: `when="2010"` before `"2005"`; unknown `when` last; on an equal `when`, the newer `created_at` first.
- [ ] **Step 2: Run them.** Expect an import error.
- [ ] **Step 3: Create the module.** Copy the Python block from review D1 on `main` exactly: docstring, the `F` import, the wrapped `games.models` import, and all four names. Add nothing.
- [ ] **Step 4: Run the tests, then `make check-fast`.** Expect pass.
- [ ] **Step 5: Commit.** `feat: scope the records a library counts`

### Task 2: Writes, the duration field and the form

**Files:**
- Create: `games/writes/historical_playtime.py`
- Modify: `games/forms.py` (after `SessionForm` and `_session_initial`)
- Test: `tests/test_historical_playtime_form.py`

**Interfaces consumed:** `HistoricalPlaytimeStatement`, `RecordHistoricalPlaytime`, `RestateHistoricalPlaytime`, `RemoveHistoricalPlaytime`, `RestoreHistoricalPlaytime`, `when_sentence` (all in `games/commands/historical_playtime.py`); `numbered_for`, `display_name`; `tracked_game`; `latest_ordinary_run` (`games/writes/playersession.py`); `TemporalFormField`; `SearchSelectWidget`.

**Interfaces produced:**
- In `games/writes/historical_playtime.py`, each with `*, correlation_id: uuid.UUID` and each inside `answered("historical playtime")`:
  - `record_historical_playtime(actor: User, statement: HistoricalPlaytimeStatement, *, correlation_id) -> uuid.UUID`
  - `restate_historical_playtime(actor, record: HistoricalPlaytime, statement, *, correlation_id) -> None`
  - `remove_historical_playtime(actor, record, *, correlation_id) -> None`
  - `restore_historical_playtime(actor, record, *, correlation_id) -> None`
- In `games/forms.py`:
  - `HoursMinutesWidget(forms.MultiWidget)` and `HoursMinutesField(forms.MultiValueField)`. The field cleans to a `timedelta`; blank cleans to `timedelta(0)`.
  - `CheckboxListWidget(forms.CheckboxSelectMultiple)` and `RadioListWidget(forms.RadioSelect)`, rendered through `Checkbox()` and `Radio()` inside a `Fieldset`/`Legend`. Add either tag to the builder whitelist in `primitives.py` if it is missing.
  - `HistoricalWhenField(TemporalFormField)`.
  - `HistoricalPlaytimeForm(PrimitiveWidgetsMixin, forms.Form)` with `__init__(self, *args, library, game, presentation, record: HistoricalPlaytime | None = None, **kwargs)` and `statement() -> HistoricalPlaytimeStatement`.

**Gotchas:**
- The `_dispatch` and `_created_id` shape is copied from `games/writes/playersession.py`: a fresh `uuid.uuid7()` idempotency key per dispatch, and the created id read from the first event's `aggregate_id`. Move `_dispatch` and `_created_id` into a shared helper only if both modules import one. Otherwise keep a local copy; do not import private names across modules.
- `HoursMinutesWidget` holds two `NumberInput`s with visible labels "Hours" and "Minutes": hours `min=0 max=99999`, minutes `min=0 max=59`. The field refuses values outside those ranges with a field error. Those are type errors, not domain rules; the maximum keeps `timedelta` from overflowing.
- `apply_primitive_widget_classes` (`games/forms.py:126-162`) gives `INPUT_CLASS` to everything that is not a `Select` or a `Textarea`, and `RadioSelect` and `CheckboxSelectMultiple` are neither. Add `HoursMinutesWidget`, `CheckboxListWidget` and `RadioListWidget` to its exemption tuple. `HoursMinutesWidget` stamps its own input classes, with no `w-full`.
- `playthroughs`: `queryset = Playthrough.objects.filter(library=library)` is what the field validates against. `choices` are set separately from `numbered_for(library, [tracked.pk])`, labelled with `display_name`, as `SessionForm` sets `runs.queryset` and `runs.choices`. Never `live_ordinary_runs` for labels: it raises `UnnumberedPlaythrough`. `required=False`.
- The Add initial is `[latest_ordinary_run(library, game).pk]` when one exists. The Edit initial is the record's run ids.
- `when`: `HistoricalWhenField.to_python` calls `TemporalFormField.to_python` and catches `ValidationError`. It reads `error.__cause__` (a `TemporalValueParseError`) and raises `ValidationError(when_sentence(cause), code=cause.code)`. `statement()` passes `None` for unknown and `value.canonical` otherwise.
- `provenance`: a `ChoiceField` with `RadioListWidget`. Add offers Estimated and Manually entered, with initial Estimated. Edit appends Externally measured only when `record.provenance` holds it.
- `device`: the queryset is `Device.objects.for_library(library)`, united (`|`) with `Device.objects.filter(library=library, pk=record.device_id)` when the record holds one. The resolver resolves over the same union.
- `clean_note`: `value.replace("\r\n", "\n")`.
- Seconds: when `record` is given, both inputs are non-blank, and the cleaned duration equals `record.duration` with its seconds removed, `statement()` carries `record.duration`.

- [ ] **Step 1: Write the failing tests.** Construct the form directly; no views yet.
  - `HoursMinutesField`: `("120", "30")` is 120 h 30 min; `("", "")` is zero; `("1", "60")`, `("-1", "0")` and `("100000", "0")` are refused.
  - A blank duration is valid in the form, and `statement().duration == timedelta(0)`.
  - Seconds are kept: a record of 1:30:20 posted as 1 h 30 min gives 1:30:20. Posted as 1 h 31 min, it gives 1:31:00. A record of 0:00:20 posted blank gives zero.
  - A note posted as `"a\r\nb"` cleans to `"a\nb"`.
  - Rendered `playthroughs` and `provenance`: one `<fieldset>`, one `<legend>`, one input per choice, and no `INPUT_CLASS` on the inputs.
  - A posted removed run validates in the form, so the command decides.
  - Provenance choices on Add are two. On Edit of an externally measured record they are three, with it initial.
  - A `when` of "2005-13" shows `WHEN_NO_SUCH_DATE` on the field. Unknown gives `statement().when is None`.
  - Add checks the latest run.
  - The choices exclude the bucket and a removed run.
  - A run with a blank name is labelled "Playthrough 2".
  - Held device: remove the device after recording. On Edit, the device renders selected and a POST with its id validates. On Add, a different removed device is refused.
  - `record_historical_playtime` returns the new record's id.
  - A refusal (zero runs) raises `CommandFailed` carrying `AT_LEAST_ONE_RUN`.
- [ ] **Step 2: Run them.** Expect failures.
- [ ] **Step 3: Implement the writes module, the field and the form.**
- [ ] **Step 4: Run the tests, then `make check-fast`.**
- [ ] **Step 5: Commit.** `feat: state historical playtime from a form`

### Task 3: Routes and views

**Files:**
- Create: `games/views/historical_playtime_entry.py`
- Modify: `games/urls.py` (import the module; four `path`s after the session block)
- Modify: `games/views/returns.py` (four names in `ORIGIN_AWARE`)
- Modify: `tests/test_paths_return_200.py` (the Add and Edit pages)
- Modify: `tests/test_view_authentication.py` (`world` gains `"record_id"`, a record made through dispatch)
- Modify: `tests/test_restore_routes.py` (`ROUTES` gains `("games:restore_historical_playtime", _removed_record, None)`; `_visible` gains a `HistoricalPlaytime` branch over `library_records`)
- Test: `tests/test_historical_playtime_views.py`

**Interfaces produced:** route names `games:add_historical_playtime` (`game_id`), `games:edit_historical_playtime`, `games:remove_historical_playtime` and `games:restore_historical_playtime` (`record_id`), with the paths in the spec's table.

**Gotchas:**
- The private resolvers are `_library_record(request, record_id)` over `readable_records(library)` (used by Edit) and `_any_library_record(request, record_id)` over `HistoricalPlaytime.objects.filter(library=library).select_related("player_game__game")` (used by Remove and Restore). Both use `owned_or_404`.
- Import the write functions as `remove_record` and `restore_record`: the views have the same names.
- Add resolves the game with `owned_or_404(Game.objects.tracked_by(library), library, id=game_id)`, as `view_game` does.
- The fallback for every redirect is `"games:view_game"` with `fallback_args=[game.pk, game.url_slug]`.
- Edit succeeds with `messages.success(request, "Historical playtime saved.")` whether or not the command answered `Unchanged`.
- A refusal is `messages.error(request, failure.message)`, and the same form is rendered again. Do not redirect.
- Remove: `confirm_and_apply(request, action=partial(remove_historical_playtime, ...), title="Remove historical playtime", message=f"Remove this historical playtime record of {game.name}?", confirm_label="Remove", fallback=..., fallback_args=..., undo=UndoOffer("Historical playtime removed.", "games:restore_historical_playtime", [record.pk]))`.
- Restore: `@require_POST`, then `restore_and_return(request, action=..., restored="Historical playtime restored.", fallback=..., fallback_args=...)`.
- Render with `AddForm(form, request=request, submit_class="", fields=FormFields(form))` and the two `ModuleScript`s.

- [ ] **Step 1: Write the failing tests.**
  - **Acceptance:** POST Add with two runs gives one record and two join rows, and redirects to the origin (`?origin=<game detail url>`). POST Edit with one run leaves one join row, and the kept run's join id is unchanged. POST Remove sets `removed_at`, and the queued message carries the restore URL. POST Restore clears `removed_at`.
  - An unchanged Edit: `LibraryEvent` count unchanged, success message shown.
  - An Edit of a record naming a removed device: the device is kept and no event is appended.
  - Refusals render the form with the command's sentence and status 200: no runs (`AT_LEAST_ONE_RUN`), zero duration (`AT_LEAST_A_SECOND`), a removed run on Add ("That playthrough was removed from your library. Restore it before recording this.", from `refuse_unless_live`; the literal is unnamed, so assert on its text or name it as a constant in `games/commands/playthrough.py`), the bucket (`INTO_THE_BUCKET_HISTORICAL`), a run of another game (`ONE_GAME`).
  - An Edit posting the stored note with CRLF appends no event.
  - A second POST to Remove redirects and appends no event.
  - Another library's record: 404 on Edit, Remove (GET and POST) and Restore. Another library's game: 404 on Add.
  - GET Remove renders the confirm page and changes nothing.
  - GET Restore answers 405.
  - Without an origin, the redirect goes to Game detail.
- [ ] **Step 2: Run them.** Expect `NoReverseMatch`.
- [ ] **Step 3: Implement the views, routes and classification.** Add the 200 cases to `tests/test_paths_return_200.py`.
- [ ] **Step 4: Run the tests, then `make check-fast`.** `tests/test_returns_classification.py`, `tests/test_view_authentication.py` and `tests/test_restore_routes.py` must pass.
- [ ] **Step 5: Commit.** `feat: record, restate and remove historical playtime`

### Task 4: The Game detail section

**Files:**
- Modify: `games/views/game.py` (`_game_section` gains `add_url: str | None = None`; new `_historical_playtime_section`; `view_game` places it between `_sessions_section` and `_playthroughs_section`)
- Test: `tests/test_game_detail_historical_playtime.py`

**Gotchas:**
- The query is `readable_records(library).filter(player_game__game=game).order_by(*RECORD_ORDER).prefetch_related("runs")`. Names come from one `numbered_for(library, [tracked.pk])` call, turned into a dict keyed by run id.
- The Add button renders beside the heading whether or not the section is empty. It is a `ControlButton(href=add_url, color="gray")` with a plus or add icon (check `games/templates/icons/` for an existing slug before adding one), and the same header layout as "View all". When both are given, both render.
- Cells are `TemporalText(record.when, presentation)`, `Duration(record.duration, durations, id_scope=f"game-historical-{record.pk}", manual=True)`, `Pill(label=HistoricalPlaytimeProvenance(record.provenance).label)`, the run names joined by ", ", the device name or "No device", and a `ButtonGroup` with Edit and Remove through `action_url(..., origin=origin)`.
- The empty message is "No historical playtime."

- [ ] **Step 1: Write the failing tests.** GET `view_game`:
  - the heading "Historical playtime" sits between "Sessions" and "Playthroughs";
  - the count badge;
  - rows in `RECORD_ORDER`, with an unknown `when` rendered "Unknown" and last;
  - a record naming two runs lists both names;
  - Edit and Remove links carry `origin`;
  - the Add link carries `origin`;
  - the empty state, with the Add link still present;
  - a removed record is absent.
  - (A removed catalog game is Task 1's test: Game detail answers 404 for one.)
- [ ] **Step 2: Run them.** Expect failures.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests, then `make check-fast`.**
- [ ] **Step 5: Commit.** `feat: list historical playtime on Game detail`

### Task 5: Browser path, docs and the second-merge work

**Files:**
- Create: `e2e/test_historical_playtime_entry_e2e.py`
- Modify: `CLAUDE.md` (the HistoricalPlaytime entry, review D5)
- Modify, only if #1097 is on `main` (review D4): #1097's Historical list view and `games/views/game.py`

**Gotchas:**
- Run `make ts` before e2e. Never run e2e while `make dev` is up.
- Make the game through dispatch, as in Task 2, so it has one run. Add the second with `tests/stated_runs.another_run`, which e2e may import.
- Wait on the server-rendered section (`#historical-playtime-container` or the row text) before any ORM read.
- Fill the `temporal-field` as `e2e/test_temporal_field_e2e.py` does.
- Undo: click the toast's Undo button, then wait for the row to reappear.

- [ ] **Step 1: Write the e2e test.** Game detail → Add → year 2005, 100 h, two runs, Estimated → Save. The row shows two run names. Edit, uncheck one run, Save; the row shows one name. Remove, confirm; the row is gone. Undo; the row is back.
- [ ] **Step 2: Run it.** `make test-e2e` with `PYTEST_WORKERS=0` when debugging. Expect pass.
- [ ] **Step 3: CLAUDE.md.** Replace "Nothing reads or writes it from a page yet." with one sentence: Game detail records, restates, removes and restores records through `games/views/historical_playtime_entry.py`. If `main` changed that sentence, keep `main`'s and append this one.
- [ ] **Step 4: Review D4.** `git fetch origin`. If #1097 has merged, add its list's Actions column (Edit and Remove via `action_url` with origin) and the section's `view_all_url` (the list narrowed to the game with #1097's filter), each with a test. If it has not, do nothing; #1097 carries it.
- [ ] **Step 5: Gate.** Rebase on `origin/main`. Run `make check`, read its exit code from a log, and confirm it is 0.
- [ ] **Step 6: Commit.** `test: record historical playtime in the browser` (plus `docs:` for CLAUDE.md)
- [ ] **Step 7: Docs sweep.** Delete this plan. Rewrite the spec so it is timeless. Trim new comments.

## Self-review

- Spec coverage: shared scope (T1), writes (T2), form rows (T2), seconds and held device (T2), routes, returns and refusals (T3), Undo (T3, T5), section (T4), CLAUDE.md and D4 (T5), gate (T5).
- Names used across tasks: `readable_records`, `RECORD_ORDER`, `record_historical_playtime`, `HistoricalPlaytimeForm.statement()`, and the four route names.
