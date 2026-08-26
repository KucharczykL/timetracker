# PlayerGame exclude-from-unfinished Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A library records that a tracked game stays out of unfinished lists,
through a command and an event, projected onto a new
`PlayerGame.excluded_from_unfinished` column.

**Architecture:** This repeats the shape #673 gave `mastered`, with the same
plain `bool` payload. A constant `False` default covers every row no event
touched; one event type,
`library.playergame.excluded_from_unfinished_changed`, states both directions;
the handler amends the row by primary key;
`SetPlayerGameExcludedFromUnfinished` builds the event behind the stream-head
lock. Nothing reads the column: `Purchase.infinite` remains the one field the
unfinished statistics consult until the Purchase cutover.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pydantic (strict payload
validation), pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-issue-674-playergame-unfinished-exclusion-design.md`

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
- `make format` reformats Python inside Markdown fences too. If it rewrites
  this plan, revert the plan rather than the code, and note that Task 5 deletes
  the plan *before* the final gate runs.

---

### Task 1: The column and its migration

**Files:**
- Modify: `games/models.py:1332-1333` (the `PlayerGame` class, below `mastered`)
- Create: `games/migrations/0031_playergame_excluded_from_unfinished.py`
  (generated)
- Test: `tests/test_projection_model.py:243-246` (`PINNED_DEFAULTS`)
- Test: `tests/test_playergame_projection.py:59-61` (below the mastered default)

**Interfaces:**
- Consumes: nothing.
- Produces: `PlayerGame.excluded_from_unfinished`, a `BooleanField` that starts
  at `False`. Tasks 3 and 4 read and write it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_projection_model.py`, extend the pinned defaults:

```python
#: Every constant a projection column starts at.
PINNED_DEFAULTS: dict[str, dict[str, object]] = {
    "games.PlayerGame": {
        "status": "unplayed",
        "mastered": False,
        "excluded_from_unfinished": False,
    },
}
```

In `tests/test_playergame_projection.py`, add below
`test_a_tracked_game_starts_unmastered`:

```python
def test_a_tracked_game_starts_in_unfinished_lists():
    """The creation event states no exclusion."""
    assert PlayerGame().excluded_from_unfinished is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_projection_model.py tests/test_playergame_projection.py -k 'pinned or unfinished_lists'"`

Expected: FAIL. `test_a_tracked_game_starts_in_unfinished_lists` raises
`AttributeError: 'PlayerGame' object has no attribute
'excluded_from_unfinished'`, and `test_every_projection_default_is_pinned`
reports a dict without the key.

- [ ] **Step 3: Add the column**

In `games/models.py`, inside `PlayerGame`, below the `mastered` field:

```python
    #: An explicit preference, never inferred from status.
    excluded_from_unfinished = models.BooleanField(default=False)
```

- [ ] **Step 4: Generate the migration**

Run: `make makemigrations ARGS="games playergame_excluded_from_unfinished"`

Expected: `games/migrations/0031_playergame_excluded_from_unfinished.py`,
holding one `AddField` for `excluded_from_unfinished` with `default=False`. Read
it. It must add nothing else and must carry no `RunPython`: every existing row
is the projection of a stream that states nothing about the exclusion, and the
catalog holds no field to derive one from, so `False` is already correct for
each.

- [ ] **Step 5: Apply it and run the tests**

Run: `make migrate` then
`make test ARGS="tests/test_projection_model.py tests/test_playergame_projection.py"`

Expected: PASS, including `test_playergame_is_a_pure_projection` — a literal
default trips none of E004 to E007.

- [ ] **Step 6: Commit**

```bash
git add games/models.py games/migrations/0031_playergame_excluded_from_unfinished.py tests/test_projection_model.py tests/test_playergame_projection.py
git commit -m "Give a tracked game an exclusion column"
```

---

### Task 2: The event

