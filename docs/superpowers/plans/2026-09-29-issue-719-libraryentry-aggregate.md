# LibraryEntry aggregate (M1) implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the LibraryEntry aggregate — the opening endpoint variant, the
table, eight events, five commands, writes, reads, four API routes, the
generalised referrer registry, the catalog library path — as one PR that
passes the replay gate and `make check`.

**Architecture:** One more `CURRENT_STATE` projection beside Device, shaped
on the Device aggregate (#1274/#1275). The acquired day is a new opening
endpoint variant of the #1275 primitive. A Release is resolved through a
new `visible_row` over one `LIBRARY_PATHS` map that the ownership audit
reads as well.

**Tech Stack:** Django 6 / PostgreSQL 18, the event store in `games/events`,
pydantic strict payloads, Django Ninja, pytest with `transaction=True`.

**Spec:** `docs/superpowers/specs/2026-09-29-issue-719-libraryentry-aggregate-design.md`
(read it whole first; the wave design and the charter it cites are binding).

## Global constraints

- Run everything through `make`; iterate with `make test-fast ARGS=…`, gate
  once with full `make check` at the end (includes `e2e/`). Wrap in
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"` when another
  worktree may be testing.
- `make format` and `make lint-fix` before every commit (lint-fix sorts
  imports; format does not).
- Vocabulary: `make vale` refuses the words `docs/vocabulary.md` lists, in
  prose and comments alike. Comments: intent only, no issue numbers, terse.
- Identifiers are complete words. Compound and role types get names
  (`type EntryId = uuid.UUID`).
- Every `CommandRejected` raise states `sentence=`; a row the library does
  not hold is `RowNotHeld` (no sentence); a row it holds but cannot read is
  `RowUnreadable`. Resolve through `games/commands/scope.py` only
  (`test_command_scope_guard`).
- Projectors write through `self.project`/`self.amend` only
  (`test_projector_scope_guard`).
- Never write `GeneratedField`s. Never `instance.delete()`.
- Tests that dispatch need `@pytest.mark.django_db(transaction=True)`; a
  test that must not have the autouse tracking seed uses
  `pytest.mark.untracked_games` (see the gate's `pytestmark`).
- Migration number: `0020` (verify after rebase: `ls games/migrations`).

---

### Task 0: Rebase

- [ ] `git fetch origin && git rebase origin/main`; confirm
  `games/migrations` ends at `0019_device_access_end.py`.

### Task 1: The opening endpoint variant

**Files:**
- Modify: `games/endpoint_fields.py`, `games/events/endpoint.py`,
  `games/endpoints.py`, `games/events/projection.py` (after
  `project_voided`), `games/commands/endpoint.py`, `games/checks.py`
  (`endpoint_errors`)
- Test: `tests/test_endpoint_primitive.py`

**Interfaces (produces):**
```text
# games/endpoint_fields.py
@dataclass(frozen=True, slots=True, kw_only=True)
class OpeningEndpointColumns(EndpointColumns):
    """Stated by the creation; corrected; never voided."""
    # __post_init__: raise TypeError if self.way is not None
    # unstated_columns(): raise TypeError("An opening endpoint is never unstated.")
def opening_marker() -> models.DateTimeField  # editable=False, null=False

# games/events/endpoint.py
class OpeningEndpointEvents[PayloadT](NamedTuple):
    corrected: EventSpec[PayloadT]
    @property
    def family(self) -> tuple[EventType]: ...
def opening_endpoint_events[PayloadT](aggregate_type, *, corrected: EventType, payload: type[PayloadT]) -> OpeningEndpointEvents[PayloadT]

# games/endpoints.py
@dataclass(frozen=True, slots=True, kw_only=True)
class OpeningEndpoint(OpeningEndpointColumns):
    events: OpeningEndpointEvents[Any]
    @classmethod
    def over(cls, columns: OpeningEndpointColumns, events) -> OpeningEndpoint
    @property
    def model(self) -> type[models.Model]
ENDPOINTS: tuple[Endpoint | OpeningEndpoint, ...]

# games/events/projection.py  (Projector)
def opening_columns(self, endpoint: OpeningEndpointColumns, event: RecordedEvent, *, note: str) -> dict[str, Any]
#   {when: event.effective_time, marker: event.recorded_at, note_column: note}

# games/commands/endpoint.py
def correct_opening_endpoint(row, endpoint: OpeningEndpoint, statement: ActStatement, *, same_correction: str, before_event: BeforeEvent = _nothing) -> Sequence[NewEvent] | Unchanged
#   _payload/_states_it annotations widen to EndpointColumns
```

**Gotchas:**
- `endpoint_errors` (games/checks.py) adds: for an `OpeningEndpointColumns`,
  the marker field's `null` must be `False` → problem
  `"its marker admits null"`. `declared` already holds every field.
- `tests/test_endpoint_primitive.py` parametrises over `ENDPOINTS`; a
  one-member `NamedTuple` iterates fine. The `_start(**changes)` helper
  builds `EndpointColumns` — add a `_opening(**changes)` twin.
- `project_corrected` needs no change: `_stated_values` reads `way` (None).

**Tests to add** (`tests/test_endpoint_primitive.py`):
- `test_an_opening_endpoint_refuses_a_way`
- `test_an_opening_endpoint_states_no_unstated_columns`
- `test_e014_refuses_a_nullable_opening_marker` (patch `ENDPOINTS` as the
  existing `broken` test does, with a model whose marker is `endpoint_marker()`)
- `test_opening_columns_reads_the_creation` (a `RecordedEvent` with
  `effective_time` and `recorded_at`; assert the three keys)
- `test_correct_opening_endpoint_answers_unchanged_for_the_same_statement`
  and `_emits_the_correction` (use a `Playthrough`-shaped fake or wait for
  Task 4's model; simplest: test through `CorrectEntryAcquisition` in
  Task 6 and keep only the two column tests here)

- [ ] Write failing tests, run `make test-fast ARGS="tests/test_endpoint_primitive.py -x"`, implement, pass, `make typecheck`, commit
  `feat: opening endpoint variant of the stated endpoint`.

### Task 2: `LIBRARY_PATHS`, `visible_row`, `ProjectionReference.library_path`

**Files:**
- Modify: `games/projections.py`, `games/commands/scope.py`,
  `games/commands/playergame.py` (`TrackGame._visible_game`)
- Test: `tests/test_projection_references.py`, `tests/test_command_scope.py`,
  `tests/test_playergame_command.py` (TrackGame's sentence still answered)

**Interfaces (produces):**
```text
# games/projections.py
type LibraryPath = str  # e.g. "edition__game__library"
LIBRARY_PATHS: Mapping[type[models.Model], LibraryPath] = {Release: "edition__game__library", Edition: "game__library"}
def library_path_of(model: type[models.Model]) -> LibraryPath | None
#   concrete `library` field first → "library"; else LIBRARY_PATHS.get(model)
def _is_library_scoped(model) -> bool  # = library_path_of(model) is not None
class ProjectionReference(NamedTuple):
    model; field; library_path: LibraryPath = "library"
    # on(): reads library_path_of(field.related_model); refuses None as today
# cross_library_violations: f"{name}__{reference.library_path}_id" in the
#   __in clause, the isnull clause and the exclude(F("library_id"))

# games/commands/scope.py
def visible_row[RowT: Model](context, reads: QuerySet[RowT], refusal: Refusal, **lookup) -> RowT
#   path = library_path_of(reads.model); filter(Q(**{f"{path}__isnull": True}) | Q(**{path: context.library}), **lookup).get()
#   ObjectDoesNotExist → refusal.raised()
```

**Gotchas:**
- `library_path_of` must answer from the concrete field before the map, or
  the `isolate_apps` registries in `tests/test_projection_references.py`
  and `tests/test_projection_targets.py` break.
- `tests/test_projection_references.py:295` constructs
  `ProjectionReference(...)` positionally: the default keeps it valid.
- `TrackGame._visible_game` becomes
  `visible_row(context, Game.objects.alive(), Refusal(message=…, sentence="That game is not available to track.", raises=CommandRejected), pk=self.game_id)`.
  Keep the existing sentence text exactly.
- `scope.py` is `EXEMPT` in the scope guard; the `.get()` is allowed there.

**Tests to add:**
- `test_projection_references.py`: `test_a_catalog_model_reaches_its_library_through_a_path`
  (`library_path_of(Release) == "edition__game__library"`),
  `test_the_walk_finds_no_reference_yet_through_a_path` (list unchanged until Task 4).
- `test_command_scope.py`: `test_visible_row_answers_a_shared_row`,
  `_answers_the_librarys_own_private_row`,
  `_refuses_another_librarys_private_row_with_the_stated_class`,
  `_reads_removed_rows_when_the_caller_passes_all` (over `Release`,
  built with the `stated_graph` fixture on a shared `Game(library=None)`
  and a private one).
- `cross_library_violations` over a path: covered in Task 4 (needs the model).

- [ ] Tests → fail → implement → pass → commit
  `feat: resolve a catalog row through its library path`.

### Task 3: Referrer registry over any target

**Files:**
- Rename: `games/reads/playthrough_referrers.py` → `games/reads/referrers.py`
  (`git mv`); update imports in `games/reads/playthrough_runs.py`,
  `games/bulk_move.py`, `games/commands/playthrough.py`,
  `tests/test_playthrough_referrers.py` (rename to `tests/test_referrers.py`),
  `tests/test_historical_playtime_command.py`,
  `tests/test_playthrough_command.py` (module import and the
  `monkeypatch.setattr(referrers, "BLOCKING_REFERRERS", …)` target)
- Test: `tests/test_referrers.py`

**Interfaces (produces):**
```text
class BlockingReferrer(NamedTuple):
    model: type[ProjectionModel]; field_name: FieldName; target: type[ProjectionModel]; sentence: str
    @classmethod
    def on(cls, model, field_name, *, target: type[ProjectionModel], sentence: str) -> BlockingReferrer
    #   refuses field.related_model is not target
def referrers_of(target: type[ProjectionModel]) -> tuple[BlockingReferrer, ...]
#   tuple(r for r in BLOCKING_REFERRERS if r.target is target) — read the module global at call time
def rows_naming(referrer, row: ProjectionModel) -> QuerySet  # refuses type(row) is not referrer.target
def blocking_referrer(row: ProjectionModel) -> BlockingReferrer | None   # over referrers_of(type(row))
def foreign_referrer(row: ProjectionModel) -> ForeignReferrer | None
```

**Gotchas:**
- The 11 `BlockingReferrer.on(` calls in `tests/test_playthrough_command.py`
  gain `target=Playthrough`.
- `games/bulk_move.py:141` loops `referrers_of(Playthrough)`.
- `_live_rows_naming` filters `library=row.library`; unchanged in shape.

**Tests:** existing referrer tests move; add
`test_on_refuses_a_field_naming_another_model_than_the_target`,
`test_referrers_of_reads_the_patched_tuple` (monkeypatch, then call),
`test_rows_naming_refuses_a_row_of_another_model`.

- [ ] Rename → tests → implement → `make test-fast ARGS="tests/test_referrers.py tests/test_playthrough_command.py tests/test_bulk_edit_moves.py -x"` → commit
  `refactor: referrer registry names its target model`.

### Task 4: `LibraryEntry` model, migration, registrations

**Files:**
- Modify: `games/models.py` (after `Device`), `games/signals.py`
  (`@receiver(pre_delete, sender=LibraryEntry)`), `games/projections.py`
  (`AUDITED_PROJECTION_REFERENCES`), `games/events/references.py`
  (kind `libraryentry`), `games/management/commands/audit_library_ownership.py`
  (a `("entries", …)` line under Direct owners)
- Create: `games/migrations/0020_libraryentry.py` via
  `make makemigrations ARGS="games --name libraryentry"`
- Test: `tests/test_projection_references.py`, `tests/test_projection_rebuild.py`,
  `tests/test_uuid_identity_audit.py`, `tests/test_retention.py`,
  `tests/test_event_references.py`, swap-list tuples in
  `tests/test_playergame_projection.py`, `tests/test_playthrough_projection.py`,
  `tests/test_historical_playtime_projection.py`, `tests/test_event_benchmark.py`;
  new `tests/test_libraryentry_model.py`

**Interfaces (produces):**
```text
class EntryAccess(models.TextChoices): OWNED="owned"; BORROWED; RENTED; SUBSCRIPTION; TRIAL; DEMO; PIRATED
class EntryFormat(models.TextChoices): PHYSICAL="physical"; DIGITAL="digital"; UNKNOWN="unknown"
ENTRY_ACQUISITION_COLUMNS = OpeningEndpointColumns(name="acquisition", model_label="games.LibraryEntry", when="acquired", lower="acquired_lower", upper="acquired_upper", marker="acquisition_recorded_at", note="acquisition_note")
class LibraryEntryQuerySet(RemovableMixin, models.QuerySet["LibraryEntry"]): ancestor_marks = ("player_game",)
class LibraryEntry(ProjectionModel, ReferencedRow):
    objects = LibraryEntryQuerySet.as_manager()
    id = UUIDv7Field(primary_key=True, editable=False, default=NOT_PROVIDED, db_default=NOT_PROVIDED)
    player_game = FK(PlayerGame, RESTRICT, related_name="entries")
    release = FK(Release, RESTRICT, related_name="+")
    access = CharField(max_length=16, choices=EntryAccess)
    format = CharField(max_length=16, choices=EntryFormat)
    note = TextField(blank=True, default="")
    acquired = endpoint_when(); acquired_lower/upper = endpoint_bound(...)
    acquisition_recorded_at = opening_marker(); acquisition_note = endpoint_note()
    created_at = DateTimeField(editable=False)
    removed_at = DateTimeField(null=True, default=None, editable=False)
    class Meta: constraints = (library_identity_constraint(), CheckConstraint(access__in words, name="games_libraryentry_access_known"), CheckConstraint(format__in words, name="games_libraryentry_format_known")); indexes = (Index(fields=("library","release"), condition=Q(removed_at__isnull=True), name="live_entry_per_release_idx"),)
```
- `games/events/references.py`: `_capture_entry(entry)` → `Reference(kind="libraryentry", id=str(entry.pk), label=entry.player_game.game.name, detail=f"{entry.access}, {entry.format}")`; registered `PROJECTED`, `created_by="library.libraryentry.created"`.
- `AUDITED_PROJECTION_REFERENCES` += `ProjectionReference.on(LibraryEntry, "player_game")`, `ProjectionReference.on(LibraryEntry, "release")` (keep the tuple sorted as the walk sorts: by table, then column).

**Gotchas:**
- `games.E014` runs on `manage.py check`: the endpoint is registered in
  `ENDPOINTS` in Task 5 (needs the events); until then only the columns
  exist, which is fine.
- Exact lists to update: `test_projection_references.py` walk list (+2),
  `test_projection_rebuild.py` `projection_models()` tuple (+`LibraryEntry`
  after `LibraryCalendar`), `test_uuid_identity_audit.py`
  `EXPECTED_RELATION_COLUMNS` (+3 columns) and `EXPECTED_IDENTITY_TABLES`
  (+`games_libraryentry`), the swap tuples (+`("games_libraryentry", 0, 0, 0)`
  after `games_librarycalendar`), `test_event_references.py` `by_kind`
  (+`"libraryentry": entry`, entry built by the projector in Task 5 — add
  the key in Task 5), `test_retention.py` registry tests (pass once
  `ReferencedRow` + receiver are in).
- `makemigrations` prompts: the Make target passes `--noinput`.

**Tests to add** (`tests/test_libraryentry_model.py`): the two CHECKs refuse
a foreign word (`IntegrityError` on a raw `_base_manager.create`), the
partial index and both constraints are in `Meta`, `alive()` hides a row
under a removed PlayerGame, `cross_library_violations` reports an entry
naming a foreign private Release (build two libraries, a private graph in
each via `stated_graph`, an entry row via `_base_manager.create` naming the
other's Release; assert the sentence names `LibraryEntry.release`).

- [ ] Model → migration → registrations → update exact lists → `make check-fast` → commit
  `feat: the LibraryEntry projection table`.

### Task 5: Events and the `Entries` projector

**Files:**
- Create: `games/events/libraryentry.py`, `games/projectors/libraryentry.py`
- Modify: `games/projectors/__init__.py` (import), `games/endpoints.py`
  (`ENTRY_ACQUISITION = OpeningEndpoint.over(ENTRY_ACQUISITION_COLUMNS, ENTRY_ACQUISITION_EVENTS)`, in `ENDPOINTS`),
  `tests/test_projection_replay_gate.py` `registered_event_types` (+`Entries.handles`)
- Test: `tests/test_libraryentry_projection.py`, `tests/test_libraryentry_events.py`

**Interfaces (produces):**
```text
# games/events/libraryentry.py
type EntryAccessValue = Literal["owned","borrowed","rented","subscription","trial","demo","pirated"]
type EntryFormatValue = Literal["physical","digital","unknown"]
class LibraryEntryCreatedPayload(TypedDict): player_game: ReferenceId; release: Reference; access: EntryAccessValue; format: EntryFormatValue; note: NoteText; acquisition_note: NoteText
LIBRARYENTRY_CREATED / _ACCESS_CHANGED / _FORMAT_CHANGED / _NOTE_CHANGED / _RELEASE_CHANGED / _REMOVED / _RESTORED: EventSpec
ENTRY_ACQUISITION_EVENTS = opening_endpoint_events("libraryentry", corrected="library.libraryentry.acquisition_corrected", payload=EndpointPayload)
LIBRARYENTRY_ACQUISITION_CORRECTED = ENTRY_ACQUISITION_EVENTS.corrected
def libraryentry_created(player_game_id, release: Release, *, access, format, note, acquired: TemporalValue | None, acquisition_note, entry_id: uuid.UUID | None = None) -> NewEvent
def libraryentry_access_changed(entry_id, access) / _format_changed / _note_changed / _release_changed(entry_id, release: Release) / _acquisition_corrected(entry_id, *, when, note) / _removed / _restored

# games/projectors/libraryentry.py
class Entries(Projector): family_name = CURRENT_STATE; handles = {...eight...}
#   _created: self.project(LibraryEntry, event, player_game_id=UUID(payload["player_game"]), release_id=UUID(payload["release"]["id"]), access=…, format=…, note=…, created_at=event.recorded_at, **self.opening_columns(ENTRY_ACQUISITION_COLUMNS, event, note=payload["acquisition_note"]))
#   _acquisition_corrected: self.project_corrected(ENTRY_ACQUISITION_COLUMNS, event)
```
Event names: `library.libraryentry.{created,access_changed,format_changed,note_changed,release_changed,acquisition_corrected,removed,restored}`.

**Gotchas:**
- `Literal` words pinned to `EntryAccess`/`EntryFormat` values by a test
  (see `test_device_command.py::test_the_payload_spells_every_stored_type`).
- Look at `Devices._created` for how `project()` refuses `library`.
- `project()`'s `_required_columns` demands `created_at` and the marker.

**Tests:** `tests/test_libraryentry_projection.py` mirrors
`tests/test_device_projection.py` (every event replays to the same rows; a
rebuild puts back a lost row; a stream naming an entry it never created is
refused — the last via a fake payload with a `libraryentry` Reference).
`tests/test_libraryentry_events.py`: the Literals match the choices; the
created payload refuses an extra key; `by_kind` in
`test_event_references.py` gains the entry.

- [ ] Commit `feat: LibraryEntry events and the Entries projector`.

### Task 6: Commands

**Files:**
- Create: `games/commands/libraryentry.py`
- Modify: `games/events/dispatch.py` (`CommandName`: `LIBRARYENTRY_RECORD = "library.libraryentry.record"`, `_DESCRIBE`, `_CORRECT_ACQUISITION`, `_REMOVE`, `_RESTORE`), `games/commands/scope.py` (`library_entry_row`, `library_entry`, shaped as the device pair)
- Test: `tests/test_libraryentry_command.py`, `tests/test_endpoint_fingerprints.py`, `tests/entries.py` (test helper like `tests/devices.py`: `record_entry(library, release, **words)`, `remove_entry`, `restore_entry`)

**Interfaces (produces):**
```text
UNKNOWN_ACCESS = "Choose one of the listed access words."
UNKNOWN_FORMAT = "Choose one of the listed formats."
RELEASE_REMOVED = "That release was removed from the catalog. Restore it before recording a copy."
RELEASE_OF_ANOTHER_GAME = "That release belongs to another game. Choose a release of this one."
PLAYER_GAME_REMOVED = "That game was removed from your library. Restore it before changing its copies."
ENTRY_REMOVED = "That copy was removed. Put it back before changing what it records."
@dataclass(frozen=True, slots=True) class RecordEntry(Command): release_id: uuid.UUID; access: str; format: str; note: str = ""; acquired: ActStatement = ActStatement(None, "")
class DescribeEntry(Command): entry_id; access: str | None = None; format: str | None = None; note: str | None = None; release_id: uuid.UUID | None = None
class CorrectEntryAcquisition(Command): entry_id; statement: ActStatement
class RemoveEntry(Command): entry_id
class RestoreEntry(Command): entry_id
```
Rules, in order (from the spec's table): `RecordEntry.build` → `check_access`/`check_format` → `visible_row(context, Release.objects.select_related("edition__game").all(), Refusal(message=…), pk=…)` → `Release.objects.alive().filter(pk=…).exists()` else `CommandRejected(RELEASE_REMOVED)` → `PlayerGame.objects.filter(library=context.library, game=game).first()`: removed → refuse; `None` → `events = tracking_events(game)`, `tracked_id = events[0].aggregate_id`; then `libraryentry_created(tracked_id, release, …)`.
`RemoveEntry`: `library_entry_row` → `Unchanged` if removed → refuse under removed PlayerGame → `blocking_referrer(entry)` → `foreign_referrer(entry)` as `RemovePlaythrough` does (`RowUnreadable`).

**Gotchas:**
- Fingerprints: add all five to `tests/test_endpoint_fingerprints.py`
  `COMMANDS` with fixed UUIDs, run once to read the digests, pin them.
- `__post_init__` strips `note`, `acquisition` note; `stated_date` on the day.
- `test_command_answers.py` walks every `games` module: every raise site
  needs a sentence or the test names it.
- `RecordEntry` with a `PlayerGame` that is removed: sentence
  `PLAYER_GAME_REMOVED`; do not track again.

**Tests** (`tests/test_libraryentry_command.py`, `transaction=True`,
helpers shaped as `test_device_command.py`): creation writes one event on a
tracked game and three (`playergame.created`, `playthrough.created`,
`libraryentry.created`) on an untracked one; foreign word → sentence;
removed Release / Edition / Game → `RELEASE_REMOVED`; another library's
private Release → `RowNotHeld`; shared Release → two libraries record
independent rows; two entries on one Release in one library; describe
emits one event per differing fact, `Unchanged` when none, refuses a
Release of another game and a removed one; correction `Unchanged` on the
same statement, emits on a different day, keeps the marker; remove/restore
move the mark, repeat `Unchanged`, refused under removed PlayerGame;
restore refused under a removed Release; `referrers_of(LibraryEntry) == ()`
today, so the removal's registry read is covered by monkeypatching
`games.commands.libraryentry.blocking_referrer` to answer a
`BlockingReferrer` (build one with `on(PlayerSession, "playthrough",
target=Playthrough, sentence="Purchases name this copy.")`) and asserting
`RemoveEntry` is refused with that sentence.

- [ ] Commit `feat: LibraryEntry commands`.

### Task 7: Writes and reads

**Files:**
- Create: `games/writes/libraryentry.py`, `games/reads/entries.py`
- Modify: `games/reads/events.py` (`dispatched_events`)
- Test: `tests/test_libraryentry_writes.py`, `tests/test_entries_read.py`

**Interfaces (produces):**
```text
# games/reads/events.py
def dispatched_events(result: CommandResult) -> LibraryEventQuerySet
#   LibraryEvent.objects.filter(stream_id=result.stream_id, sequence__range=(first, last)).order_by("sequence"); ValueError on sequences None

# games/writes/libraryentry.py
SUBJECT: SubjectNoun = "entry"
class EntryDraft(NamedTuple): release_id; access: str; format: str; note: str; acquired: ActStatement
class RecordedEntry(NamedTuple): entry_id: uuid.UUID; tracked_the_game: bool
def record_entry(actor, draft, *, correlation_id, idempotency_key=None, source_metadata=None) -> RecordedEntry
def restate_entry(actor, entry, *, access=None, format=None, note=None, release_id=None, acquired: ActStatement | None, correlation_id) -> None   # correction first, then description
def remove_entry(actor, entry, *, correlation_id, idempotency_key=None, source_metadata=None) -> CommandResult
def restore_entry(...)

# games/reads/entries.py
def library_entries(library) -> LibraryEntryQuerySet  # library on entry + player_game; marks: removed_at, player_game__removed_at, release__removed_at, release__edition__removed_at, release__edition__game__removed_at
def readable_entries(library)  # .select_related("player_game__game", "release__platform")
def game_entries(library, game)
```
- `SubjectNoun` Literal in `games/writes/answers.py` gains `"entry"`.
- `answered("entry")` around every dispatch.

**Tests:** `record_entry` answers `tracked_the_game=True` on an untracked
game and the entry id (not the PlayerGame's); a repeat under the same
idempotency key answers the same id; `restate_entry` sends the correction
first (a refused correction leaves the description unsent — refuse by
naming a removed entry); `library_entries` hides each of the five marks and
never answers another library's row; `UnscopedRead` on `None`.

- [ ] Commit `feat: LibraryEntry writes and reads`.

### Task 8: API

**Files:**
- Modify: `games/api.py` (`entry_router`, mounted `/entries`), `games/views/returns.py` if any route table guard reads API names (check `tests/test_action_origin_parity.py`; API routes are not in it)
- Test: `tests/test_api.py` (new class/section), `tests/test_library_api_isolation.py` (`test_entry_crud_is_library_scoped`)

**Interfaces:**
```text
class EntryIn(Schema): extra=forbid; release_id: UUIDv7; access: str; format: str; note: str = ""; acquired: StatedTemporal = None; acquisition_note: str = ""
class EntryUpdate(Schema): extra=forbid; access/format/note/release_id/acquired/acquisition_note all optional; model_validator: acquired and acquisition_note both present or both absent, else ValueError("State the acquired day and its note together.")
class EntryOut(Schema): id; game (alias player_game.game.name); game_id; release_id; platform (release.platform.name or ""); access; format; note; acquired: str|None; acquired_lower/upper: date|None; acquisition_recorded_at: datetime; acquisition_note; created_at
GET /entries/ (limit=Query(100, ge=0), offset) → list; POST / (Idempotency-Key via _stated_idempotency_key) → 201; GET /{id}; PATCH /{id}
```
Follow `create_session`/`partial_update_session` for `CommandFailed` →
`_answered_or_http`, `owned_or_404(readable_entries(library), library, pk=…)`
after every write, `messages.success`.

**Tests:** POST records (201, row shape, `tracked_the_game` message),
repeat with the same `Idempotency-Key` answers the same id, 422 on an
unknown key and on `acquired` without `acquisition_note`, 409 with the
sentence on a removed Release, 404 on another library's private Release;
GET list respects `limit=0`; PATCH each act; isolation test: library B
cannot GET/PATCH A's entry, and a shared Release gives each its own row.

- [ ] Commit `feat: /api/entries routes`.

### Task 9: Replay gate and ownership audit

**Files:**
- Modify: `tests/test_projection_replay_gate.py` (`build_stream`,
  `build_neighbour`, `ProjectionSnapshot` → 6-tuple, `rows_of`,
  `row_versions` (`* 6`, add the table), `empty_projections` (entries
  before PlayerGame), the partial-stream count `37` → `45`, the swap list,
  `test_the_stream_leaves_a_removed_row_in_each_table`), a new
  `assert_entries_belong_to_their_games(library)` called after each replay
- Test: `tests/test_libraryentry_model.py` (audit test from Task 4 if not done there)

**Gotchas:**
- Games in the gate are bare; state a default graph per game with
  `state_catalog_graph` (copy the `stated_graph` fixture's `EditionState`/
  `ReleaseState` call, no platform) before recording entries.
- `build_stream` must dispatch: `RecordEntry` ×2 on one Release (one on a
  game not yet tracked — create a fourth `Game` for it), `DescribeEntry`
  changing all four facts (needs a second live Release on that game:
  state two `ReleaseState`s), `CorrectEntryAcquisition`, `RemoveEntry`,
  `RestoreEntry`, and a final `RemoveEntry` left removed.
- `build_neighbour` records one entry.

- [ ] `make test-fast ARGS="tests/test_projection_replay_gate.py -x"` green → commit
  `test: replay gate covers the LibraryEntry stream`.

### Task 10: Docs, gate, PR

- [ ] `CLAUDE.md`: a **LibraryEntry** bullet under Models (shape of the
  Device bullet, ~10 lines: projector, commands, opening endpoint, visible_row,
  referrer registry rename), and the referrer registry sentence in the
  Playthrough bullet points at `games/reads/referrers.py`.
- [ ] `docs/event-retention.md#naming`: one sentence on the opening endpoint
  (`acquired` beside `acquisition_recorded_at`, never null).
- [ ] `make vale`, `make format`, `make lint-fix`.
- [ ] Full gate: `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check > /tmp/check.log 2>&1; echo $?` — read the exit code, not grep.
- [ ] PR body names #719, #720, #722 as delivered together (closes all three); links the spec and this plan; lists the exact-list test edits.

## Follow-up issues to file / comments to leave

1. Docs-only PR after merge: wave doc Decisions gains "An entry's command
   names the Release; the game is derived" and the M1 row's delivery note;
   comment on each open sibling (#721, #1352, #725, #726, #828).
2. Comment on P1 (#725): register `BlockingReferrer.on(Purchase, "entry", target=LibraryEntry, sentence=…)` and state `RemoveEntry`'s purchase sentence; Purchase must be a `ProjectionModel` with `alive()` first.
3. Comment on M2 (#721): add the end columns and their two CHECKs in `0021`; `ENTRY_ACCESS_END = Endpoint.over(...)`; `LIBRARY_ENTRY_WAYS` grows `EndWay` by returned/expired/revoked/refunded.
4. Comment on M3 (#1352): the Edit entry form carries `acquisition_note` beside the acquired day; the API refuses one without the other.
5. Comment on #1347 (device acquired day): reuse `OpeningEndpoint`.
6. Comment on the catalog relink issue (#782 or the one that owns the relink): the relink restates `LibraryEntry.release` beside the PlayerGame's game in one dispatch.

## Self-review

- Spec coverage: opening endpoint (T1), storage (T4), events (T5), commands
  (T6), scope/references (T2, T4), referrer registry (T3), writes/reads/API
  (T7, T8), verification (T4, T9, T10), limits (follow-ups). No gap.
- Names used consistently: `ENTRY_ACQUISITION_COLUMNS` (T4) /
  `ENTRY_ACQUISITION` (T5); `referrers_of` (T3, T6); `visible_row` (T2, T6);
  `dispatched_events` (T7); `library_entries`/`readable_entries` (T7, T8).
