# Correct and rename a Playthrough — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A library corrects a Playthrough's name, its note, and either
endpoint's date and note, each through a command with its own event.

**Architecture:** Three commands in `games/commands/playthrough.py` beside the
two #681 shipped — `DescribePlaythrough`, `CorrectPlaythroughStart`,
`CorrectPlaythroughCompletion` — appending four new event types, replayed by
four `amend()` handlers on the `Playthroughs` projector. No screen, no form, no
route, no migration.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pydantic-validated event
payloads, pytest.

**Spec:** `docs/superpowers/specs/2026-09-06-issue-1010-playthrough-corrections-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never a bare
  `uv run` / `pnpm` / `pytest`. Focused runs: `make test ARGS="…"`. `ARGS` is
  interpolated unquoted, so a `-k` expression carries its own quotes.
- **The verification gate is the full `make check`**, including `e2e/`. Use
  `make check-fast` while iterating.
- **A command carries no model instance.** Fields are hashed into the
  idempotency fingerprint, so a command holds a UUID and re-fetches in `build`.
- **No dispatch inside a transaction.** A test that dispatches needs
  `@pytest.mark.django_db(transaction=True)`.
- **A rejection carries two sentences.** `raise CommandRejected(message,
  sentence=…)`: the argument is for a log, `sentence` is the only thing a
  person reads. Every raise site here states one.
- **Never write a `GeneratedField`**: `started_lower`, `started_upper`,
  `completed_lower`, `completed_upper`.
- **A projector reads only its event.** No clock, no command context, no read
  of the row it writes.
- **Full words in identifiers**: `event` not `e`, `playthrough`/`run` not `p`.
- **Refused words** are enforced by `make vale` over docs *and* code comments:
  a projector **replays**, the row is the **projection**, a record is
  **removed**. See `docs/vocabulary.md`.
- **Comments earn their place.** Seven words where seven will do, `#:` for a
  fact about the line below it, prose for a decision that a reader would
  otherwise re-litigate.

---

## File Structure

**Created**

| Path | Responsibility |
|---|---|
| — | Nothing. Every file this issue needs exists. |

**Modified**

| Path | Change |
|---|---|
| `games/events/playthrough.py` | Two payload types, four `EventSpec`s, four builders |
| `games/events/dispatch.py:90-92` | Three `CommandName` members |
| `games/projectors/playthrough.py` | Four handlers, four `handles` entries |
| `games/commands/playthrough.py` | `_endpoint_subject` → `_live_run`; three commands; the name bound |
| `games/models.py:1634,1637` | The two `#1010 states it` comments |
| `CLAUDE.md` | The `Playthrough` bullet's future tense |
| `tests/test_playthrough_events.py` | The four specs, their payloads, their builders |
| `tests/test_playthrough_projection.py` | Four handlers, one replay from empty |
| `tests/test_playthrough_command.py` | Every refusal, every `Unchanged`, the fingerprints |

---

## Task 1: The resolver says what it returns

**Files:**
- Modify: `games/commands/playthrough.py:109-133,153,191`

A pure rename, first, so every task after it reads the settled name.
`_endpoint_subject` refuses a removed run and a removed tracked game; a rename
is not an endpoint. `_live_run` says what it returns: the run, when neither
mark is set.

Nothing outside the module names it — it is private, and `grep -rn
"_endpoint_subject"` finds the definition and two calls. #909 merges
`library_playthrough()` with the two other library-scoped resolvers; it does
not merge this one, which states a removal rule the other two have no column
for.

- [ ] **Step 1: Make the change**

Rename the function and both calls. Its docstring already reads generically
("The run, refused if nothing may be stated about it") — leave it.

- [ ] **Step 2: Run the tests**

Run: `make test ARGS="tests/test_playthrough_command.py"`
Expected: PASS, unchanged. A rename with a behaviour change is two commits.

- [ ] **Step 3: Commit**

```bash
git add games/commands/playthrough.py
git commit -m "Name the resolver for what it returns"
```