**Files:**
- Modify: `games/events/playergame.py` (append below the mastered event)
- Test: `tests/test_playergame_events.py` (append below the mastered tests)

**Interfaces:**
- Consumes: `PlayerGame.excluded_from_unfinished` from Task 1 (in name only;
  nothing imports it here).
- Produces: `PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED`, an `EventSpec` whose
  `event_type` is `"library.playergame.excluded_from_unfinished_changed"`,
  `aggregate_type` is `"playergame"`, and payload is
  `PlayerGameExcludedFromUnfinishedChangedPayload`, a `TypedDict` with one key,
  `excluded_from_unfinished: bool`. Tasks 3 and 4 import it from
  `games.events.playergame`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_events.py`:

```python
def test_the_exclusion_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for(
        "library.playergame.excluded_from_unfinished_changed"
    )

    assert registered is PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED
    assert registered.aggregate_type == "playergame"


def test_the_exclusion_payload_states_the_value_it_sets():
    """One type states both directions."""
    validated = DEFAULT_EVENT_TYPES.validate(
        PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.event_type,
        {"excluded_from_unfinished": False},
    )

    assert validated == {"excluded_from_unfinished": False}


def test_an_exclusion_payload_of_a_string_is_refused():
    """Strict validation takes no truthy string."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.event_type,
            {"excluded_from_unfinished": "true"},
        )


def test_an_exclusion_payload_stating_nothing_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.event_type, {}
        )


def test_the_exclusion_payload_carries_no_reference():
    """The creation event holds the one reference."""
    assert (
        DEFAULT_EVENT_TYPES.reference_fields_for(
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.event_type
        )
        == {}
    )
```

Extend the import at the top of the same file:

```python
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_STATUS_CHANGED,
    StatusValue,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_events.py"`

Expected: FAIL at collection — `ImportError: cannot import name
'PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED'`.

- [ ] **Step 3: Register the event**

Append to `games/events/playergame.py`:

```python
@with_config(STRICT_SCHEMA)
class PlayerGameExcludedFromUnfinishedChangedPayload(TypedDict):
    """Whether this library keeps the game out of unfinished lists."""

    excluded_from_unfinished: bool


PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED = EventSpec(
    "library.playergame.excluded_from_unfinished_changed",
    aggregate_type="playergame",
    payload=PlayerGameExcludedFromUnfinishedChangedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED)
```

The payload needs no `Literal`, for the reason `mastered` needs none: strict
validation refuses a plain string for an enum field, and a bool is already the
type a recorded payload reads back as.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_events.py"`

Expected: PASS, all of them.

- [ ] **Step 5: Commit**

```bash
git add games/events/playergame.py tests/test_playergame_events.py
git commit -m "Record one event for an exclusion change"
```

---

### Task 3: The handler

**Files:**
- Modify: `games/projectors/playergame.py` (a method and a `handles` entry)
- Test: `tests/test_playergame_projection.py` (append below the mastered tests)

**Interfaces:**
- Consumes: `PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED` from Task 2;
  `PlayerGame.excluded_from_unfinished` from Task 1.
- Produces: `PlayerGames._excluded_from_unfinished_changed(self, event:
  RecordedEvent) -> None`, reached through `DEFAULT_REGISTRY.apply(event)`. Task
  4 relies on it running on the append path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_projection.py`:

```python
def append_excluded(library, actor, identity, excluded, *, key="exclude"):
    """Append one exclusion change, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [
                PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.new(
                    aggregate_id=identity,
                    payload={"excluded_from_unfinished": excluded},
                )
            ],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


@pytest.mark.django_db(transaction=True)
def test_the_exclusion_event_writes_the_flag(owned_user, owned_library, tracked_game):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)

    append_excluded(owned_library, owned_user, identity, True)

    assert PlayerGame.objects.get(pk=identity).excluded_from_unfinished is True


