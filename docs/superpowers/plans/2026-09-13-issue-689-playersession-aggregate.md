# PlayerSession aggregate implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `PlayerSession` projection table, its three timing modes and their constraints, the creation event and command, the projector, the queryset, and both projection-reference registrations — a table nothing writes and nothing reads yet.

**Architecture:** Third projection family after `PlayerGame` and `Playthrough`, copying their topology: identity is the creation event's `aggregate_id`, the projector is the only writer, `removed_at` is the projector's mark. Timing is one stated word bound to its columns by database CHECKs, and the payload carries it as a discriminated union so an impossible statement cannot be recorded. Three stored generated columns — `effective_day`, `effective_duration`, `sort_instant` — give every later read one non-null column per question.

**Tech Stack:** Django 6 / Python 3.14 / PostgreSQL 18, pydantic `TypeAdapter` payload validation, pytest + pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-13-issue-689-playersession-aggregate-design.md` — read it first; every "why" lives there and is not repeated here.

## Global Constraints

- Run everything through `make`. Never `direnv exec .`, never bare `uv run` / `pytest`.
- Iterate with `make check-fast`; the gate before "done" is the full `make check`, e2e included.
- Focused runs: `make test ARGS="tests/test_playersession_projection.py -x"`.
- Python 3.14 only. `except A, B:` (PEP 758) is valid here; ruff formats to it.
- Never write to a `GeneratedField`.
- Name variables with complete words. Name compound types (`TypedDict`, `NamedTuple`, PEP 695 alias) rather than repeating structural annotations.
- Every `CommandRejected` carries two sentences: `raise CommandRejected(message, sentence=…)`.
- No command resolves a row with a bare manager `.get()`; use `library_row` from `games/commands/scope.py`. `tests/test_command_scope_guard.py` enforces it.
- Comments explain intent, never history; no issue or PR references in code comments.
- The recorded vocabulary is frozen on merge: event type names, aggregate type, payload keys and their spellings cannot be changed afterwards.

---

### Task 1: The table, its constraints and its registrations

**Files:**
- Modify: `games/models.py` (after `Playthrough`, before `UserLibraryPreferences`)
- Modify: `games/projections.py:109-112` (`AUDITED_PROJECTION_REFERENCES`)
- Create: `games/migrations/00XX_playersession.py` (generated)
- Test: `tests/test_playersession_projection.py`

**Interfaces produced:**
- `PlayerSessionTimingMode(models.TextChoices)` — `TIMED = "timed"`, `DURATION_ONLY = "duration_only"`, `CORRECTED = "corrected"`
- `PlayerSessionQuerySet(RemovableMixin, models.QuerySet["PlayerSession"])` with `ancestor_marks = ("playthrough", "playthrough__player_game")`
- `PlayerSession(ProjectionModel)` with the columns in the spec's §"The columns"
- `Playthrough.sessions` reverse accessor

- [x] **Step 1: Write the failing tests**

`tests/test_playersession_projection.py`, module docstring `"""One row per session a library records."""`. Build rows with `PlayerSession.objects.create(...)` directly in these tests — the projector arrives in Task 4, and these tests are about the schema.

Constraint tests (each wraps the write in `pytest.raises(IntegrityError)` inside `transaction.atomic()`):

| test | row | expected |
|---|---|---|
| `test_timed_refuses_a_stated_day` | timed + `stated_day` | IntegrityError |
| `test_timed_refuses_a_stated_duration` | timed + `stated_duration` | IntegrityError |
| `test_timed_requires_a_day_zone` | timed, `day_zone=None` | IntegrityError |
| `test_corrected_refuses_a_stated_day` | corrected + `stated_day` | IntegrityError |
| `test_corrected_requires_both_instants` | corrected, `ended_at=None` | IntegrityError |
| `test_corrected_requires_an_override` | corrected, `stated_duration=None` | IntegrityError |
| `test_duration_only_refuses_an_instant` | duration_only + `started_at` | IntegrityError |
| `test_duration_only_refuses_a_day_zone` | duration_only + `day_zone` | IntegrityError |
| `test_duration_only_requires_a_duration` | duration_only, `stated_duration=None` | IntegrityError |
| `test_an_endpoint_zone_needs_its_instant` | timed, `ended_at=None`, `ended_at_zone="Asia/Tokyo"` | IntegrityError |
| `test_a_blank_zone_is_refused` | timed, `day_zone=""` | IntegrityError |
| `test_an_end_before_its_start_is_refused` | timed, `ended_at` one hour before `started_at` | IntegrityError |
| `test_a_negative_duration_is_refused` | duration_only, `stated_duration=timedelta(minutes=-5)` | IntegrityError |
| `test_an_unknown_mode_is_refused` | `timing_mode="guessed"` | IntegrityError |
| `test_an_end_equal_to_its_start_is_admitted` | timed, `ended_at == started_at` | row exists |
| `test_a_running_timed_row_is_admitted` | timed, `ended_at=None` | row exists |

Generated-column tests (`refresh_from_db()` after each write):

```python
def test_a_timed_row_takes_its_day_from_its_zone(owned_library, run):
    session = _timed(
        run,
        started_at=datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
        day_zone="Europe/Prague",
    )
    session.refresh_from_db()
    assert session.effective_day == date(2026, 1, 2)
    assert session.sort_instant == datetime(2026, 1, 1, 23, 30, tzinfo=UTC)