---

## Task 2: The name and the note are two events

**Files:**
- Modify: `games/events/playthrough.py`
- Test: `tests/test_playthrough_events.py`

**Interfaces:**
- Produces: `PLAYTHROUGH_NAME_CHANGED`, `PLAYTHROUGH_NOTE_CHANGED`,
  `playthrough_name_changed()`, `playthrough_note_changed()` for Tasks 4 and 5.

Neither event carries an `effective_time`. A rename happens on no day in the
world. `library.playergame.mastered_changed` is the precedent that states
none; `library.playergame.status_changed` states one because a status is a
fact the Journal places on a day.

`note_changed` takes a payload type of its own rather than reusing
`PlaythroughEndpointPayload`. The shape is identical and the meaning is not:
that type's docstring binds its note to an act whose date is the
`effective_time`, and the row's note has no day.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_events.py`, following the shape of the
existing registration and payload tests:

```python
def test_the_descriptive_events_are_in_the_default_vocabulary():
    name = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.name_changed")
    note = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.note_changed")

    assert (name, note) == (PLAYTHROUGH_NAME_CHANGED, PLAYTHROUGH_NOTE_CHANGED)
    assert name.aggregate_type == "playthrough"


def test_a_descriptive_payload_refuses_the_other_one_s_key():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYTHROUGH_NAME_CHANGED.event_type, {"note": "second run"}
        )


def test_a_rename_states_no_day():
    """A name is true of the run, not of a date."""
    identity = uuid.uuid7()

    renamed = playthrough_name_changed(identity, name="Ironman")

    assert renamed.aggregate_id == identity
    assert renamed.effective_time is None
    assert renamed.payload == {"name": "Ironman"}
```

Import the two specs and the two builders beside the existing ones.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_events.py -k descriptive or rename"`
Expected: ImportError — the names do not exist yet.

- [ ] **Step 3: Make the change**

In `games/events/playthrough.py`, after `PlaythroughEndpointPayload` and its
two specs:

```text
@with_config(STRICT_SCHEMA)
class PlaythroughNamePayload(TypedDict):
    """What the library calls this run. Blank reads as its number."""

    name: str


@with_config(STRICT_SCHEMA)
class PlaythroughNotePayload(TypedDict):
    """The note of the whole run.

    Not `PlaythroughEndpointPayload`, though the shape is the same:
    that note belongs to an act, and its day is the effective_time.
    This one describes a run and has no day.
    """

    note: str


PLAYTHROUGH_NAME_CHANGED = EventSpec(
    "library.playthrough.name_changed",
    aggregate_type="playthrough",
    payload=PlaythroughNamePayload,
)

PLAYTHROUGH_NOTE_CHANGED = EventSpec(
    "library.playthrough.note_changed",
    aggregate_type="playthrough",
    payload=PlaythroughNotePayload,
)

DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_NAME_CHANGED)
DEFAULT_EVENT_TYPES.register(PLAYTHROUGH_NOTE_CHANGED)


def playthrough_name_changed(playthrough_id: uuid.UUID, *, name: str) -> NewEvent:
    """The library calls the run this now."""
    #: No effective_time: a rename happens on no day.
    return PLAYTHROUGH_NAME_CHANGED.new(
        aggregate_id=playthrough_id, payload={"name": name}
    )


def playthrough_note_changed(playthrough_id: uuid.UUID, *, note: str) -> NewEvent:
    """The note of the run, as it now reads."""
    return PLAYTHROUGH_NOTE_CHANGED.new(
        aggregate_id=playthrough_id, payload={"note": note}
    )
```

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_playthrough_events.py"`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add games/events/playthrough.py tests/test_playthrough_events.py
git commit -m "Record a Playthrough's name and note as events"
```

---

## Task 3: A corrected endpoint is its own event

**Files:**
- Modify: `games/events/playthrough.py`
- Test: `tests/test_playthrough_events.py`

**Interfaces:**
- Consumes: `PlaythroughEndpointPayload` (same module).
- Produces: `PLAYTHROUGH_START_CORRECTED`, `PLAYTHROUGH_COMPLETION_CORRECTED`
  and their builders for Tasks 4 and 6.

Both reuse `PlaythroughEndpointPayload`: they are separate `EventSpec`s, so an
issue that gives one of them a field gives it a type of its own. The corrected
date rides in `effective_time`, as it does on the event being corrected.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_correction_events_are_in_the_default_vocabulary():
    started = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.start_corrected")
    completed = DEFAULT_EVENT_TYPES.spec_for("library.playthrough.completion_corrected")

    assert (started, completed) == (
        PLAYTHROUGH_START_CORRECTED,
        PLAYTHROUGH_COMPLETION_CORRECTED,
    )


def test_a_corrected_endpoint_carries_its_date_as_the_effective_time():
    identity = uuid.uuid7()
    when = TemporalValue.from_month(2024, 3)

    corrected = playthrough_start_corrected(identity, when=when, note="blind run")

    assert corrected.aggregate_id == identity
    assert corrected.effective_time == when
    assert corrected.payload == {"note": "blind run"}


def test_a_corrected_endpoint_states_an_unknown_day_as_no_effective_time():
    corrected = playthrough_completion_corrected(uuid.uuid7(), when=None, note="")

    assert corrected.effective_time is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_events.py -k correct"`