@pytest.mark.django_db(transaction=True)
def test_the_exclusion_event_states_the_way_back(
    owned_user, owned_library, tracked_game
):
    """One type, and the payload decides."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_excluded(owned_library, owned_user, identity, True)

    append_excluded(owned_library, owned_user, identity, False, key="undo")

    assert PlayerGame.objects.get(pk=identity).excluded_from_unfinished is False


@pytest.mark.django_db(transaction=True)
def test_replaying_the_creation_event_again_keeps_a_later_exclusion(
    owned_user, owned_library, tracked_game
):
    """A default is absent from DO UPDATE."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_excluded(owned_library, owned_user, identity, True)
    created = RecordedEvent.from_row(
        LibraryEvent.objects.get(event_type="library.playergame.created")
    )

    DEFAULT_REGISTRY.apply(created)

    assert PlayerGame.objects.get(pk=identity).excluded_from_unfinished is True


@pytest.mark.django_db(transaction=True)
def test_replaying_the_exclusion_event_costs_one_statement(
    owned_user, owned_library, tracked_game
):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_excluded(owned_library, owned_user, identity, True)
    event = RecordedEvent.from_row(
        LibraryEvent.objects.get(
            event_type="library.playergame.excluded_from_unfinished_changed"
        )
    )

    with CaptureQueriesContext(connection) as queries:
        DEFAULT_REGISTRY.apply(event)

    assert [query["sql"].split(maxsplit=1)[0] for query in queries] == ["UPDATE"]