def test_restating_the_zone_moves_the_day(owned_library, run):
    session = _timed(
        run,
        started_at=datetime(2026, 1, 1, 23, 30, tzinfo=UTC),
        day_zone="Europe/Prague",
    )
    PlayerSession.objects.filter(pk=session.pk).update(day_zone="UTC")
    session.refresh_from_db()
    assert session.effective_day == date(2026, 1, 1)
```

Also: `test_a_duration_only_row_takes_its_written_day` (`effective_day == stated_day`, `sort_instant` is midnight UTC of it), `test_a_finished_timed_row_measures_elapsed_time`, `test_a_running_timed_row_measures_nothing` (`effective_duration == timedelta(0)`), `test_a_corrected_row_answers_its_override` (elapsed 1h, override 30m → `timedelta(minutes=30)`).

Structure tests:

```python
def test_the_model_passes_the_projection_checks():
    assert check_projection_models(apps=global_apps) == []


def test_both_references_are_registered():
    keys = {reference.key for reference in AUDITED_PROJECTION_REFERENCES}
    assert ("games.PlayerSession", "playthrough") in keys
    assert ("games.PlayerSession", "device") in keys
    assert unaudited_projection_references() == ()


def test_the_manager_states_alive():
    assert hasattr(PlayerSession._default_manager, "alive")


def test_alive_reads_the_run_and_the_tracked_game_but_not_the_catalog_game():
    # removed run -> hidden; removed PlayerGame -> hidden;
    # removed catalog Game -> still visible
```

And the mode-spelling pin, which the issue commissions:

```python
def test_the_modes_are_spelled_as_the_census_spells_them():
    assert {mode.value for mode in PlayerSessionTimingMode} == {
        verdict.value for verdict in MODE_VERDICTS
    }
```

- [x] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_playersession_projection.py -x"` → ImportError, no `PlayerSession`.

- [x] **Step 3: Add the model**

In `games/models.py`, after `Playthrough`. Every column the creation event states carries **no default** — that is what makes `_required_columns` hold the handler to naming it. The three generated columns:

```python
    effective_day = models.GeneratedField(
        expression=Coalesce(
            F("stated_day"),
            Cast(
                Func(F("day_zone"), F("started_at"), function="timezone"),
                models.DateField(),
            ),
        ),
        output_field=models.DateField(),
        db_persist=True,
        editable=False,
    )
    effective_duration = models.GeneratedField(
        expression=Coalesce(
            F("stated_duration"),
            F("ended_at") - F("started_at"),
            Value(timedelta(0)),
        ),
        output_field=models.DurationField(),
        db_persist=True,
        editable=False,
    )
    sort_instant = models.GeneratedField(
        expression=Coalesce(
            F("started_at"),
            Func(
                Value("UTC"),
                Cast(F("stated_day"), models.DateTimeField()),
                function="timezone",
            ),
        ),
        output_field=models.DateTimeField(),
        db_persist=True,
        editable=False,
    )
```

The `Cast` inside `sort_instant` is load-bearing: without casting the date to a naive timestamp first, PostgreSQL binds the STABLE `date → timestamptz` cast and refuses the column with `ERROR: generation expression is not immutable`. If Django's emitted SQL differs from `(stated_day::timestamp) AT TIME ZONE 'UTC'`, read the DDL with `schema_editor().table_sql(PlayerSession)` and adjust until it matches.

