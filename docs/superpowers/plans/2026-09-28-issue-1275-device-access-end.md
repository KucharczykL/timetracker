# Device access end and the stated endpoint: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the playthrough endpoint machinery into a reusable stated-endpoint primitive, then let a library state that its access to a device ended (sold, lost, given away, broken, stolen).

**Architecture:** An `Endpoint` descriptor names one endpoint's columns and its three event specs; field factories, a system check, projector helpers, command skeleton functions, a pure move decision and filter-field builder hang off it. Playthrough start/completion move onto it with zero behaviour change (member 1); `Device` gains `DEVICE_ACCESS_END` (member 2).

**Tech Stack:** Django 6, PostgreSQL 18, pydantic `TypedDict` payloads, Django Ninja, TypeScript custom elements, pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-28-issue-1275-device-access-end-design.md` — read it first; this plan names files, interfaces and cases, the spec holds the reasons.

## Global Constraints

- Run everything through `make`; wrap every pytest target in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- Member 1 changes no recorded spelling: event types, `CommandName`s, command fields, columns, filter keys, labels, rendered pages.
- Device events: `library.device.access_ended`, `library.device.access_end_corrected`, `library.device.access_end_voided`.
- Device columns: `access_ended`, `access_ended_lower`, `access_ended_upper`, `access_end_recorded_at`, `access_end_note`, `access_end_way` (`""` when unstated).
- Device ways, recorded spelling: `sold`, `lost`, `given_away`, `broken`, `stolen`; labels Sold, Lost, Given away, Broken, Stolen; the unstated choice reads "Held".
- Every refusal carries a `sentence=`; comments state intent only, no issue numbers; complete-word identifiers; `make format`, `make lint-fix` and `make vale` before each commit.
- Iterate with `make check-fast`; the gate is one full `make check` at the end.

## Delivery

Branch `claude/issue-1275-stated-endpoint` (member 1, Tasks 1–5) and `claude/issue-1275-device-access-end` (member 2, Tasks 6–12), built with `gh stack init` / `gh stack add`, opened with `gh stack submit`.

---

### Task 0: Stack and baseline

- [ ] Rebase onto `origin/main`; `gh stack init` member 1 branch; move the spec and plan commits onto it.
- [ ] `make loadsample` into the dev database if empty; `make devlogin`; `make render-pages ARGS="--user admin --out /tmp/…/pages-before"` (scratchpad). Keep the directory for Task 5 and Task 12.

---

## Member 1: the stated-endpoint primitive

### Task 1: Pin fingerprints, then the event factory and the descriptor

**Files:**
- Create: `games/events/endpoint.py`, `games/endpoints.py`, `tests/test_endpoint_fingerprints.py`, `tests/test_endpoint_primitive.py`
- Modify: `games/events/playthrough.py`

**Interfaces — produces:**
- `class EndWay(StrEnum)`: `SOLD="sold"`, `LOST="lost"`, `GIVEN_AWAY="given_away"`, `BROKEN="broken"`, `STOLEN="stolen"`; `END_WAY_LABELS: Mapping[EndWay, str]`.
- `EndpointPayload(TypedDict): note: str` (moved from `PlaythroughEndpointPayload`; keep that name as an alias export).
- `class EndpointEvents(NamedTuple): stated: EventSpec; corrected: EventSpec; voided: EventSpec`.
- `endpoint_events(aggregate_type: str, *, stated: str, corrected: str, voided: str, payload: type, voided_payload: type) -> EndpointEvents` — builds and registers on `DEFAULT_EVENT_TYPES`.
- `@dataclass(frozen=True) class Endpoint`: `name: str`, `model: type[ProjectionModel]` (resolved lazily by label string to dodge the import cycle: `model_label: str` + `model` property via `apps.get_model`), `when`, `lower`, `upper`, `marker`, `note: str`, `way: str | None`, `events: EndpointEvents`, `ways: tuple[EndWay, ...]`; property `family -> tuple[str, str, str]` (type strings).
- `ENDPOINTS: tuple[Endpoint, ...]` registry, `PLAYTHROUGH_START`, `PLAYTHROUGH_COMPLETION` in `games/endpoints.py`.

- [ ] **Step 1: Fingerprint pin (before any refactor).** In `tests/test_endpoint_fingerprints.py`, for `StartPlaythrough`, `CompletePlaythrough`, `CorrectPlaythroughStart`, `CorrectPlaythroughCompletion`, `VoidPlaythroughStart`, `VoidPlaythroughCompletion` and a `CreatePlaythrough` with both `ActStatement`s, build with fixed UUIDs and a fixed `TemporalValue`, compute `canonical_command_input(command)` (games/events/dispatch.py) and assert against literal strings captured from the current code. Run `make test ARGS="tests/test_endpoint_fingerprints.py"` → PASS on main code. Commit.
- [ ] **Step 2: Failing primitive tests.** `tests/test_endpoint_primitive.py`: `PLAYTHROUGH_START.events.stated.event_type == "library.playthrough.started"` (and the other five); `PLAYTHROUGH_START.family` equals the tuple `games/bulk_playthrough_acts.py` builds today; every `ENDPOINTS` member's specs are registered. Run → FAIL (import).
- [ ] **Step 3: Implement** `games/events/endpoint.py` and `games/endpoints.py`; rewrite the six spec constants in `games/events/playthrough.py` as `PLAYTHROUGH_START_EVENTS = endpoint_events("playthrough", stated="library.playthrough.started", …)` and keep every existing constant name (`PLAYTHROUGH_STARTED = PLAYTHROUGH_START_EVENTS.stated`, …) and constructor function. Point `games/bulk_playthrough_acts.py`'s hand-built families at `PLAYTHROUGH_START.family` / `PLAYTHROUGH_COMPLETION.family`.
- [ ] **Step 4:** `make test ARGS="tests/test_endpoint_primitive.py tests/test_endpoint_fingerprints.py tests/test_bulk_playthrough_acts.py -x"` → PASS. `make check-fast`. Commit `refactor(events): build playthrough endpoint specs from one factory`.

### Task 2: Field factories, constraints, `games.E014`

**Files:**
- Create: `games/endpoint_fields.py`
- Modify: `games/models.py` (Playthrough endpoint fields), `games/checks.py`, `tests/test_endpoint_primitive.py`

**Interfaces — produces:**
- `endpoint_when() -> TemporalValueField`, `endpoint_bound(when: str, side: Literal["lower","upper"]) -> GeneratedField`, `endpoint_marker() -> DateTimeField`, `endpoint_note() -> TextField`, `endpoint_way(ways: Sequence[EndWay]) -> CharField` (`max_length=16, blank=True, default="", choices=[(way.value, END_WAY_LABELS[way]) …]`).
- `endpoint_constraints(endpoint: Endpoint) -> tuple[CheckConstraint, ...]` — `()` without ways; else `<model>_<endpoint.name>_way_known` (`way__in=[…] | way=""`) and `<model>_<endpoint.name>_way_with_marker` (`(way="") == (marker IS NULL)` spelled as two `Q` branches).
- System check `games.E014` in `games/checks.py`.

- [ ] **Step 1: Failing tests:** each factory reproduces Playthrough's current field `deconstruct()` exactly (compare against `Playthrough._meta.get_field("started").deconstruct()` etc. captured before the swap); `endpoint_constraints(PLAYTHROUGH_START) == ()`; E014 fires on a fake descriptor naming a missing column, a bound column that is a plain field, and a way endpoint whose model lacks its constraints (use `isolate_apps` or call the check function on descriptors directly).
- [ ] **Step 2:** Implement; replace Playthrough's hand-written endpoint fields with the factories (keep `help_text`/comments as today's deconstruct demands).
- [ ] **Step 3:** `make makemigrations ARGS="--check --dry-run"` → "No changes detected". `make check-fast`. Commit `refactor(models): declare playthrough endpoints through field factories`.

### Task 3: Projector helpers

**Files:**
- Modify: `games/events/projection.py` (Projector), `games/projectors/playthrough.py`

**Interfaces — produces:** on `Projector`:
- `project_stated(self, endpoint: Endpoint, event: RecordedEvent) -> None` — `amend(model, event, **{when: event.effective_time, marker: event.recorded_at, note: payload["note"], way?: payload["way"]})`
- `project_corrected(self, endpoint, event)` — same without the marker.
- `project_voided(self, endpoint, event)` — `when=None, marker=None, note="", way?=""`.

- [ ] **Step 1:** Swap `_started`, `_completed`, `_start_corrected`, `_completion_corrected`, `_start_voided`, `_completion_voided` for one-line calls. Existing `tests/test_playthrough_*` projector tests and `tests/test_projection_replay_gate.py` are the failing-then-passing proof (they must stay green; no new test needed beyond a helper unit test asserting the voided dict for a way endpoint once Task 6 exists).
- [ ] **Step 2:** `make test ARGS="tests/test_projection_replay_gate.py tests/test_event_replay.py -k playthrough"` → PASS; `make check-fast`. Commit.

### Task 4: Reads and command skeletons

**Files:**
- Create: `games/reads/endpoints.py`, `games/commands/endpoint.py`
- Modify: `games/reads/playthrough_endpoints.py`, `games/commands/playthrough.py`, `tests/test_endpoint_primitive.py`

**Interfaces — produces:**
- `StatedEndpoint(recorded_at, when, note, way: EndWay | None = None)` moved to `games/reads/endpoints.py`, re-exported from `playthrough_endpoints`.
- `stated(row: Model, endpoint: Endpoint) -> StatedEndpoint | None`.
- `ActStatement(when, note="")` moved to `games/commands/endpoint.py`, re-exported from `games.commands.playthrough`; `WayActStatement(when: TemporalValue | None, way: EndWay, note: str = "")`.
- `class EndpointSentences(NamedTuple)`: `already_stated: Refusal-text pair`, `nothing_to_correct`, `unchanged_state`, `unchanged_correct`, `unchanged_void` — log message and person sentence for each, as the six commands spell them today.
- `state_endpoint(row, endpoint, *, when, note, way=None, sentences, before_event: Callable[[], None] = _nothing) -> Sequence[NewEvent] | Unchanged`
- `correct_endpoint(...)` same signature; `void_endpoint(row, endpoint, *, sentences, before_event) -> Sequence[NewEvent] | Unchanged`.
- Event built with `endpoint.events.<x>.new(aggregate_id=row.pk, effective_time=when, payload={"note": note} | ({"way": way} if endpoint.way else {}))`.

- [ ] **Step 1: Failing tests** for the skeletons over a playthrough row: identical restatement → `Unchanged`; different → `CommandRejected` with the stated sentence; `before_event` runs after the stated/Unchanged decision and before the event (a hook that raises proves order); correct refuses unstated before comparing; void answers `Unchanged` before `before_event`.
- [ ] **Step 2:** Implement; rewrite the six commands' `build` bodies to resolve as today and call the skeleton, passing today's sentences verbatim and `endpoints_certainly_reversed` / `_refuse_under_a_removed_game` + `_refuse_a_removed_run` as `before_event`. `CreatePlaythrough` builds its events through `PLAYTHROUGH_START.events.stated.new(...)` via the existing constructors — no skeleton.
- [ ] **Step 3:** `make test ARGS="tests/test_playthrough_endpoints_read.py tests/test_playthrough_endpoint_writes.py tests/test_endpoint_fingerprints.py tests/test_endpoint_primitive.py -x"` then `make test ARGS="-k playthrough"`. Commit.

### Task 5: Move decision, filter fields, member-1 parity

**Files:**
- Create: `games/writes/endpoint.py`
- Modify: `games/writes/playthrough.py`, `games/filters.py`, `tests/test_endpoint_primitive.py`

**Interfaces — produces:**
- `class EndpointMove(Enum)`: `NOTHING`, `ACT`, `CORRECT`, `VOID`; `endpoint_move(stated: StatedEndpoint | None, wanted: object | None) -> EndpointMove` — no value comparison.
- `class EndpointFilterFields(NamedTuple): interval: FilterField; stated: FilterField; way: FilterField | None`; `endpoint_filter_fields(endpoint, *, interval_label: str | None = None, stated_label: str, way_label: str | None = None) -> EndpointFilterFields`.

- [ ] **Step 1: Failing tests:** the four-way table of `endpoint_move` (both stated and wanted → `CORRECT` even when equal); `PlaythroughFilter.fields` keys, order, labels and `metadata_lookup` equal a literal snapshot taken from main.
- [ ] **Step 2:** Implement; `_state_endpoint` keeps its early return and note carry and picks `first`/`correction` from `endpoint_move`; `PlaythroughFilter.fields` places `endpoint_filter_fields(...)` entries in today's order with `stated_label="Has a start"` / today's completion label.
- [ ] **Step 3:** `make check-fast`; `make makemigrations ARGS="--check --dry-run"`; `make render-pages ARGS="--user admin --out …/pages-member1"`; `diff -r pages-before pages-member1` → empty. Commit.
- [ ] **Step 4:** `gh stack add claude/issue-1275-device-access-end`.

---

## Member 2: device access end

### Task 6: Device events, columns, projector, commands

**Files:**
- Modify: `games/events/device.py`, `games/endpoints.py`, `games/models.py` (Device), `games/projectors/device.py`, `games/commands/device.py`, `games/events/dispatch.py` (`CommandName`), `tests/test_device_command.py`, `tests/test_device_projection.py`, `tests/test_projection_replay_gate.py`
- Create: migration via `make makemigrations ARGS="games --name device_access_end"`

**Interfaces — produces:**
- `DeviceWayValue = Literal["sold","lost","given_away","broken","stolen"]` (bare Literal, per the pydantic discriminator memory); `DeviceAccessEndPayload(TypedDict): way: DeviceWayValue; note: str`; `DeviceAccessEndVoidedPayload(TypedDict)` empty.
- `DEVICE_ACCESS_END_EVENTS = endpoint_events("device", stated="library.device.access_ended", corrected="library.device.access_end_corrected", voided="library.device.access_end_voided", …)`; constructors `device_access_ended(device_id, *, when, way, note)`, `device_access_end_corrected(...)`, `device_access_end_voided(device_id)`.
- `DEVICE_ACCESS_END = Endpoint(name="access_end", model_label="games.Device", when="access_ended", lower="access_ended_lower", upper="access_ended_upper", marker="access_end_recorded_at", note="access_end_note", way="access_end_way", ways=(SOLD, LOST, GIVEN_AWAY, BROKEN, STOLEN), events=DEVICE_ACCESS_END_EVENTS)`.
- `CommandName.DEVICE_END_ACCESS = "library.device.end_access"`, `DEVICE_CORRECT_ACCESS_END = "library.device.correct_access_end"`, `DEVICE_VOID_ACCESS_END = "library.device.void_access_end"`.
- `check_way(way: str) -> EndWay` (sentence "Choose one of the listed ways a device leaves."); `EndDeviceAccess(device_id: UUID, statement: WayActStatement)`, `CorrectDeviceAccessEnd(device_id, statement)`, `VoidDeviceAccessEnd(device_id)`; `CreateDevice.access_end: WayActStatement | None = None`.
- Removed-device sentence: "That device was removed. Put it back before changing what it records."

- [ ] **Step 1: Failing tests** (`tests/test_device_command.py`): end on held → one event with `effective_time` and payload; end twice identical → `Unchanged`, different → refused (sentence); correct unstated → refused; correct way alone → one event; void unstated → `Unchanged`; void on removed device with an end → refused after the Unchanged check; end/correct on removed → refused with the aggregate's sentence; way `"refunded"` → refused by `check_way`; `CreateDevice(access_end=…)` → two events, one build. Projection tests: stated/corrected/voided columns, marker kept across correction; replay gate: add a device stream create-with-end → correct → void → remove to `tests/test_projection_replay_gate.py` (its unappended-type guard fails until you do).
- [ ] **Step 2:** Implement; Device fields through the factories; `Meta.constraints = (library_identity_constraint(), *endpoint_constraints(DEVICE_ACCESS_END))`; projector maps the three specs to `project_stated/corrected/voided`; make the migration; add a test that dispatching every command path never trips either CHECK (a direct `Device.objects.filter(...).update(access_end_way="sold")` on a held row does, proving the CHECK exists).
- [ ] **Step 3:** `make test ARGS="tests/test_device_command.py tests/test_device_projection.py tests/test_projection_replay_gate.py tests/test_endpoint_primitive.py -x"`; `make check-fast`. Commit `feat(device): state that access to a device ended`.

### Task 7: Write path and form

**Files:**
- Modify: `games/writes/device.py`, `games/forms.py` (`DeviceForm`), `games/views/device.py` (add/edit), `tests/test_device_views.py`, `tests/test_device_command.py` (API case lives in the API test file that covers `POST /api/devices/` — find with `grep -rn "api/devices/" tests`)

**Interfaces — produces:**
- `restate_device(actor, device, *, name, device_type, access_end: WayActStatement | None, correlation_id, idempotency_key=None, source_metadata=None) -> None` replaces `describe_device` (update its callers); dispatches `DescribeDevice` then the `endpoint_move` command, each under `answered(SUBJECT)`.
- `create_device(..., access_end: WayActStatement | None = None)`.
- `DeviceForm`: `access = ChoiceField(choices=[("", "Held"), *way choices], required=False)`, `access_day = <temporal form field used by PlaythroughForm/historical form>(required=False)`, `access_note = CharField(required=False, widget=Textarea)`; `clean()` → `self.cleaned_data["access_end"]: WayActStatement | None`; initial from `stated(device, DEVICE_ACCESS_END)`; help text on `access`: "Held takes back a recorded end. Getting a device back cannot be recorded yet."

- [ ] **Step 1: Failing tests:** edit Held→Sold (month day, note) → row stated; Sold→Lost → corrected, marker unchanged; Sold→Held → voided; name + way changed in one post → two commands, one correlation id (read events); add with Sold → one creation, two events; `POST /api/devices/` with name/type only → 201, held.
- [ ] **Step 2:** Implement; render through `AddForm`/`FormFields`; the temporal widget's media arrives through `FormFields`.
- [ ] **Step 3:** `make test ARGS="tests/test_device_views.py -x"` + the API test; `make check-fast`. Commit.

### Task 8: Picker hint and order

**Files:**
- Modify: `common/components/search_select.py` (`SearchSelectOption`, `_option_row`), `games/api.py` (`PickerOption`, `search_devices`), `games/forms.py` (`device_options`, `_held_device_options`, session form resolver), `ts/elements/search-select.ts` (interface, `buildRow`, `optionFromRow`), `ts/elements/search-select.test.ts`, `tests/test_api*.py` (device search), `tests/test_search_select*.py`

**Interfaces — produces:** `SearchSelectOption.hint: NotRequired[str]`; row attribute `data-hint`; TS `SearchSelectOption.hint?: string`; `device_option(device) -> SearchSelectOption` in `games/forms.py`, the one producer every device resolver and `search_devices` call (hint = way label when ended).

- [ ] **Step 1: Failing tests:** vitest — `buildRow` renders trailing muted hint, `optionFromRow` round-trips `hint` and leaves it out of `data`, matching ignores hint; pytest — `search_devices` with empty `q` orders held before ended, each by today's key, and sets `hint="Sold"`; with `q` both groups match by name; `_option_row` emits `data-hint`.
- [ ] **Step 2:** Implement (empty-`q` ordering: `F("access_end_recorded_at").asc(nulls_first=True)` ahead of today's terms; with `q`, held first then name).
- [ ] **Step 3:** `make ts`; `make test-ts TS_ARGS="ts/elements/search-select.test.ts"`; `make test ARGS="-k 'search_devices or search_select' -x"`. Commit.

### Task 9: Default device

**Files:**
- Modify: `games/models.py` (`UserLibraryPreferences.default_device`), `games/forms.py` (`LibraryPreferencesForm`), `games/views/library.py`, `games/api.py` (`update_library_default_device`), tests beside each (`grep -rn "default_device" tests` to find them)

**Interfaces:** `default_device` filters `access_end_recorded_at__isnull=True`; `LibraryPreferencesForm(devices=…, default_device=…, stored_default: Device | None)` — queryset = held devices `|` the stored one; the stored ended one gets help text "{Way}, so new sessions name no device. Choose another."; PATCH raises `RowRefused("That device is {way}. Choose a device the library still holds.")` for an ended device.

- [ ] **Step 1: Failing tests:** property answers `None` for an ended default and the id survives; void restores it; settings page renders the ended device selected with help text, offers no other ended device, and a save posting it back keeps the id; the count card still counts ended devices; PATCH with an ended device → 422 and the sentence; session form seeds no device.
- [ ] **Step 2:** Implement. **Step 3:** focused tests, `make check-fast`, commit.

### Task 10: Devices list

**Files:**
- Modify: `games/views/device.py` (`DEVICE_COLUMNS`, cells), `games/filters.py` (`DeviceFilter`), `common/components/quick_filter.py` (`QUICK_FACETS["devices"]`), `games/sorting.py` (`DEVICE_SORTS`), `tests/test_device_views.py`, `tests/test_filters.py` (device cases), `tests/test_sorting.py`

**Interfaces:** `Column("Access", "access", key="access", priority=2)`; cell text from `access_cell(device, presentation) -> str` ("Held" / "Sold · May 2021" / "Lost" — way label, then the temporal value formatted at its precision through the same formatter the playthrough list uses for endpoints); `DeviceFilter` attributes `access_ended: DateCriterion | None`, `is_access_ended: BoolCriterion | None`, `access_end_way: ChoiceCriterion | None`; facets `QuickFacet("is_access_ended", "Access ended")`, `QuickFacet("access_end_way", "Way")`; sort `"access_ended": SortSpec("access_ended_lower")` (nulls last both ways, as `SortSpec` does).

- [ ] **Step 1: Failing tests:** column text for the three shapes; each facet narrows and round-trips through `is_quick_editable`; `access_ended` interval filter; sort puts held last both directions; builder page for devices renders the new fields.
- [ ] **Step 2:** Implement. **Step 3:** focused tests, `make check-fast`, commit.

### Task 11: Sample anonymizer

**Files:** Modify `games/management/commands/anonymize_sample.py`, `tests/test_anonymize_sample.py`

- [ ] **Step 1: Failing test:** a device with an `access_ended` event at a known day anonymizes to that day shifted by the device's offset; creation stays at the fixed epoch; a later `removed` event's `recorded_at` is not before the end's; output byte-deterministic per seed.
- [ ] **Step 2:** `device_offsets` seeded per device pk (same RNG discipline as `game_offsets`, before key reassignment), used in place of the zero branch for device aggregates whose events carry `effective_time`.
- [ ] **Step 3:** `make test ARGS="tests/test_anonymize_sample.py -x"`. Commit.

### Task 12: End-to-end, docs, issues, gate

**Files:** Create `e2e/test_device_access_end_e2e.py`; modify `CLAUDE.md` (Device bullet: the endpoint and its three commands; Key patterns: one line naming `games/endpoints.py`), `docs/event-retention.md` if the naming section needs the new example.

- [ ] e2e: open Edit on a device, choose Sold, type a month in the temporal field, save; the list's Access column reads "Sold · <month>"; the session form's device picker shows the device with hint "Sold" after held ones; edit back to Held; the column reads "Held". Wait on server-rendered content before any ORM read.
- [ ] `make render-pages` → `pages-member2`; `diff -r pages-member1 pages-member2`; every difference is the Devices list, device forms, device builder page, or settings — attribute each.
- [ ] File follow-up issues (bare `#NNN` in bullets): device access restored; bulk tray act for ending access; sale price on a sold end; device acquired endpoint. Post comments on #721, #727, #1157, #601 as the spec's "Comments to post" states, with the new issue numbers.
- [ ] Full gate: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check > …/check.log 2>&1; echo $?` → 0 (read the exit code, not a grep).