@pytest.mark.django_db(transaction=True)
def test_a_replay_reproduces_the_exclusion(owned_user, owned_library, tracked_game):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_excluded(owned_library, owned_user, identity, True)
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert PlayerGame.objects.get(pk=identity).excluded_from_unfinished is True


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_the_exclusion(owned_user, owned_library, tracked_game):
    """Replay parity over an amended row."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_excluded(owned_library, owned_user, identity, True)

    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    drift = [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [(0, 0, 0)]

    rebuilt = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert rebuilt.swapped is True
    assert PlayerGame.objects.get(pk=identity).excluded_from_unfinished is True
```

Extend the import at the top of the same file:

```python
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_STATUS_CHANGED,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_projection.py -k exclusion"`

Expected: FAIL. The append raises, because no family handles the type and
`PlayerGames.handles` does not name it.

- [ ] **Step 3: Handle the event**

In `games/projectors/playergame.py`, add the method below `_mastered_changed`
and extend `handles`. The whole class body from `_mastered_changed` down reads:

```python
    def _mastered_changed(self, event: RecordedEvent) -> None:
        #: From the payload, so replays agree.
        self.amend(PlayerGame, event.aggregate_id, mastered=event.payload["mastered"])

    def _excluded_from_unfinished_changed(self, event: RecordedEvent) -> None:
        #: From the payload, so replays agree.
        self.amend(
            PlayerGame,
            event.aggregate_id,
            excluded_from_unfinished=event.payload["excluded_from_unfinished"],
        )

    handles: ClassVar[HandlerMap] = {
        PLAYERGAME_CREATED: _created,
        PLAYERGAME_STATUS_CHANGED: _status_changed,
        PLAYERGAME_MASTERED_CHANGED: _mastered_changed,
        PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED: _excluded_from_unfinished_changed,
    }
```

Extend the module's import from `games.events.playergame` to name
`PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED`.

`amend()` and not `project()`: an event that changes one column knows nothing of
the others, and a missing row must raise `ProjectionRowMissing` rather than
write a part-row a rebuild cannot reproduce.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_projection.py"`

Expected: PASS, the whole file.

- [ ] **Step 5: Commit**

```bash
git add games/projectors/playergame.py tests/test_playergame_projection.py
git commit -m "Amend the row an exclusion event names"
```

---

### Task 4: The command

**Files:**
- Modify: `games/events/dispatch.py:82` (one `CommandName` member)
- Modify: `games/commands/playergame.py` (append the command)
- Test: `tests/test_playergame_command.py` (append below the mastered tests)

**Interfaces:**
- Consumes: `PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED` from Task 2; the
  handler from Task 3; the module-level `_tracked_game(context: CommandContext,
  game_id: uuid.UUID) -> PlayerGame` that #673 already lifted out of
  `SetPlayerGameStatus`.
- Produces: `SetPlayerGameExcludedFromUnfinished(game_id: uuid.UUID,
  excluded_from_unfinished: bool)`, a frozen dataclass `Command` whose
  `command_name` is `CommandName.PLAYERGAME_SET_EXCLUDED_FROM_UNFINISHED`
  (`"library.playergame.set_excluded_from_unfinished"`). #677 dispatches it;
  nothing in this issue does.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_command.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_excluding_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        SetPlayerGameExcludedFromUnfinished(
            game_id=game.pk, excluded_from_unfinished=True
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="exclude-outer-wilds",
    )

    event = LibraryEvent.objects.get(
        event_type="library.playergame.excluded_from_unfinished_changed"
    )
    assert event.payload == {"excluded_from_unfinished": True}
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert row.excluded_from_unfinished is True


@pytest.mark.django_db(transaction=True)
def test_an_exclusion_leaves_the_rest_of_the_row_alone(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=True),
        actor=owned_user,
        library=owned_library,
        idempotency_key="master-outer-wilds",
    )
    before = PlayerGame.objects.get()

    dispatch(
        SetPlayerGameExcludedFromUnfinished(
            game_id=game.pk, excluded_from_unfinished=True
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="exclude-outer-wilds",
    )

    after = PlayerGame.objects.get()
    assert (after.pk, after.game_id, after.tracked_at, after.status) == (
        before.pk,
        before.game_id,
        before.tracked_at,
        before.status,
    )
    assert after.mastered is True


@pytest.mark.django_db(transaction=True)
def test_excluding_an_untracked_game_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameExcludedFromUnfinished(
                game_id=game.pk, excluded_from_unfinished=True
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="exclude-untracked",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.excluded_from_unfinished_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_excluding_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameExcludedFromUnfinished(
                game_id=shared_game.pk, excluded_from_unfinished=True
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="exclude-theirs",
        )

    assert PlayerGame.objects.get().excluded_from_unfinished is False


@pytest.mark.django_db(transaction=True)
def test_the_exclusion_a_game_already_records_is_refused(owned_user, owned_library):
    """One convention for #906 to change."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            SetPlayerGameExcludedFromUnfinished(
                game_id=game.pk, excluded_from_unfinished=False
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="include-outer-wilds",
        )


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_exclusion_change(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    command = SetPlayerGameExcludedFromUnfinished(
        game_id=game.pk, excluded_from_unfinished=True
    )

    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="exclude"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="exclude"
    )

    assert (first.replayed, second.replayed) == (False, True)
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playergame.excluded_from_unfinished_changed"
        ).count()
        == 1
    )
