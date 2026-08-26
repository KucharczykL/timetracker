# PlayerGame mastered Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A library records mastery of a tracked game through a command and an
event, projected onto a new `PlayerGame.mastered` column.

**Architecture:** This repeats the shape #672 gave `status`, with one difference:
the payload holds a plain `bool`, so no `Literal` is needed. A constant `False`
default covers every row no event touched; one event type,
`library.playergame.mastered_changed`, states both directions; the handler amends
the row by primary key; `SetPlayerGameMastered` builds the event behind the
stream-head lock.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pydantic (strict payload
validation), pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-issue-673-playergame-mastered-design.md`

## Global Constraints

- Run everything through `make`. Never `uv run`, `pytest` or `direnv exec .`
  directly. Focused runs: `make test ARGS="tests/test_x.py -k name"`.
- The verification gate is the full `make check`, including `e2e/`. `make
  check-fast` is for iterating only.
- Python 3.14 is required. A `SyntaxError` in an `except A, B:` line means the
  wrong interpreter, not broken code.
- Never write to a `GeneratedField`.
- Name variables with complete words: `event` not `e`, `template` not `tpl`.
- Comments are `#:` one-liners of about seven words. Docstrings are one line
  unless the reason needs more.
- Commit subjects are seven words, in the imperative.
- Every projection column default must be a literal constant. `games.checks`
  E004 to E007 refuse a db default and a callable default.
- Payload validation is strict (`ConfigDict(extra="forbid", strict=True)`): no
  coercion, no extra keys.

---

### Task 1: The column and its migration

**Files:**
- Modify: `games/models.py:1306-1330` (the `PlayerGame` class)
- Create: `games/migrations/0030_playergame_mastered.py` (generated)
- Test: `tests/test_projection_model.py:243-246` (`PINNED_DEFAULTS`)
- Test: `tests/test_playergame_projection.py:50-53` (beside the status default)

**Interfaces:**
- Consumes: nothing.
- Produces: `PlayerGame.mastered`, a `BooleanField` that starts at `False`.
  Tasks 3 and 4 read and write it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_projection_model.py`, extend the pinned defaults:

```python
#: Every constant a projection column starts at.
PINNED_DEFAULTS: dict[str, dict[str, object]] = {
    "games.PlayerGame": {"status": "unplayed", "mastered": False},
}
```

In `tests/test_playergame_projection.py`, add below
`test_a_tracked_game_starts_unplayed`:

```python
def test_a_tracked_game_starts_unmastered():
    """The creation event states no mastery."""
    assert PlayerGame().mastered is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_projection_model.py tests/test_playergame_projection.py -k 'pinned or unmastered'"`

Expected: FAIL. `test_a_tracked_game_starts_unmastered` raises
`AttributeError: 'PlayerGame' object has no attribute 'mastered'`, and
`test_every_projection_default_is_pinned` reports a dict without `mastered`.

- [ ] **Step 3: Add the column**

In `games/models.py`, inside `PlayerGame`, below the `status` field:

```python
    #: No event states it: a constant default.
    mastered = models.BooleanField(default=False)
```

- [ ] **Step 4: Generate the migration**

Run: `make makemigrations ARGS="games playergame_mastered"`

Expected: `games/migrations/0030_playergame_mastered.py`, holding one
`AddField` for `mastered` with `default=False`. Read it. It must add nothing
else and must carry no `RunPython`: every existing row is a projection of events
that state nothing about mastery, so `False` is already correct for each.

- [ ] **Step 5: Apply it and run the tests**

Run: `make migrate` then
`make test ARGS="tests/test_projection_model.py tests/test_playergame_projection.py"`

Expected: PASS, including `test_playergame_is_a_pure_projection` — a literal
default trips none of E004 to E007.

- [ ] **Step 6: Commit**

```bash
git add games/models.py games/migrations/0030_playergame_mastered.py tests/test_projection_model.py tests/test_playergame_projection.py
git commit -m "Give a tracked game a mastered column"
```

---

### Task 2: The event

**Files:**
- Modify: `games/events/playergame.py` (append below the status event)
- Test: `tests/test_playergame_events.py` (append below the status tests)

**Interfaces:**
- Consumes: `PlayerGame.mastered` from Task 1 (in name only; nothing imports it
  here).
- Produces: `PLAYERGAME_MASTERED_CHANGED`, an `EventSpec` whose `event_type` is
  `"library.playergame.mastered_changed"`, `aggregate_type` is `"playergame"`,
  and payload is `PlayerGameMasteredChangedPayload`, a `TypedDict` with one key,
  `mastered: bool`. Tasks 3 and 4 import it from
  `games.events.playergame`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_events.py`:

```python
def test_the_mastered_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playergame.mastered_changed")

    assert registered is PLAYERGAME_MASTERED_CHANGED
    assert registered.aggregate_type == "playergame"