Expected: ImportError.

- [ ] **Step 3: Make the change**

Two specs and two builders, in the shape of `playthrough_started`. Each passes
the run's id as `aggregate_id`, because the aggregate exists.

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_playthrough_events.py"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/events/playthrough.py tests/test_playthrough_events.py
git commit -m "Record a corrected Playthrough endpoint as an event"
```

---

## Task 4: The projector replays the four

**Files:**
- Modify: `games/projectors/playthrough.py`
- Test: `tests/test_playthrough_projection.py`

**Interfaces:**
- Consumes: the four specs from Tasks 2 and 3.

All four `amend()`. None may `project()`: `project()` instantiates the model
and refuses a column no handler filled, so a correction event — which knows
nothing of `player_game`, `kind` or `created_at` — raises `TypeError` there.

Neither correction handler names a marker column. That is what keeps the first
statement's instant across a rebuild.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playthrough_projection.py`, using the module's existing
`dispatch` + `RecordedEvent` helpers rather than a second set.

The load-bearing one:

```python
@pytest.mark.django_db(transaction=True)
def test_a_replay_keeps_the_instant_the_start_was_recorded(
    owned_user, owned_library, game
):
    """A correction states a better date, not a second act."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    _correct_start(owned_user, owned_library, run, when=TemporalValue.from_year(2024))
    stated_at = Playthrough.objects.get(pk=run.pk).start_recorded_at

    Playthrough.objects.all().delete()
    replay(...)

    rebuilt = Playthrough.objects.get(pk=run.pk)
    assert rebuilt.start_recorded_at == stated_at
    assert rebuilt.started == TemporalValue.from_year(2024)
```

Follow the file's existing replay test for the exact `replay(...)` call and its
`Playthrough.objects.all().delete()` precedent — a projection test destroys
rows to prove a rebuild writes them, which is not the library's removal act.

Add one test per handler: a rename over a recorded event, a note, a corrected
start, a corrected completion, each asserting the row and asserting the other
endpoint's marker reads back null.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_projection.py -k correct or rename or replay"`
Expected: the handlers are missing, so the event has no owner and the row keeps
its old value.

- [ ] **Step 3: Make the change**

In `games/projectors/playthrough.py`:

```text
    def _name_changed(self, event: RecordedEvent) -> None:
        self.amend(Playthrough, event.aggregate_id, name=event.payload["name"])

    def _note_changed(self, event: RecordedEvent) -> None:
        self.amend(Playthrough, event.aggregate_id, note=event.payload["note"])

    def _start_corrected(self, event: RecordedEvent) -> None:
        #: No marker: the act was recorded when it was stated.
        self.amend(
            Playthrough,
            event.aggregate_id,
            started=event.effective_time,
            start_note=event.payload["note"],
        )

    def _completion_corrected(self, event: RecordedEvent) -> None:
        self.amend(
            Playthrough,
            event.aggregate_id,
            completed=event.effective_time,
            completion_note=event.payload["note"],
        )
```

Add the four entries to `handles`.

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_playthrough_projection.py"`
Expected: PASS, whole file. `test_playthrough_is_a_pure_projection` and the
`_required_columns` tests still pass — no column changed.

- [ ] **Step 5: Commit**

```bash
git add games/projectors/playthrough.py tests/test_playthrough_projection.py
git commit -m "Replay a rename, a note and a corrected endpoint"
```

---

## Task 5: Describe a run

**Files:**
- Modify: `games/commands/playthrough.py`, `games/events/dispatch.py`
- Test: `tests/test_playthrough_command.py`

**Interfaces:**
- Consumes: `_live_run` (Task 1), the two builders (Task 2).
- Produces: `DescribePlaythrough` for #1012.

One command, two facts, `None` for a fact it does not state — the shape
`RecordPlayerGameFacts` settled. `__post_init__` refuses a command that states
neither, and strips each stated value: a name of three spaces is a cleared
name, not a name that silently costs the row its number.

Two refusals read the command's own values and stand ahead of the comparison: a
name longer than the column, and a cleared name on a run whose `kind` is not
`ORDINARY`, for which no display number is counted.

- [ ] **Step 1: Write the failing tests**

Add a `_describe` helper beside `_start` and `_complete`, then:

```python
@pytest.mark.django_db(transaction=True)
def test_describing_a_run_records_one_event_per_stated_fact(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    result = _describe(owned_user, owned_library, run, name="Ironman", note="no saves")

    assert result.outcome is CommandOutcome.APPENDED
    assert Playthrough.objects.get().name == "Ironman"
    assert Playthrough.objects.get().note == "no saves"


@pytest.mark.django_db(transaction=True)
def test_a_fact_the_command_does_not_state_is_left_alone(
    owned_user, owned_library, game
):
    """None is not a value; it is the absence of a statement."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name="Ironman", note="no saves")

    _describe(owned_user, owned_library, run, name=None, note="one save", key="again")

    assert Playthrough.objects.get().name == "Ironman"


@pytest.mark.django_db(transaction=True)
def test_a_cleared_name_reads_as_the_display_number(owned_user, owned_library, game):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _describe(owned_user, owned_library, run, name="Ironman", note=None)

    _describe(owned_user, owned_library, run, name="   ", note=None, key="again")

    numbered = with_display_number(Playthrough.objects.all()).get()
    assert display_name(numbered) == "Playthrough 1"


@pytest.mark.django_db(transaction=True)
def test_a_command_that_states_no_fact_is_not_a_command():
    with pytest.raises(ValueError):
        DescribePlaythrough(playthrough_id=uuid.uuid7(), name=None, note=None)
```

Plus: a name over the column's length refused with its sentence; a cleared name
on an `IMPORTED_HISTORY` run refused with its sentence; both facts already
holding answering `UNCHANGED`; a removed run and a removed tracked game refused
through `_live_run`; a run of another library refused with the sentence that
names no id.

Build the imported-history row with `playthrough_created(..., kind=
"imported_history")` through the stream, as the projection tests do — not with
`Playthrough.objects.create()`, which no code path may.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_command.py -k describe"`
Expected: ImportError.

- [ ] **Step 3: Make the change**

`CommandName.PLAYTHROUGH_DESCRIBE = "library.playthrough.describe"` in
`games/events/dispatch.py`, beside the three Playthrough members.

The bound is a module constant, because django-stubs types `max_length` as
`int | None` — the shape `EVENT_TYPE_MAX_LENGTH` and
`IDEMPOTENCY_KEY_MAX_LENGTH` already use:

```text
PLAYTHROUGH_NAME_MAX_LENGTH: int = cast(
    "int", Playthrough._meta.get_field("name").max_length
)
```

Then the command:

```text
@dataclass(frozen=True, slots=True)
class DescribePlaythrough(Command):
    """State the run's name, its note, or both."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_DESCRIBE
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    #: None states no fact. "" clears the value.
    name: str | None
    note: str | None

    def __post_init__(self) -> None:
        if self.name is None and self.note is None:
            raise ValueError(
                "DescribePlaythrough states no fact. A command that asks for "
                "nothing would still claim an idempotency key and write a "
                "record for a request that expressed no intent."
            )
        #: A name of three spaces is a cleared name.
        for field_name in ("name", "note"):
            stated = getattr(self, field_name)
            if stated is not None:
                object.__setattr__(self, field_name, stated.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        ...
```

The build, in order: the length refusal, the kind refusal, then one event per
value that differs, then `Unchanged`. Both refusals read the command's own
values, so neither is excused by the row already holding one.

The two sentences:

- over the length — "That name is too long. Keep it under 255 characters."
  (interpolate the constant rather than writing the number twice);
- a cleared name on a bucket — "This run is not numbered, so it needs a name of
  its own."

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_playthrough_command.py"`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add games/commands/playthrough.py games/events/dispatch.py tests/test_playthrough_command.py
git commit -m "State a Playthrough's name and note"
```

---

## Task 6: Correct an endpoint

**Files:**
- Modify: `games/commands/playthrough.py`, `games/events/dispatch.py`
- Test: `tests/test_playthrough_command.py`

**Interfaces:**
- Consumes: `_live_run`, `stated_start` / `stated_completion`,
  `endpoints_certainly_reversed`, the two builders (Task 3).
- Produces: `CorrectPlaythroughStart`, `CorrectPlaythroughCompletion` for
  #1012.

The branch order is the one thing to get right, and it inverts #906's:

1. `_live_run` — the library, then the two removal marks;
2. **the marker.** `stated_start(run) is None` is refused here, ahead of
   `Unchanged`;
3. the value comparison — `(when, note)` against `(stated.when, stated.note)`.
   Equal is `Unchanged`;
4. `endpoints_certainly_reversed`, with the moved value in its own slot.

Step 2 is ahead of step 3 because an unstated endpoint holds exactly the values
a "played before" correction states: `started` is null and `start_note` is `""`
on a row that never started. Under #906's order that dispatch answers
`UNCHANGED`, claims an idempotency key, and tells the player nothing is wrong.

- [ ] **Step 1: Write the failing tests**

The one that pins the order:

```python
@pytest.mark.django_db(transaction=True)
def test_correcting_an_endpoint_that_was_never_stated_is_refused(
    owned_user, owned_library, game
):
    """The values match a row that never started. The marker does not."""
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    with pytest.raises(CommandRejected) as refusal:
        _correct_start(owned_user, owned_library, run, when=None, note="")

    assert refusal.value.sentence == (
        "This run has no start to correct. Record that it started first."
    )
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playthrough.start_corrected"
        ).count()
        == 0
    )
```

And the one that pins the marker:

```python
@pytest.mark.django_db(transaction=True)
def test_a_correction_leaves_the_instant_the_act_was_recorded(
    owned_user, owned_library, game
):
    _track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    _start(owned_user, owned_library, run, when=TemporalValue.from_year(2023))
    stated_at = Playthrough.objects.get().start_recorded_at

    _correct_start(owned_user, owned_library, run, when=TemporalValue.from_year(2024))

    corrected = Playthrough.objects.get()
    assert corrected.start_recorded_at == stated_at
    assert corrected.started == TemporalValue.from_year(2024)
```

Plus, for each of the two commands: a corrected date; a corrected endpoint
note; a date cleared to unknown leaving the act stated; the identical pair
answering `UNCHANGED`; `TemporalValue.unknown()` restating a dateless endpoint;
the reversed pair refused, from the start side and from the completion side;
the three `_live_run` refusals.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_playthrough_command.py -k correct"`
Expected: ImportError.