```

Extend the import at the top of the same file:

```python
from games.commands.playergame import (
    SetPlayerGameExcludedFromUnfinished,
    SetPlayerGameMastered,
    SetPlayerGameStatus,
    TrackGame,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_command.py"`

Expected: FAIL at collection — `ImportError: cannot import name
'SetPlayerGameExcludedFromUnfinished'`.

- [ ] **Step 3: Name the command**

In `games/events/dispatch.py`, add a member to `CommandName` below
`PLAYERGAME_SET_MASTERED`:

```python
    PLAYERGAME_SET_EXCLUDED_FROM_UNFINISHED = (
        "library.playergame.set_excluded_from_unfinished"
    )
```

The parentheses are what `ruff format` produces: the one-line form is 95
columns, and the formatter cannot split a string.

- [ ] **Step 4: Add the command**

Append to `games/commands/playergame.py`:

```python
@dataclass(frozen=True, slots=True)
class SetPlayerGameExcludedFromUnfinished(Command):
    """Keep a tracked game out of unfinished lists, or put it back."""

    command_name: ClassVar[CommandName] = (
        CommandName.PLAYERGAME_SET_EXCLUDED_FROM_UNFINISHED
    )
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    excluded_from_unfinished: bool

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.excluded_from_unfinished == self.excluded_from_unfinished:
            recorded = (
                "excluded from" if self.excluded_from_unfinished else "included in"
            )
            raise CommandRejected(
                f"This library already records game {self.game_id} as "
                f"{recorded} unfinished lists. Whether a repeat should instead "
                "succeed as a no-op is EV-23 (#906)."
            )
        return [
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.new(
                aggregate_id=tracked.pk,
                payload={"excluded_from_unfinished": self.excluded_from_unfinished},
            )
        ]
```

Extend the module's import from `games.events.playergame` to name
`PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED`. `_tracked_game` is already at
module level: call it, do not add a private method.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_command.py tests/test_command_dispatch.py"`

Expected: PASS. `test_the_allowlist_holds_real_commands_only` stays green: the
new name does not start with `test.`.

- [ ] **Step 6: Commit**

```bash
git add games/commands/playergame.py games/events/dispatch.py tests/test_playergame_command.py
git commit -m "Add a command that excludes from unfinished"
```

---

### Task 5: The gate and the record

**Files:**
- Delete: `docs/superpowers/plans/2026-08-26-issue-674-playergame-unfinished-exclusion.md`

**Interfaces:**
- Consumes: every task above.
- Produces: nothing the code imports.

`CLAUDE.md` needs no edit this time: #673 already changed the `PlayerGame`
bullet to say the row is "written only by the `PlayerGames` projector", which
stays true with a fourth event type. `docs/STATUSES.md` also stays as it is: it
describes the purchase-based unfinished list, and no read changes here.

- [ ] **Step 1: Delete this plan**

The spec stays; the plan does not outlive the work. Delete it *before* the gate,
so `format-check` never sees the Python in these fences.

```bash
git rm docs/superpowers/plans/2026-08-26-issue-674-playergame-unfinished-exclusion.md
```

- [ ] **Step 2: Run the full gate**

Run: `make check`

Expected: green. Lint, format check, mypy, ts-check, vitest, and the whole
pytest suite including `e2e/`. A hand-picked subset is not the gate. If the
formatter rewraps a line, commit that with the rest.

- [ ] **Step 3: Commit**

```bash
git commit -m "Retire the plan for the exclusion column"
```

---

## Verification

- `make check` green, which is the issue's acceptance gate.
- Idempotency: `test_one_idempotency_key_records_one_exclusion_change` shows one
  key records one event;
  `test_replaying_the_creation_event_again_keeps_a_later_exclusion` shows the
  creation event is safe to run again.
- Replay parity: `test_a_replay_reproduces_the_exclusion` and
  `test_a_rebuild_reproduces_the_exclusion`, the second asserting a `CHECK`
  rebuild finds no drift before it swaps.
- Migration evidence: `0031_playergame_excluded_from_unfinished` is one
  `AddField` with a constant default and no data step.
- User isolation: `test_excluding_a_game_another_library_tracks_is_refused`
  shows one library cannot set the preference on another library's row.

## Reversibility

Nothing reads the column and nothing dispatches the command, so a revert is the
four commits plus `make migrate ARGS="games 0030_playergame_mastered"`. No
recorded event is lost by that: none exists until #677 wires a caller.

## Out of scope

No view, form or API calls the command, and no filter, saved preset, statistic
or API reads the column. `Purchase.infinite` stays the one field the unfinished
and dropped statistics consult; the charter moves that fact at the Purchase
cutover, with the preflight list of mixed-purchase games. #676 therefore
backfills no exclusion event — unlike `status` and `mastered`, the catalog holds
nothing to back one with. #677 switches the writes, and #678 moves the reads.