`Meta`: `get_latest_by = "sort_instant"`, the nine constraints (spec §"The constraints"), and the three indexes `playersession_day_order` `(library, effective_day, id)`, `playersession_sort_order` `(library, sort_instant, id)`, `playersession_run_day` `(playthrough, effective_day)`. Index names must stay ≤ 30 characters.

- [x] **Step 4: Register both references**

`games/projections.py`: append `ProjectionReference.on(PlayerSession, "playthrough")` and `ProjectionReference.on(PlayerSession, "device")` to `AUDITED_PROJECTION_REFERENCES`, importing `PlayerSession` beside the other two. Leaving either out fails `manage.py check` with `games.E009`.

- [x] **Step 5: Make and apply the migration**

```bash
make makemigrations ARGS="games --name playersession"
```

Then `make migrate`. Read the generated file before moving on: it must create one table with eight `CheckConstraint`s and three indexes, and no `AlterField` on anything else.

- [x] **Step 6: Run the tests**

`make test ARGS="tests/test_playersession_projection.py"` → all pass. Then `make check-fast`.

- [x] **Step 7: Commit**

```bash
git add games/models.py games/projections.py games/migrations tests/test_playersession_projection.py
git commit -m "feat: state what a recorded session holds"
```

---

### Task 2: The event and its payload

**Files:**
- Create: `games/events/playersession.py`
- Modify: `games/events/vocabulary.py:31` (the type-alias comment naming an event type that does not exist)
- Test: `tests/test_playersession_events.py`

**Interfaces consumed:** `PlayerSessionTimingMode` (Task 1).

**Interfaces produced:**
- `type InstantText = Annotated[str, AfterValidator(canonical_instant_text)]`
- `type DayText = Annotated[str, AfterValidator(canonical_day_text)]`
- `canonical_instant_text(value: str) -> str`, `canonical_day_text(value: str) -> str`
- `instant_text(value: datetime) -> str`, `day_text(value: date) -> str`, `instant_from_text(value: str) -> datetime`, `day_from_text(value: str) -> date`
- `TimedTimingPayload`, `DurationOnlyTimingPayload`, `CorrectedTimingPayload`, `TimingPayload`
- `PlayerSessionCreatedPayload`, `PLAYERSESSION_CREATED: EventSpec`
- `playersession_created(playthrough_id, *, timing, device, release, note, emulated, session_id=None) -> NewEvent`

- [x] **Step 1: Write the failing tests**

`tests/test_playersession_events.py`:

- `test_the_event_type_is_spelled_once_and_forever` — `PLAYERSESSION_CREATED.event_type == "library.playersession.created"` and `aggregate_type == "playersession"`.
- `test_a_timed_payload_round_trips` — validate through `DEFAULT_EVENT_TYPES.validate(...)` and get the same dict back.
- `test_an_unknown_mode_is_refused`, `test_an_extra_key_is_refused`, `test_a_missing_key_is_refused`, `test_a_lax_integer_is_refused` (`"90"` for `duration_seconds`) — each `pytest.raises(PayloadInvalid)`.
- `test_a_non_canonical_instant_is_refused` — `"2024-06-01T21:30:00Z"` refused, `"2024-06-01T21:30:00+00:00"` accepted.
- `test_a_non_canonical_day_is_refused` — `"2024-6-1"` refused.
- `test_a_malformed_instant_is_refused` — `"not a date"`.
- `test_an_instant_survives_the_round_trip_to_the_microsecond` — `instant_from_text(instant_text(value)) == value` for a value with microseconds and a non-UTC tzinfo.
- `test_the_references_are_enumerated` — `DEFAULT_EVENT_TYPES.reference_fields_for(...)` is `{"device": OPTIONAL, "release": OPTIONAL}`; `playthrough` is not a reference field.
- `test_the_payload_carries_the_day_as_its_effective_time` — `playersession_created(...).effective_time.canonical == "2026-01-02"` for a timed statement whose zone puts it there, and equals `stated_day` for a duration-only one.
- `test_the_identity_may_be_stated` — passing `session_id` uses it; omitting it mints a UUIDv7.

- [x] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_playersession_events.py -x"`.

- [x] **Step 3: Write the module**

Follow `games/events/playthrough.py`'s shape. The canonical-text validators mirror `canonical_uuid_text` in `games/events/references.py:46`: parse, reformat, refuse anything that differs.