def test_the_mastered_payload_states_the_value_it_sets():
    """One type states both directions."""
    validated = DEFAULT_EVENT_TYPES.validate(
        PLAYERGAME_MASTERED_CHANGED.event_type, {"mastered": False}
    )

    assert validated == {"mastered": False}


def test_a_mastered_payload_of_a_string_is_refused():
    """Strict validation takes no truthy string."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_MASTERED_CHANGED.event_type, {"mastered": "true"}
        )


def test_a_mastered_payload_stating_nothing_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYERGAME_MASTERED_CHANGED.event_type, {})


def test_the_mastered_payload_carries_no_reference():
    """The creation event holds the one reference."""
    assert (
        DEFAULT_EVENT_TYPES.reference_fields_for(
            PLAYERGAME_MASTERED_CHANGED.event_type
        )
        == {}
    )
```

Extend the import at the top of the same file:

```python
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_STATUS_CHANGED,
    StatusValue,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_events.py"`

Expected: FAIL at collection — `ImportError: cannot import name
'PLAYERGAME_MASTERED_CHANGED'`.

- [ ] **Step 3: Register the event**

Append to `games/events/playergame.py`:

```python
@with_config(STRICT_SCHEMA)
class PlayerGameMasteredChangedPayload(TypedDict):
    """Whether this library now masters the game."""

    mastered: bool


PLAYERGAME_MASTERED_CHANGED = EventSpec(
    "library.playergame.mastered_changed",
    aggregate_type="playergame",
    payload=PlayerGameMasteredChangedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_MASTERED_CHANGED)
```

The payload needs no `Literal`. `status` needs one because strict validation
refuses a plain string for an enum field; a bool is already the type a recorded
payload reads back as.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_events.py"`

Expected: PASS, all of them.

- [ ] **Step 5: Commit**

```bash
git add games/events/playergame.py tests/test_playergame_events.py
git commit -m "Record one event for a mastery change"
```

---

### Task 3: The handler

**Files:**
- Modify: `games/projectors/playergame.py` (a method and a `handles` entry)
- Test: `tests/test_playergame_projection.py` (append below the status tests)

**Interfaces:**
- Consumes: `PLAYERGAME_MASTERED_CHANGED` from Task 2; `PlayerGame.mastered`
  from Task 1.
- Produces: `PlayerGames._mastered_changed(self, event: RecordedEvent) -> None`,
  reached through `DEFAULT_REGISTRY.apply(event)`. Task 4 relies on it running
  on the append path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_projection.py`:

```python
def append_mastered(library, actor, identity, mastered, *, key="mastered"):
    """Append one mastery change, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [
                PLAYERGAME_MASTERED_CHANGED.new(
                    aggregate_id=identity,
                    payload={"mastered": mastered},
                )
            ],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


@pytest.mark.django_db(transaction=True)
def test_the_mastered_event_writes_the_flag(owned_user, owned_library, tracked_game):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)

    append_mastered(owned_library, owned_user, identity, True)

    assert PlayerGame.objects.get(pk=identity).mastered is True


@pytest.mark.django_db(transaction=True)
def test_the_mastered_event_states_the_way_back(
    owned_user, owned_library, tracked_game
):
    """One type, and the payload decides."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_mastered(owned_library, owned_user, identity, True)

    append_mastered(owned_library, owned_user, identity, False, key="undo")

    assert PlayerGame.objects.get(pk=identity).mastered is False


@pytest.mark.django_db(transaction=True)
def test_replaying_the_creation_event_again_keeps_a_later_mastery(
    owned_user, owned_library, tracked_game
):
    """A default is absent from DO UPDATE."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_mastered(owned_library, owned_user, identity, True)
    created = RecordedEvent.from_row(
        LibraryEvent.objects.get(event_type="library.playergame.created")
    )

    DEFAULT_REGISTRY.apply(created)

    assert PlayerGame.objects.get(pk=identity).mastered is True


@pytest.mark.django_db(transaction=True)
def test_replaying_the_mastered_event_costs_one_statement(
    owned_user, owned_library, tracked_game
):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_mastered(owned_library, owned_user, identity, True)
    event = RecordedEvent.from_row(
        LibraryEvent.objects.get(event_type="library.playergame.mastered_changed")
    )

    with CaptureQueriesContext(connection) as queries:
        DEFAULT_REGISTRY.apply(event)

    assert [query["sql"].split(maxsplit=1)[0] for query in queries] == ["UPDATE"]