- [ ] **Step 3: Make the change**

Two `CommandName` members —
`PLAYTHROUGH_CORRECT_START = "library.playthrough.correct_start"` and
`PLAYTHROUGH_CORRECT_COMPLETION = "library.playthrough.correct_completion"` —
and two commands in the shape of `StartPlaythrough`, each with
`stated_date()` in `__post_init__`.

The order call, per command:

```text
        if endpoints_certainly_reversed(started=self.when, completed=run.completed):
```

```text
        if endpoints_certainly_reversed(started=run.started, completed=self.when):
```

Sentences: the unstated endpoint as above; the reversed pair reuses the
wording #681 states, because the fact refused is the same one.

- [ ] **Step 4: Run them and watch them pass**

Run: `make test ARGS="tests/test_playthrough_command.py tests/test_playthrough_projection.py"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/commands/playthrough.py games/events/dispatch.py tests/test_playthrough_command.py
git commit -m "Correct a stated Playthrough endpoint"
```

---

## Task 7: The idempotency evidence

**Files:**
- Test: `tests/test_playthrough_command.py`

The acceptance block asks event-sourced work to prove idempotency, and two
fingerprint claims in the spec are load-bearing. #681 tests both by name; this
task does the same for the three new commands.

- [ ] **Step 1: Write the tests**

- a repeat under one key records nothing further, once per command shape. The
  outcome is `REPLAYED`, and the event count does not move;
- `unknown()` and `None` fingerprint alike on a correction: dispatch with
  `when=None`, then re-dispatch under the *same* key with
  `TemporalValue.unknown()`, and read `REPLAYED`. Without `stated_date()` the
  encoder tags the unknown value and the digests differ, which is the
  regression this pins;
- `name=None` and `name=""` fingerprint apart: two dispatches under one key,
  and the second answers with a mismatch rather than replaying. This is what
  makes them two answers.

- [ ] **Step 2: Run them**

Run: `make test ARGS="tests/test_playthrough_command.py -k fingerprint or repeat"`
Expected: PASS, and each fails if `stated_date()` is taken out of the
correction's `__post_init__`. Check that by hand once; do not commit the
removal.

- [ ] **Step 3: Commit**

```bash
git add tests/test_playthrough_command.py
git commit -m "Pin the fingerprints of a correction"
```

---

## Task 8: The docs sweep and the gate

**Files:**
- Modify: `games/models.py:1634,1637`, `games/commands/playthrough.py`,
  `CLAUDE.md`

Four places name this issue in the future tense:

- `Playthrough.name` — "#1010 states it; blank reads as `Playthrough N`";
- `Playthrough.note` — "#1010 states it";
- the two sentences in `StartPlaythrough` and `CompletePlaythrough` that read
  "#1010 corrects a stated endpoint". They now name the command a person is
  sent to, and they stay short;
- the `Playthrough` bullet in `CLAUDE.md`, which describes the row's name and
  note as unstated and the endpoint refusals as pointing forward.

Keep the register: ASD-STE100 for the docs, seven words for a comment, and no
refused word in either.

- [ ] **Step 1: Correct the four**

- [ ] **Step 2: Run the gate**

Run: `make check`
Expected: green, `e2e/` included. `make vale` is inside it and reads the two
new spec and plan documents as well as every comment this issue wrote.

- [ ] **Step 3: Commit**

```bash
git add games/models.py games/commands/playthrough.py CLAUDE.md
git commit -m "Sweep the comments for the Playthrough corrections"
```

---

## Out of scope

No screen, no form, no API route, no `PlayEvent` path: #1012 through #1015
switch the reads and #687 switches the writes. No removal or restoration:
#1011. No repair of a pair already stored reversed, no retraction of a stated
endpoint, and no uniqueness over the name — the spec states why for each.