```python
def canonical_instant_text(value: str) -> str:
    """The one spelling an instant is read back in."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{value!r} is not an ISO-8601 instant.") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{value!r} states no offset.")
    canonical = parsed.astimezone(UTC).isoformat()
    if canonical != value:
        raise ValueError(f"{value!r} is not canonical; {canonical!r} is.")
    return value
```

Each member gets its own `@with_config(STRICT_SCHEMA)`; `mode` is a `Literal`, never the `TextChoices` enum — strict validation refuses an enum for a recorded string, and the recorded vocabulary is frozen while the enum is not (the same reason `PlayerGameStatus` has `StatusValue` beside it).

`effective_time` is a `TemporalValue` over the day: `TemporalValue.parse(day_text(day))`, where the day is `stated_day` for a duration-only statement and `started_at` read in `day_zone` otherwise.

Fix the stale comment at `games/events/vocabulary.py:31` to read `# "library.playersession.created"`.

- [x] **Step 4: Run the tests, then the suite**

`make test ARGS="tests/test_playersession_events.py"`, then `make check-fast`.

- [x] **Step 5: Commit**

```bash
git add games/events/playersession.py games/events/vocabulary.py tests/test_playersession_events.py
git commit -m "feat: record what one session states about its time"
```

---

### Task 3: A duration fingerprints

**Files:**
- Modify: `games/events/idempotency.py:115-137` (`_encode_command_value`)
- Test: `tests/test_event_idempotency.py`

**Interfaces produced:** `_encode_command_value` answers `("duration", <total microseconds as text>)` for a `timedelta`.

- [x] **Step 1: Write the failing tests**

In `tests/test_event_idempotency.py`, beside the existing encoder tests:

```python
def test_a_duration_encodes_as_its_microseconds():
    assert _encode_command_value(timedelta(minutes=90)) == ("duration", "5400000000")


def test_two_spellings_of_one_duration_fingerprint_alike():
    assert fingerprint_command_input({"d": timedelta(hours=1)}) == (
        fingerprint_command_input({"d": timedelta(minutes=60)})
    )


def test_durations_a_microsecond_apart_fingerprint_differently():
    assert fingerprint_command_input({"d": timedelta(seconds=1)}) != (
        fingerprint_command_input({"d": timedelta(seconds=1, microseconds=1)})
    )


def test_a_negative_duration_keeps_its_sign():
    assert _encode_command_value(timedelta(seconds=-1)) == ("duration", "-1000000")
```

- [x] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_event_idempotency.py -k duration"` → `TypeError: timedelta has no canonical form…`.

- [x] **Step 3: Add the branch**

Above the `raise`, beside the `Decimal` branch. Use `value // timedelta(microseconds=1)`, which is exact and needs no float. `timedelta` normalises its own fields, so no further canonicalisation is needed — say so in a comment, because every other branch in that function exists to undo a non-canonical spelling.

- [x] **Step 4: Run the tests**

`make test ARGS="tests/test_event_idempotency.py"`.

- [x] **Step 5: Commit**

```bash
git add games/events/idempotency.py tests/test_event_idempotency.py
git commit -m "feat: give a duration one canonical form"
```

---

### Task 4: The projector

**Files:**
- Create: `games/projectors/playersession.py`
- Modify: `games/projectors/__init__.py`
- Test: `tests/test_playersession_projection.py` (append)

**Interfaces consumed:** Task 1's model, Task 2's `PLAYERSESSION_CREATED` and payload types.

**Interfaces produced:**
- `columns_for_timing(timing: TimingPayload) -> dict[str, Any]` — always eight keys: `timing_mode`, `started_at`, `started_at_zone`, `ended_at`, `ended_at_zone`, `stated_day`, `stated_duration`, `day_zone`, with `None` for every column the mode forbids
- `PlayerSessions(Projector)`, family `ProjectorFamily.CURRENT_STATE`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_playersession_projection.py` (the module already carries `pytestmark = pytest.mark.untracked_games`):

- `test_the_mapper_names_every_timing_column` — for each of the three payload members, `set(columns_for_timing(...))` equals the eight names, and the forbidden ones are `None`.
- `test_the_creation_handler_writes_the_whole_row` — replay one appended event and assert `_unfilled_columns` reports nothing; simplest form is to let `project()` do it and assert no `TypeError`.
- `test_the_projection_replays_from_an_empty_stream` — append creation events for three sessions across the modes, `PlayerSession.objects.all().delete()`, `replay(...)`, and assert every column of every row equals what it held before (copy the comparison style from `test_playthrough_projection.py`).
- `test_a_rebuild_reports_no_drift` — `rebuild_projections(..., mode=RebuildMode.CHECK)` reports zero differing rows, generated columns included.
- `test_a_session_names_the_run_the_event_names` — the row's `playthrough_id` comes off the payload, and `library_id` off the event, never off a command context.

- [x] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_playersession_projection.py -k replay -x"`.