@pytest.mark.django_db(transaction=True)
def test_a_replay_reproduces_the_mastery(owned_user, owned_library, tracked_game):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_mastered(owned_library, owned_user, identity, True)
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert PlayerGame.objects.get(pk=identity).mastered is True


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_the_mastery(owned_user, owned_library, tracked_game):
    """Replay parity over an amended row."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_mastered(owned_library, owned_user, identity, True)

    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    drift = [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [(0, 0, 0)]

    rebuilt = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert rebuilt.swapped is True
    assert PlayerGame.objects.get(pk=identity).mastered is True
```

Extend the import at the top of the same file:

```python
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_STATUS_CHANGED,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_projection.py -k 'mastered or mastery'"`

Expected: FAIL. The append raises, because no family handles the type and
`PlayerGames.handles` does not name it.

- [ ] **Step 3: Handle the event**

In `games/projectors/playergame.py`, add the method below `_status_changed` and
extend `handles`:

```python
    def _mastered_changed(self, event: RecordedEvent) -> None:
        #: From the payload, so replays agree.
        self.amend(PlayerGame, event.aggregate_id, mastered=event.payload["mastered"])

    handles: ClassVar[HandlerMap] = {
        PLAYERGAME_CREATED: _created,
        PLAYERGAME_STATUS_CHANGED: _status_changed,
        PLAYERGAME_MASTERED_CHANGED: _mastered_changed,
    }
```

Extend the module's import to name `PLAYERGAME_MASTERED_CHANGED`.

`amend()` and not `project()`: an event that changes one column knows nothing of
the others, and a missing row must raise `ProjectionRowMissing` rather than
write a part-row a rebuild cannot reproduce.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_projection.py"`

Expected: PASS, the whole file.

- [ ] **Step 5: Commit**

```bash
git add games/projectors/playergame.py tests/test_playergame_projection.py
git commit -m "Amend the row a mastery event names"
```

---

### Task 4: The command

**Files:**
- Modify: `games/events/dispatch.py:82` (one `CommandName` member)
- Modify: `games/commands/playergame.py` (lift the lookup, add the command)
- Test: `tests/test_playergame_command.py` (append below the status tests)

**Interfaces:**
- Consumes: `PLAYERGAME_MASTERED_CHANGED` from Task 2; the handler from Task 3.
- Produces: `SetPlayerGameMastered(game_id: uuid.UUID, mastered: bool)`, a frozen
  dataclass `Command` whose `command_name` is
  `CommandName.PLAYERGAME_SET_MASTERED` (`"library.playergame.set_mastered"`),
  and `_tracked_game(context: CommandContext, game_id: uuid.UUID) -> PlayerGame`
  at module level, which both commands in the module call. #677 dispatches the
  command; nothing in this issue does.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_command.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_mastering_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=True),
        actor=owned_user,
        library=owned_library,
        idempotency_key="master-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.mastered_changed")
    assert event.payload == {"mastered": True}
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert row.mastered is True


@pytest.mark.django_db(transaction=True)
def test_mastery_leaves_the_rest_of_the_row_alone(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="complete-outer-wilds",
    )
    before = PlayerGame.objects.get()

    dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=True),
        actor=owned_user,
        library=owned_library,
        idempotency_key="master-outer-wilds",
    )

    after = PlayerGame.objects.get()
    assert (after.pk, after.game_id, after.tracked_at, after.status) == (
        before.pk,
        before.game_id,
        before.tracked_at,
        PlayerGameStatus.COMPLETED,
    )


@pytest.mark.django_db(transaction=True)
def test_mastery_of_an_untracked_game_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameMastered(game_id=game.pk, mastered=True),
            actor=owned_user,
            library=owned_library,
            idempotency_key="master-untracked",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.mastered_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_mastery_of_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameMastered(game_id=shared_game.pk, mastered=True),
            actor=owned_user,
            library=owned_library,
            idempotency_key="master-theirs",
        )

    assert PlayerGame.objects.get().mastered is False


@pytest.mark.django_db(transaction=True)
def test_the_mastery_a_game_already_records_is_refused(owned_user, owned_library):
    """One convention for #906 to change."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            SetPlayerGameMastered(game_id=game.pk, mastered=False),
            actor=owned_user,
            library=owned_library,
            idempotency_key="unmaster-outer-wilds",
        )


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_mastery_change(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    command = SetPlayerGameMastered(game_id=game.pk, mastered=True)

    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="master"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="master"
    )

    assert (first.replayed, second.replayed) == (False, True)
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playergame.mastered_changed"
        ).count()
        == 1
    )
