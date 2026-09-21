# Search select creates a row from the typed name — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `<search-select>` whose query names no option offers a `Create “…”` row that POSTs the typed name, takes back the new row, and selects it.

**Architecture:** Two new props on one element (`params`, carried as JSON text; `create_url`), one new row kind in the panel, four API routes, and one new command whose build decides between adopting a placeholder run and creating one. Three consumers adopt it: both device pickers, the session form's run picker, the purchase form's platform.

**Tech Stack:** Django 6 + Django Ninja, Python 3.14, TypeScript custom elements + vitest, pytest + pytest-playwright.

**Spec:** [docs/superpowers/specs/2026-09-21-issue-1080-search-select-create-design.md](../specs/2026-09-21-issue-1080-search-select-create-design.md)

**Issue:** [#1080](https://github.com/KucharczykL/timetracker/issues/1080). [#714](https://github.com/KucharczykL/timetracker/issues/714) blocks on member 1.

## Global Constraints

- Every command runs through `make`. No `direnv exec .`, no bare `uv run` / `pnpm` / `pytest`.
- `make check-fast` while iterating. The gate is one full `make check`, under the shared lock:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`.
- `make format` and `make format-check` before every commit, documentation included.
- Run `make ts` after editing any `.ts`, and `make gen-element-types` after editing an element's props.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Prose in `docs/` and in comments is linted by `make vale`. Read [Vocabulary](../../vocabulary.md) before writing either.
- Unabbreviated identifiers in Python and TypeScript. A compound value passed between functions gets a named type.
- A test that POSTs through a view that dispatches needs `@pytest.mark.django_db(transaction=True)`.
- Two members, as one `gh stack`. Member 1 is tasks 1–8; member 2 is tasks 9–10.

---

## File structure

**Member 1**

| File | Responsibility |
|---|---|
| `games/api.py` | Four routes: a run search, the run POST's new body and answer, a device POST, a platform POST. |
| `games/commands/playthrough.py` | `CreatePlaythrough.name`; the new `RecordPlaythroughByName`. |
| `games/events/dispatch.py` | One `CommandName` member. |
| `games/writes/playthrough.py` | `record_named_run`, the request-free write path. |
| `games/api_creation.py` (create) | `created_row(form) -> CreatedRow` and the sentence flattening both form routes share. |
| `common/components/custom_elements.py` | Three `SearchSelectProps` members and the `CreateParams` named role. |
| `common/components/search_select.py` | The create-row node, the two new `SearchSelect` arguments. |
| `ts/elements/search-select.ts` | Param resolution, dependency re-search, the create row's render and commit. |
| `ts/elements/search-select.create.test.ts` (create) | The create row's vitest cases. |
| `games/forms.py` | `SearchSelectWidget` gains `create_url`, `params`, `csrf`; both device fields state `create_url`. |

**Member 2**

| File | Responsibility |
|---|---|
| `games/forms.py` | `PlaythroughSelectWidget` renders a `SearchSelect`; `_run_options`; the purchase form's platform states `create_url`. |
| `ts/elements/playthrough-select.ts`, `.test.ts` | Both go: the element has no job left. |
| `common/components/custom_elements.py` | `PlaythroughSelectProps` and its registration go. |

---

## Task 1: The run search route

**Files:**
- Modify: `games/api.py:304` (`_readable_runs`), `games/api.py:328` (beside `list_playthroughs`)
- Test: `tests/test_playthrough_api_reads.py`

**Interfaces:**
- Produces: `GET /api/playthrough/search?game=<uuid>&q=<text>&limit=<int>` answering `list[PlaythroughOption]`, a schema of `value: str`, `label: str`, `data: dict[str, str]` — the shape `search_devices` answers at `games/api.py:414`.

**Gotchas:** `list_playthroughs` answers `PlaythroughOut`, which states `display_name` and no `value`; the element's `buildRow` reads `option.value` and `option.label` (`ts/elements/search-select.ts:396`). Do not widen the list route — a picker and a client reading a run are different readers. `_readable_runs` already numbers each row through `with_display_number`, so `label` is `display_name(run)`. `game` is required here, unlike on the list route: a picker never lists every library run.

- [ ] **Step 1: Write the failing tests.** In `tests/test_playthrough_api_reads.py`:
  - `test_the_search_answers_option_shaped_rows` — one run at a game; assert the body is `[{"value": str(run.pk), "label": "Playthrough 1", "data": {}}]`.
  - `test_the_search_narrows_on_the_query` — two runs, one named `New Game Plus`; `?q=plus` answers one row.
  - `test_the_search_answers_no_run_of_another_game` — a second game's run is absent.
  - `test_the_search_answers_no_removed_run` — a removed run is absent.
  - `test_the_search_answers_no_imported_history_bucket` — a bucket run is absent. This is the contract #714 reads; name it so a later change cannot admit the bucket in silence.
- [ ] **Step 2: Run them.** `make test-fast ARGS="tests/test_playthrough_api_reads.py -k search"`. Expected: 404s.
- [ ] **Step 3: Implement.** Add `PlaythroughOption(Schema)` and the route, reading `_readable_runs(library).filter(player_game__game_id=game)` and `name__icontains` on `q`. Register nothing — the router is already mounted.
- [ ] **Step 4: Run them.** Same command. Expected: pass.
- [ ] **Step 5:** `make format && make format-check`, then commit.

---

## Task 2: `CreatePlaythrough` takes a name

**Files:**
- Modify: `games/commands/playthrough.py:112-181`
- Test: `tests/test_playthrough_commands.py`

**Interfaces:**
- Produces: `CreatePlaythrough(game_id=…, started=…, completed=…, note="", name="")`.

**Gotchas:** The build already appends `playthrough_note_changed(run_id, note=self.note)` when `note` is non-blank (`games/commands/playthrough.py:168`); the name is the same shape with `playthrough_name_changed(run_id, name=self.name)` (`games/events/playthrough.py:202`). Strip `name` in `__post_init__` beside `note`, or a restatement fingerprints differently. The new field changes `canonical_command_input`; harmless, because `_dispatch` mints a key per call (`games/writes/playthrough.py:79`) and no test pins the field set — do not add an idempotency key here to compensate.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_creation_states_the_name_it_carries` — dispatch with `name=" NG+ "`; the row's `name` is `"NG+"`.
  - `test_a_creation_with_no_name_appends_no_name_event` — assert the event types are exactly `("library.playthrough.created",)`.
- [ ] **Step 2: Run them.** `make test-fast ARGS="tests/test_playthrough_commands.py -k name"`. Expected: `TypeError` on the unknown keyword.
- [ ] **Step 3: Implement.** Add the field, the strip, and the conditional append.
- [ ] **Step 4: Run them.** Expected: pass.
- [ ] **Step 5:** Commit.

---

## Task 3: `RecordPlaythroughByName`

**Files:**
- Modify: `games/events/dispatch.py:92` (a `CommandName` member), `games/commands/playthrough.py`, `games/writes/playthrough.py`
- Test: `tests/test_playthrough_by_name.py` (create)

**Interfaces:**
- Produces: `CommandName.PLAYTHROUGH_RECORD_BY_NAME = "library.playthrough.record_by_name"`; `RecordPlaythroughByName(game_id: uuid.UUID, name: str)`; `record_named_run(actor: User, game: Game, name: str, *, correlation_id: uuid.UUID) -> NamedRun` where `NamedRun` is a `NamedTuple` of `playthrough_id: uuid.UUID`, `label: str`, `tracked_the_game: bool`.

**Gotchas:** The adopt read lives in `build`, never in the write path. `record_run` reads `run_to_adopt` before dispatching (`games/writes/playthrough.py:357`) and its own docstring names the race; here the race is the harm the rule exists to refuse. A placeholder is the game's sole live ordinary run stating no start, no completion and a blank `name`, that `blocking_referrer(run)` (`games/commands/playthrough.py:551`) answers `None` for — that helper already reads both `PlayerSession.playthrough` and `HistoricalPlaytimeRun.playthrough`, alive and library-scoped, which is exactly the two referrers the rule names. Reuse it; a second read of the same fact would drift. The untracked game follows `record_run`'s shape: catch `PlayerGameNotTracked`, call `track_game`, state again once. `TrackGame` mints a blank ordinary run (`games/commands/playergame.py:80`), so the second pass adopts it and the game ends with one named run — assert that, it is the whole reason the retry is not a second creation. The build's adopt branch answers `[playthrough_name_changed(run.pk, name=…)]` against the existing key; the create branch answers what `CreatePlaythrough` answers. Refuse a blank name and a removed game, each with its own sentence, and answer `Unchanged` where the adopted run already states that name.

- [ ] **Step 1: Write the failing tests.** In `tests/test_playthrough_by_name.py`, all `@pytest.mark.django_db(transaction=True)`:
  - `test_a_placeholder_is_adopted_and_named` — a tracked game whose sole run states nothing; the answer's `playthrough_id` is that run's, and the run count stays 1.
  - `test_a_run_holding_a_session_is_not_adopted` — the sole run states nothing but a live session names it; a second run is created.
  - `test_a_run_holding_a_record_is_not_adopted` — same, with a live `HistoricalPlaytimeRun`.
  - `test_a_named_run_is_not_adopted` — the sole run already states a name.
  - `test_a_started_run_is_not_adopted` — the sole run states a start.
  - `test_two_runs_adopt_neither` — the game holds two runs.
  - `test_an_untracked_game_ends_with_one_named_run` — the game is untracked; afterwards the library holds exactly one ordinary run at it, named, and the answer states `tracked_the_game is True`.
  - `test_a_removed_game_is_refused` / `test_a_blank_name_is_refused` — each `pytest.raises(CommandRejected)` with a sentence.
  - `test_the_same_name_twice_answers_unchanged`.
- [ ] **Step 2: Run them.** `make test-fast ARGS="tests/test_playthrough_by_name.py"`. Expected: import error.
- [ ] **Step 3: Implement** the `CommandName` member, the command, and `record_named_run` under `answered("playthrough")`.
- [ ] **Step 4: Run them,** then `make test-fast ARGS="tests/test_command_answers.py tests/test_command_scope_guard.py tests/test_projection_replay_gate.py"` — the first walks every module whose exceptions reach the boundary, the second refuses a bare manager `.get()` in a build, the third replays the command stream.
- [ ] **Step 5:** Commit.

---

## Task 4: The run POST states a name and answers a body

**Files:**
- Modify: `games/api.py:349-369`, `games/api.py:180` (`PlaythroughIn`)
- Test: `tests/test_playthrough_api_writes.py:52`, `:85`

**Interfaces:**
- Produces: `CreatedRow(Schema)` in `games/api.py` — `id: str`, `label: str` — the one answer every create route states, which task 5 imports. `POST /api/playthrough/` answers `201 CreatedRow`; its body gains `name: str = ""`.

**Gotchas:** The route answers `Status(204, None)` today and two tests pin it; both change, and nothing else in `ts/`, `e2e/` or `games/` posts to it. Follow `create_session` (`games/api.py:838`) for the `response={201: …}` shape. A body stating a `name` and nothing else goes through `record_named_run`; a body stating a temporal act keeps `record_run`, because a person filling the add-run form asked for that form's rule. State this split in the route's docstring — it is the one place two write paths meet. The success message is already queued (`messages.success`), which is what carries the toast.

- [ ] **Step 1: Write the failing tests.** In `tests/test_playthrough_api_writes.py`:
  - Change the two `assert response.status_code == 204` to `201`, and assert the body holds `id` and `label`.
  - `test_a_name_alone_adopts_the_placeholder` — a tracked game with a placeholder; the answered `id` is that run's key.
  - `test_the_answer_labels_a_blank_name_by_its_number` — creating with a temporal act and no name answers `label == "Playthrough 2"`.
- [ ] **Step 2: Run them.** `make test-fast ARGS="tests/test_playthrough_api_writes.py"`. Expected: the status assertions fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** Expected: pass.
- [ ] **Step 5:** Commit.

---

## Task 5: The device and platform POSTs

**Files:**
- Create: `games/api_creation.py`
- Modify: `games/api.py` (beside `search_devices:414` and `search_platforms:431`)
- Test: `tests/test_row_creation_api.py` (create)

**Interfaces:**
- Consumes: task 4's `CreatedRow`.
- Produces: `POST /api/devices/` and `POST /api/platforms/`, each taking `{"name": str}` and answering `201 CreatedRow`; `created_row(form: forms.ModelForm) -> CreatedRow` and `refusal_sentence(form: forms.ModelForm) -> str` in `games/api_creation.py`.

**Gotchas:** `DeviceForm.type` is required — `Device.type` states a default but no `blank=True` — so the route supplies `type=Device.UNKNOWN`. `PlatformForm`'s `icon` and `group` are optional, and `Platform.save` slugifies the icon. Both forms take `library=` and set `instance.library`, so a created platform is private. Two rules refuse a duplicate platform and they are not the same rule: `Platform.clean` refuses a private row shadowing a **shared** one, and the private `UniqueConstraint` refuses the library's own duplicate through `_LibraryBoundConstraintValidationMixin`. `Platform.clean` states a non-field error, so `refusal_sentence` must read `form.errors` including `__all__` — a sentence built from field errors alone would answer an empty string there. Ninja's own 422 for a missing `name` queues no message; that is acceptable, because the element never posts a blank name. Queue `messages.error(request, sentence)` on the refusal: nothing else puts it on `HX-Trigger`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_row_creation_api.py`:
  - `test_a_device_is_created_with_the_unknown_type` — 201, and the row's `type` is `Unknown`.
  - `test_a_platform_is_created_private_to_the_library` — 201, and `platform.library_id == user.library_id`.
  - `test_a_platform_shadowing_a_shared_row_is_refused` — a shared `Platform` of that name exists; 422, and the answered `detail` is not empty.
  - `test_a_platform_the_library_already_holds_is_refused` — 422.
  - `test_a_refusal_queues_its_sentence` — assert the response carries `HX-Trigger`.
  - `test_another_library_creates_its_own_platform_of_the_same_name` — 201, two private rows.
- [ ] **Step 2: Run them.** `make test-fast ARGS="tests/test_row_creation_api.py"`. Expected: 404s.
- [ ] **Step 3: Implement** `games/api_creation.py` and both routes.
- [ ] **Step 4: Run them,** then `make test-fast ARGS="tests/test_paths_return_200.py"`.
- [ ] **Step 5:** Commit.

---

## Task 6: `params` — the prop and the dependency

**Files:**
- Modify: `common/components/custom_elements.py:594` (`SearchSelectProps`), `common/components/search_select.py:437` (`SearchSelect`'s signature) and `:568` (the `_SearchSelect` call)
- Modify: `ts/elements/search-select.ts:427` (the URL build)
- Test: `ts/elements/search-select.params.test.ts` (create)

**Interfaces:**
- Produces: `type CreateParams = str` in `custom_elements.py`; `SearchSelectProps` members `params: CreateParams`, `create_url: str`, `csrf: str`; `SearchSelect(..., params: dict[str, ParamSource] | None = None, create_url: str = "", csrf: str = "")` where `ParamSource` is `LiteralParam = TypedDict("LiteralParam", {"value": str})` or `FieldParam = TypedDict("FieldParam", {"field": str})`. TypeScript reads the parsed object as `Record<string, {value: string} | {field: string}>`.

**Gotchas:** Props are attributes. `_named_role` raises `TypeError` for anything that is not `int`, `float`, `str` or `bool` (`common/components/custom_elements.py:143`), and the reader is `getAttribute` — so `params` travels as JSON text, the way `FilterJson` and `SelectionScope` do (`common/components/primitives.py:2271`). Serialize with `json.dumps` in `SearchSelect`, parse once in `connectedCallback`, and report a parse failure through `reportClientError` rather than throwing. A field source reads the value from the hosting `<form>` through `new FormData(form).get(fieldName)`, at the moment it is used, never cached: the game picker writes its value to a hidden input. A field source is also a dependency — listen for `search-select:change` and `change` on the form, and when a depended-on field's value differs from the one last searched, search again and drop a selection the new value does not hold. `search_url` already composes with a query string (`PresetSelect` ships `?mode=`), so append params with `URL.searchParams.set` and do not assume `?` is free.

- [ ] **Step 1: Write the failing tests.** In `ts/elements/search-select.params.test.ts`:
  - `a literal param rides the search URL`.
  - `a field param reads the form's current value`.
  - `a change to a depended-on field searches again`.
  - `a change to a depended-on field drops the held selection`.
  - `an unparseable params attribute searches without them and reports`.
- [ ] **Step 2: Run them.** `make test-ts`. Expected: fail.
- [ ] **Step 3: Implement** the prop, the Python argument, and the TypeScript. Run `make gen-element-types` and check `ts/generated/props.ts` gained `params`, `createUrl`, `csrf`.
- [ ] **Step 4: Run** `make test-ts && make ts-check`.
- [ ] **Step 5:** Commit.

---

## Task 7: The create row

**Files:**
- Modify: `common/components/search_select.py:363` (`_combobox_children`, beside the no-results node)
- Modify: `ts/elements/search-select.ts` — `getVisibleOptions:200`, `renderRows:349`, `setNoResults:229`, `autoHighlight:296`, the Enter branch `:614`, the click branch `:689`
- Test: `ts/elements/search-select.create.test.ts` (create)

**Interfaces:**
- Produces: a row node carrying `data-search-select-create`, rendered after the no-results node when `create_url` is stated, with a `[data-label]` slot the client fills with the query.

**Gotchas:** The row is its own kind, as modifier rows are: `renderRows` empties every `[data-search-select-option]` on each answer (`:349`), so a create row wearing that attribute would vanish mid-keystroke. It must be read by `getVisibleOptions`, `hasVisibleContent` (`:200`, which decides whether a hosted panel opens at all — a panel holding only a create row must open), the Enter branch and the click branch. It **replaces** the no-results node rather than standing beside it. It appears only after the answer decides, which is the rule `setNoResults` already follows for a `search_url` — the comment at `:466` names the flash it avoids. The appearance test is **equality**, trimmed and case-ignored, against every loaded option's label; the panel's own filter is `label.includes(query)` (`:399`), and a rule built on that would refuse to create `PlayStation` beside `PlayStation 4`. A blank query never renders it. Disable it while its own POST is in flight, or a second Enter creates a second row — no route takes an idempotency key. POST through `fetchWithHtmxTriggers` (`ts/toast.ts`) with the `csrf` prop as `X-CSRFToken`; the middleware reads no request header (`games/htmx_middleware.py`), so the toast arrives on a plain POST. On the answer, upsert on the id: an id the panel already holds takes the new label, any other id is inserted — a run creation may adopt, and answer a key the panel already lists. Then select it and replace the query with its label. Ignore the attribute while `filter-mode` or `free-text` is true; `FilterSelect` and `PresetSelect` take no `create_url` argument, so there is nothing to raise on at render.

- [ ] **Step 1: Write the failing tests.** In `ts/elements/search-select.create.test.ts`:
  - `offers the row when no loaded label equals the query`.
  - `offers the row for a query a longer label holds` — `PlayStation` beside `PlayStation 4`.
  - `offers no row when a label equals the query, case ignored`.
  - `offers no row for a blank query`, `offers no row without create_url`, `offers no row in filter mode`.
  - `waits for the answer before offering the row`.
  - `replaces the no-results node`.
  - `Enter on the row posts the name and the params`.
  - `a click on the row posts`.
  - `a second Enter posts nothing while the first is in flight`.
  - `the answered row is selected and the query becomes its label`.
  - `an id the panel already holds takes the new label and is not inserted twice`.
  - `a refusal keeps the query and selects nothing`.
  - `a panel holding only the create row opens`.
- [ ] **Step 2: Run them.** `make test-ts`. Expected: fail.
- [ ] **Step 3: Implement** the node and the six TypeScript call sites.
- [ ] **Step 4: Run** `make test-ts && make ts-check && make test-fast ARGS="tests/test_rendered_pages.py"`.
- [ ] **Step 5:** Commit.

---

## Task 8: Both device pickers

**Files:**
- Modify: `games/forms.py:269` (`SearchSelectWidget.__init__` and `render`), `:909` (`SessionForm.device`), `:1157` (`HistoricalPlaytimeForm.device`)
- Test: `tests/test_forms.py`, `e2e/test_session_form_e2e.py`

**Interfaces:**
- Consumes: Task 5's `POST /api/devices/`, Task 6's `SearchSelect` arguments.
- Produces: `SearchSelectWidget(..., create_url: str = "", params: dict[str, ParamSource] | None = None)`, threading the request's CSRF token.

**Gotchas:** The widget renders through `render(SearchSelect(...))` and has no request; the CSRF token reaches it the way `SelectDropdown` threads `data_csrf` (`common/components/custom_elements.py:1339`) — the hosting form sets it in `__init__`, from `django.middleware.csrf.get_token(request)`. Both device fields get the same `create_url`: they read one search route and state one gap, and a create row on one alone reads as an accident. `HistoricalPlaytimeForm.device`'s queryset is `Device.objects.for_library` (`games/forms.py:1218`), so a device created mid-form validates on submit. No `params`: a device names no parent.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_forms.py::test_the_session_form_device_offers_a_create_url` and the historical playtime twin — assert the rendered widget carries `create-url="/api/devices/"`.
  - `e2e/test_session_form_e2e.py::test_a_session_records_on_a_device_created_from_the_picker` — type a name no device holds, press Enter, wait on the server-rendered section, submit, and assert the session's device. **UI assertion is not database assertion**: wait for the swapped-in section before reading the ORM.
- [ ] **Step 2: Run them.** `make test-fast ARGS="tests/test_forms.py -k create_url"` then `make test-e2e ARGS="-k created_from_the_picker"`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both again, then the member's gate: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`.
- [ ] **Step 5:** Commit, then `gh stack` member 1 and open its PR.

---

## Task 9: The run picker becomes a `SearchSelect`

**Files:**
- Modify: `games/forms.py:739` (`PlaythroughSelectWidget`), `:772` (`_run_choices` becomes `_run_options`), `:814-816` (`SessionForm.__init__`)
- Modify: `common/components/custom_elements.py:219-228` — `PlaythroughSelectProps` and its registration go
- Remove: `ts/elements/playthrough-select.ts`, `ts/elements/playthrough-select.test.ts`
- Test: `tests/test_forms.py`, `e2e/test_session_form_e2e.py`

**Interfaces:**
- Consumes: Task 1's `/api/playthrough/search`, Task 4's `POST /api/playthrough/`, Tasks 6–7.
- Produces: `_run_options(values, *, library) -> list[SearchSelectOption]`, the resolver shape `_device_options` uses at `games/forms.py:262`.

**Gotchas:** The hide rule goes. `<playthrough-select>` hides its row while the list holds one option or none (`ts/elements/playthrough-select.ts:63`, pinned by `playthrough-select.test.ts:41`), and that is the very game this issue is about — nobody types into a hidden control. With the element gone, the sole run must still be committed: a `SearchSelect` with a `search_url` pre-renders no rows (`common/components/search_select.py:499`) and holds a value only through a pick, so after a search that answers exactly one run and nothing is held, commit it through the element's own `setSelected`. `SessionForm.playthrough` is a required `ModelChoiceField`, so a form that posts nothing is a validation error, not a silent miss — assert the filled case. A bound re-render resolves the held run to its label through `_run_options`, which is why the resolver exists. `SessionForm.clean` already refuses a run of another game (`games/forms.py:924`); keep it, it is the backstop for a stale selection. Run `make gen-element-types` after taking the props away, and `make ts` so the stale `dist/elements/playthrough-select.js` does not linger.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_forms.py::test_the_run_picker_renders_a_search_select` — the rendered field carries `search-url="/api/playthrough/search"` and `create-url="/api/playthrough/"`.
  - `tests/test_forms.py::test_the_run_picker_labels_a_held_run` — a bound form states the run's display name in the search box.
  - `e2e/…::test_the_run_picker_is_visible_on_a_game_holding_one_run` — the row is not hidden.
  - `e2e/…::test_a_session_records_on_a_run_created_from_the_picker` — one submit, and the session's run is the named one.
  - `e2e/…::test_the_run_picker_refills_when_the_game_changes`.
- [ ] **Step 2: Run them.** `make test-fast ARGS="tests/test_forms.py -k run_picker"`, `make test-e2e ARGS="-k run_picker or created_from_the_picker"`. Expected: fail.
- [ ] **Step 3: Implement,** and take the element and its test away:

```bash
git rm ts/elements/playthrough-select.ts ts/elements/playthrough-select.test.ts
```

- [ ] **Step 4: Run** `make gen-element-types && make ts && make test-ts`, then the two test commands.
- [ ] **Step 5:** Commit.

---

## Task 10: The purchase form's platform

**Files:**
- Modify: `games/forms.py:1394` (`PurchaseForm.platform`)
- Test: `tests/test_forms.py`, `e2e/test_purchase_form_e2e.py`

**Interfaces:**
- Consumes: Task 5's `POST /api/platforms/`, Task 8's widget arguments.

**Gotchas:** The issue names "Add Game's platform" and no such field exists — `GameForm.Meta.fields` is `("name", "sort_name")`; the platform moved to the release row, a plain `<select>` in a cloned block (`games/catalog_form.py:119`). The purchase form holds the platform picker that is a `SearchSelect`, and it is the consumer here. Leave the release row alone; task 11 files the follow-up. The created platform is private, so it appears in `Platform.objects.visible_to(library)` and the field validates on submit.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_forms.py::test_the_purchase_platform_offers_a_create_url`.
  - `e2e/test_purchase_form_e2e.py::test_a_purchase_records_on_a_platform_created_from_the_picker`.
- [ ] **Step 2: Run them.** Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** The gate, under the lock: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`. Confirm green from the log's exit code, never from a grep.
- [ ] **Step 5:** Commit, add the member to the stack, `gh stack submit`.

---

## Task 11: The documentation sweep

**Files:**
- Modify: `CLAUDE.md` (the `search_select.py` bullet, the REST API list, the `Interactive components` section)
- Remove: this plan

**Gotchas:** `CLAUDE.md`'s component list names `SearchSelect()` and its flavors; add the two props in one clause. The REST API list gains four routes. The `<playthrough-select>` mention under the session cutover paragraph goes. Keep the spec — it is the durable half. No full `make check` for a documentation-only change; `make vale` and `make format-check` are the gate.

- [ ] **Step 1:** Edit `CLAUDE.md`.
- [ ] **Step 2:** `make vale && make format && make format-check`.
- [ ] **Step 3:** `git rm docs/superpowers/plans/2026-09-21-issue-1080-search-select-create.md` and commit.

---

## Follow-up issues filed

1. #1222 — the release row's platform becomes a `SearchSelect` with a create row. The comment at `games/catalog_form.py:119` calls a composite widget impossible in a cloned row; it is stale, and the issue says why.
2. #1223 — the create routes read an `Idempotency-Key`, as `POST /api/session/` does. The element disabling its row while a POST is in flight is a client-side guard; a retried request still creates a second row.