- [x] **Step 3: Write the projector**

Follow `games/projectors/playthrough.py`. One handler:

```python
    def _created(self, event: RecordedEvent) -> None:
        payload = event.payload
        device = payload["device"]
        self.project(
            PlayerSession,
            event.aggregate_id,
            #: From the event, never a command's context.
            library_id=event.library_id,
            playthrough_id=uuid.UUID(payload["playthrough"]),
            device_id=None if device is None else uuid.UUID(device["id"]),
            note=payload["note"],
            emulated=payload["emulated"],
            created_at=event.recorded_at,
            **columns_for_timing(payload["timing"]),
        )
```

`columns_for_timing` lives in the same module and is what #692's correction handler will import; it returns all eight keys for every member, so an `amend()` that switches mode clears what the new mode forbids.

Add `playersession` to the import in `games/projectors/__init__.py`.

- [x] **Step 4: Run the tests**

`make test ARGS="tests/test_playersession_projection.py"`, then `make check-fast`.

- [x] **Step 5: Commit**

```bash
git add games/projectors tests/test_playersession_projection.py
git commit -m "feat: project the sessions a library records"
```

---

### Task 5: The creation command

**Files:**
- Create: `games/commands/playersession.py`
- Modify: `games/events/dispatch.py:74-97` (`CommandName`)
- Test: `tests/test_playersession_command.py`

**Interfaces consumed:** Task 2's event builder, `_live_run` and `library_row` from `games/commands/playthrough.py` and `games/commands/scope.py`.

**Interfaces produced:**
- `TimedTiming`, `DurationOnlyTiming`, `CorrectedTiming` (`NamedTuple`s), `type TimingStatement = TimedTiming | DurationOnlyTiming | CorrectedTiming`
- `CreateSession(Command)` with `command_name = CommandName.PLAYERSESSION_CREATE`
- `known_zone(name: str) -> bool` — true only when both `zoneinfo` and `pg_timezone_names` know it, cached

- [x] **Step 1: Write the failing tests**

`tests/test_playersession_command.py`. Every test that dispatches needs `@pytest.mark.django_db(transaction=True)` — `run_in_transaction` refuses to nest.

Happy paths: one per mode, asserting the row's columns, its `effective_day`, its `effective_duration`, and that the appended event count is 1.

Refusals — each asserts `CommandRejected` and a non-empty `error.sentence`:

| test | input |
|---|---|
| `test_it_refuses_a_run_another_library_holds` | a run under a second library |
| `test_it_refuses_a_removed_run` | run with `removed_at` set |
| `test_it_refuses_a_run_under_a_removed_game` | `PlayerGame.removed_at` set |
| `test_it_refuses_a_device_another_library_holds` | device under a second library |
| `test_it_refuses_a_removed_device` | removed device |
| `test_it_refuses_an_end_before_its_start` | timed, end one hour early |
| `test_it_refuses_a_corrected_end_before_its_start` | corrected, same |
| `test_it_refuses_a_negative_duration` | duration-only, `timedelta(minutes=-1)` |
| `test_it_refuses_a_duration_finer_than_a_second` | `timedelta(seconds=90, microseconds=1)` |
| `test_it_refuses_a_duration_only_statement_of_nothing` | `timedelta(0)` |
| `test_it_refuses_an_end_zone_without_an_end` | timed, `ended_at=None`, `ended_at_zone="Asia/Tokyo"` |
| `test_it_refuses_a_naive_instant` | `datetime(2026, 1, 1, 12, 0)` |
| `test_it_refuses_a_zone_neither_tzdata_knows` | `"Not/AZone"` |
| `test_it_refuses_a_blank_day_zone` | `day_zone=""` |

Plus:

```python
def test_a_retry_of_one_statement_appends_nothing_more(owned_library, run):
    command = CreateSession(playthrough_id=run.pk, timing=_timed())
    first = dispatch(
        command, library=owned_library, actor=owned_library.user, idempotency_key="k"
    )
    second = dispatch(
        command, library=owned_library, actor=owned_library.user, idempotency_key="k"
    )
    assert second.outcome is CommandOutcome.REPLAYED
    assert LibraryEvent.objects.filter(library=owned_library).count() == 1
```

and `test_it_never_answers_unchanged` (two dispatches under different keys both append).

- [x] **Step 2: Run them and watch them fail**

`make test ARGS="tests/test_playersession_command.py -x"`.

- [x] **Step 3: Write the command**

`CommandName.PLAYERSESSION_CREATE = "library.playersession.create"` in `games/events/dispatch.py`, in declaration order after the playthrough entries.

`__post_init__` strips the note, exactly as `CreatePlaythrough` does, so a restatement fingerprints alike. `build()`:

1. `run = _live_run(context, self.playthrough_id)` — one import, and the removed-run and removed-game refusals are stated once for the wave.
2. Device, when given, through `library_row(context, Device.objects.all(), Refusal(...), pk=self.device_id)`, then refuse a removed one. `Device.objects` is a `RemovableLibraryQuerySet`, so `.all()` still sees removed rows and the refusal can name them.
3. Validate the statement: instants aware, end not before start, duration whole seconds and positive, zones known, endpoint zone only beside its instant.
4. `return [playersession_created(run.pk, …)]`.

`known_zone` reads `pg_timezone_names` once:

```python
@lru_cache(maxsize=1)
def _database_zones() -> frozenset[str]:
    """The zones PostgreSQL can evaluate.

    Python's tzdata and the database's are different data sets in this
    deployment, and a name only Python knows reaches the generated
    column as a DataError inside the append.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM pg_timezone_names")
        return frozenset(name for (name,) in cursor.fetchall())
```

- [x] **Step 4: Run the tests**

`make test ARGS="tests/test_playersession_command.py"`, then
`make test ARGS="tests/test_command_scope_guard.py tests/test_command_answers.py"` — the scope guard walks `games/commands/` and the answers test walks the conflict registries.

- [x] **Step 5: Commit**

```bash
git add games/commands/playersession.py games/events/dispatch.py tests/test_playersession_command.py
git commit -m "feat: record one session against a stated run"
```

---

### Task 6: Documentation and the gate

**Files:**
- Modify: `CLAUDE.md` (the Models list, after the `Playthrough` entry)
- Test: the whole suite

- [x] **Step 1: Document the model**

Add a `PlayerSession` entry to `CLAUDE.md`'s Models section in the voice of the entries around it: the third projection, its three modes and what each admits, the two generated day/duration columns and the sort instant, the mandatory run reference, `alive()`'s two ancestor marks and why the catalog game's is not among them, and that the database admits a superset of what the command admits. Name the spec.

- [x] **Step 2: Run the prose linter**

`make vale` — the vocabulary refuses `delete`, `fold` and the projector/projection word confusions in comments and docs alike.

- [x] **Step 3: Run the full gate**

`make check` — lint, format check, mypy, vale, ts-check, vitest, and the entire pytest suite including `e2e/`. Never a hand-picked subset. Do not run it while `make dev` is up: the watchers rewrite the served assets and e2e fails en masse.

- [x] **Step 4: Verify the replay parity target**

`make verify-replay-parity` — read-only, replays every library and fails on a differing row. It is not part of `make check`, and this is the change that can break it.

- [x] **Step 5: Commit and open the PR**

```bash
git add CLAUDE.md
git commit -m "docs: name what a PlayerSession holds"
```

Open the PR against `main` with `gh pr create`, naming the issue and the spec. Merge with `gh pr merge --merge` — never squash, never rebase.

---

## Follow-up issues to file

- **Restate a library's days when its display zone changes.** The wave files it; this spec narrows it: the restatement is an **event**, not a bulk `UPDATE`, because the rebuild's diff compares whole rows and `swap_in` would revert anything the events do not determine. It owes a reconciliation with `ActivityClock`, whose zone stops deciding a session's day once `effective_day` is stored.
- **`answers.py` has no answer for a database refusal.** An `IntegrityError` or `DataError` raised inside a command's transaction is in none of `CONFLICT_ANSWERS`, `ANSWERED_DIRECTLY` or `NOT_ANSWERED`, so it escapes `answered()` as a 500 after the stream head is locked. This wave avoids it by keeping every CHECK looser than its command; the boundary should still answer one.