```

Extend the import at the top of the same file:

```python
from games.commands.playergame import (
    SetPlayerGameMastered,
    SetPlayerGameStatus,
    TrackGame,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_command.py"`

Expected: FAIL at collection — `ImportError: cannot import name
'SetPlayerGameMastered'`.

- [ ] **Step 3: Name the command**

In `games/events/dispatch.py`, add a member to `CommandName` below
`PLAYERGAME_SET_STATUS`:

```python
    PLAYERGAME_SET_MASTERED = "library.playergame.set_mastered"
```

- [ ] **Step 4: Lift the tracked-row lookup**

In `games/commands/playergame.py`, delete `SetPlayerGameStatus._tracked` and put
this at module level, below the imports and above `TrackGame`:

```python
def _tracked_game(context: CommandContext, game_id: uuid.UUID) -> PlayerGame:
    """The projection row, never the catalog."""
    try:
        return PlayerGame.objects.get(library=context.library, game_id=game_id)
    except PlayerGame.DoesNotExist:
        raise CommandRejected(
            f"This library tracks no game {game_id}. A recorded fact belongs "
            "to a tracked game, and #676 backfills one for every game a "
            "library has."
        ) from None
```

In `SetPlayerGameStatus.build`, call it:

```python
        tracked = _tracked_game(context, self.game_id)
```

The wording moves from "A status belongs" to "A recorded fact belongs", because
two commands now read the message. `tracks no game`, which two tests match,
does not move.

- [ ] **Step 5: Add the command**

Append to `games/commands/playergame.py`:

```python
@dataclass(frozen=True, slots=True)
class SetPlayerGameMastered(Command):
    """State whether this library mastered a tracked game."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_SET_MASTERED
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    mastered: bool

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.mastered == self.mastered:
            recorded = "mastered" if self.mastered else "not mastered"
            raise CommandRejected(
                f"This library already records game {self.game_id} as "
                f"{recorded}. Whether a repeat should instead succeed as a "
                "no-op is EV-23 (#906)."
            )
        return [
            PLAYERGAME_MASTERED_CHANGED.new(
                aggregate_id=tracked.pk,
                payload={"mastered": self.mastered},
            )
        ]
```

Extend the module's import from `games.events.playergame` to name
`PLAYERGAME_MASTERED_CHANGED`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_command.py tests/test_command_dispatch.py"`

Expected: PASS. `test_the_allowlist_holds_real_commands_only` stays green: the
new name does not start with `test.`.

- [ ] **Step 7: Commit**

```bash
git add games/commands/playergame.py games/events/dispatch.py tests/test_playergame_command.py
git commit -m "Add a command that sets mastery"
```

---

### Task 5: The gate and the record

**Files:**
- Modify: `CLAUDE.md` (the `PlayerGame` bullet under Models)
- Delete: `docs/superpowers/plans/2026-08-26-issue-673-playergame-mastered.md`

**Interfaces:**
- Consumes: every task above.
- Produces: nothing the code imports.

- [ ] **Step 1: Correct the model bullet**

`CLAUDE.md` says `PlayerGame` is "written only by the projector handling
`library.playergame.created`". Three event types write it now. Replace that
clause with "written only by the `PlayerGames` projector". Leave the rest of the
bullet as it is.

- [ ] **Step 2: Run the full gate**

Run: `make check`

Expected: green. Lint, format check, mypy, ts-check, vitest, and the whole
pytest suite including `e2e/`. A hand-picked subset is not the gate. If the
formatter rewraps a line, commit that with the rest.

- [ ] **Step 3: Delete this plan**

The spec stays; the plan does not outlive the work.

```bash
git rm docs/superpowers/plans/2026-08-26-issue-673-playergame-mastered.md
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Say which projector writes the tracked row"
```

---

## Verification

- `make check` green, which is the issue's acceptance gate.
- Idempotency: `test_one_idempotency_key_records_one_mastery_change` shows one
  key records one event; `test_replaying_the_creation_event_again_keeps_a_later_mastery`
  shows the creation event is safe to run again.
- Replay parity: `test_a_replay_reproduces_the_mastery` and
  `test_a_rebuild_reproduces_the_mastery`, the second asserting a `CHECK`
  rebuild finds no drift before it swaps.
- Migration evidence: `0030_playergame_mastered` is one `AddField` with a
  constant default and no data step.

## Reversibility

Nothing reads the column and nothing dispatches the command, so a revert is the
four commits plus `make migrate ARGS="games 0029_playergame_status"`. No
recorded event is lost by that: none exists until #677 wires a caller.

## Out of scope

No view, form or API calls the command. `Game.mastered` stays until #678 moves
the reads. #676 must record a `mastered_changed` event for each game a library
already mastered — the `False` default covers only rows no event touched.
