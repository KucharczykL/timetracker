# PlayerGame status behind commands and events — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A library sets the status of a game it tracks through a command, which records one event that a projector folds onto the `PlayerGame` row.

**Architecture:** `PlayerGame` gains a `status` column with a constant model default. A new `library.playergame.status_changed` event carries the new status. `SetPlayerGameStatus` resolves the tracked row under the stream-head lock and emits one event. The `PlayerGames` projector folds it through a new `Projector.amend()`, which updates a subset of a row an earlier event created.

**Tech Stack:** Django 6, PostgreSQL 18, pydantic (payload schemas), pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-issue-672-playergame-status-design.md`

## Global Constraints

- Python 3.14. Run everything through `make`; never `uv run` or `pytest` directly.
- Iterate with `make check-fast`; the gate is the full `make check`.
- Never write a `GeneratedField`.
- A projection column an event states carries no default; a column no event states carries a **constant** model default.
- Event payload schemas are `TypedDict` with `@with_config(STRICT_SCHEMA)`.
- Name variables with complete words.
- Comments are written normally now; the docs sweep trims them to 7 words after the work is green.

---

### Task 1: `Projector.amend()`

**Files:**
- Modify: `games/events/projection.py`
- Test: `tests/test_event_projectors.py`

**Interfaces:**
- Consumes: `Projector`, `ProjectorRegistry`, `ProjectorFamily`, `RecordedEvent`, `ProjectionTarget` (all existing).
- Produces: `Projector.amend(model, identity, **columns) -> None` and `ProjectionRowMissing(LookupError)`, both from `games.events.projection`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_event_projectors.py`, after `test_the_helper_refuses_a_row_it_was_not_given_whole`:

```python
amend_registry = ProjectorRegistry()


class AmendingWriter(Projector, registry=amend_registry):
    """Changes one column of a row that exists."""

    family_name = ProjectorFamily.CURRENT_STATE

    def _recorded(self, event: RecordedEvent) -> None:
        #: Device stands in for a projection table.
        self.amend(  # type: ignore[type-var]
            Device,
            event.aggregate_id,
            name=f"amended {event.sequence}",
        )

    handles: ClassVar[HandlerMap] = {PROBE_RECORDED: _recorded}


@pytest.mark.django_db
def test_an_amendment_changes_the_columns_it_names(owned_library):
    identity = uuid.uuid7()
    Device.objects.create(
        pk=identity, library_id=owned_library.pk, name="created", type=Device.UNKNOWN
    )

    amend_registry.apply(
        make_event(library_id=owned_library.pk, aggregate_id=identity)
    )

    row = Device.objects.get(pk=identity)
    assert (row.name, row.type) == ("amended 1", Device.UNKNOWN)


@pytest.mark.django_db
def test_an_amendment_costs_one_statement(owned_library):
    identity = uuid.uuid7()
    Device.objects.create(
        pk=identity, library_id=owned_library.pk, name="created", type=Device.UNKNOWN
    )

    with CaptureQueriesContext(connection) as queries:
        amend_registry.apply(
            make_event(library_id=owned_library.pk, aggregate_id=identity)
        )

    assert [query["sql"].split(maxsplit=1)[0] for query in queries] == ["UPDATE"]


@pytest.mark.django_db
def test_an_amendment_writes_through_the_target_its_family_holds(owned_library):
    identity = uuid.uuid7()
    Device.objects.create(
        pk=identity, library_id=owned_library.pk, name="created", type=Device.UNKNOWN
    )
    target = RecordingTarget()

    amend_registry.for_target(target).apply(
        make_event(library_id=owned_library.pk, aggregate_id=identity)
    )

    assert target.asked == ["Device"]


@pytest.mark.django_db
def test_an_amendment_with_no_row_is_refused(owned_library):
    """Out of order, or a stream missing its creation event."""
    with pytest.raises(ProjectionRowMissing, match="no row"):
        amend_registry.apply(make_event(library_id=owned_library.pk))

    assert Device.objects.count() == 0
```

Add `ProjectionRowMissing` to the existing `from games.events.projection import (...)` block at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_event_projectors.py -k amend"`
Expected: FAIL — `ImportError: cannot import name 'ProjectionRowMissing'`.

- [ ] **Step 3: Implement `amend()`**

In `games/events/projection.py`, add the exception after the `type ColumnNames = ...` aliases:

```python
class ProjectionRowMissing(LookupError):
    """Raised for an amendment with no row to change."""
```

Add the method to `Projector`, directly after `project()`:

```python
    def amend[M: ProjectionModel](
        self, model: type[M], identity: uuid.UUID, **columns: Any
    ) -> None:
        """Change part of a row an earlier event created.

        `project()` cannot serve this: an event that changes one column knows
        nothing of the columns the creation event wrote, and a whole-row write
        would need to read them back. One `UPDATE`, no read.

        A missing row is refused rather than inserted. A replay folds a stream
        in sequence order, so the creation event has already written the row;
        zero rows matched means the stream is broken, and an insert here would
        write a part-row a rebuild could not reproduce.
        """
        #: Never the imported model: a rebuild redirects.
        projected = self.target.model(model)
        changed = projected._default_manager.filter(pk=identity).update(**columns)
        if changed != 1:
            raise ProjectionRowMissing(
                f"{model.__qualname__} has no row {identity} to amend. An "
                "event that changes part of a row is folded after the event "
                "that created it, so a missing row is a broken stream rather "
                "than a first write."
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_event_projectors.py"`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add games/events/projection.py tests/test_event_projectors.py
git commit -m "Let a fold change part of a row"
```

---

### Task 2: E007 — a projection default must be a constant

**Files:**
- Modify: `games/checks.py:130-200` (`_check_field`)
- Test: `tests/test_projection_model.py`

**Interfaces:**
- Consumes: `check_projection_models`, `ProjectionModel` (existing).
- Produces: check id `games.E007`. E005 and E006 keep their ids and messages for the two factory families they already name.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_projection_model.py`:

```python
@isolate_apps("games")
def test_a_constant_default_is_allowed():
    """A rebuild reproduces a constant."""

    class Started(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        status = models.CharField(max_length=9, default="unplayed")
        mastered = models.BooleanField(default=False)
        archived_at = models.DateTimeField(null=True, default=None)

        class Meta:
            app_label = "games"

    assert check(Started) == []


@isolate_apps("games")
def test_a_callable_default_is_refused():
    """E005 and E006 name two factories; this catches the rest."""

    class Counted(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        tags = models.JSONField(default=list)

        class Meta:
            app_label = "games"

    assert check(Counted) == ["games.E007"]


@isolate_apps("games")
def test_a_wrapped_clock_default_is_refused():
    """The hole E006's own hint admits to."""

    def when() -> datetime.datetime:
        return timezone.now()

    class Wrapped(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        seen_at = models.DateTimeField(default=when)

        class Meta:
            app_label = "games"

    assert check(Wrapped) == ["games.E007"]
```

Add `import datetime` to the file's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_projection_model.py"`
Expected: FAIL — `test_a_callable_default_is_refused` and `test_a_wrapped_clock_default_is_refused` get `[]` instead of `["games.E007"]`.

- [ ] **Step 3: Restructure the default checks**

In `games/checks.py`, replace the two trailing blocks of `_check_field` (the E005 block beginning `if callable(field.default) and field.default in _UUID_FACTORIES:` and the E006 block after it) with one branch:

```python
    if field.has_default() and callable(field.default):
        #: has_default() first: NOT_PROVIDED is a class, therefore callable.
        if field.default in _UUID_FACTORIES:
            errors.append(
                Error(
                    f"{where} defaults to a freshly minted UUID.",
                    hint=(
                        "A projection key comes from the event — its aggregate_id "
                        "or correlation_id, or a uuid5 over them — so that a "
                        "rebuild produces the identity it produced last time."
                    ),
                    obj=model,
                    id="games.E005",
                )
            )
        elif field.default in _CLOCK_FACTORIES:
            errors.append(
                Error(
                    f"{where} defaults to the clock.",
                    hint=(
                        "A rebuild evaluates the default again, at rebuild time, "
                        "so every row differs from the live one. A projected "
                        "timestamp comes from the event — recorded_at or "
                        "effective_time."
                    ),
                    obj=model,
                    id="games.E006",
                )
            )
        else:
            errors.append(
                Error(
                    f"{where} defaults to a callable.",
                    hint=(
                        "A projection column no event states carries a constant, "
                        "which a rebuild reproduces. A callable is evaluated "
                        "again at rebuild time. E005 and E006 name the two "
                        "factory families by identity; this refuses the rest, "
                        "including a wrapper around one of them."
                    ),
                    obj=model,
                    id="games.E007",
                )
            )
    return errors
```

Delete the sentence "This check knows the standard factories only; a wrapper around one of them is still a rebuild that cannot reproduce itself." from E006's hint — E007 now catches that case.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_projection_model.py"`
Expected: PASS, whole file — including the existing E005 and E006 tests.

- [ ] **Step 5: Commit**

```bash
git add games/checks.py tests/test_projection_model.py
git commit -m "Refuse a projection default the clock could move"
```

---

### Task 3: The status column

**Files:**
- Modify: `games/models.py:1291-1319` (`PlayerGame`)
- Create: `games/migrations/0029_playergame_status.py` (generated)
- Test: `tests/test_projection_model.py`, `tests/test_playergame_projection.py`

**Interfaces:**
- Produces: `games.models.PlayerGameStatus` (a `models.TextChoices` with members `UNPLAYED`, `PLAYED`, `COMPLETED`, `RETIRED`, `SHELVED`, `ABANDONED` and values `"unplayed"`, `"played"`, `"completed"`, `"retired"`, `"shelved"`, `"abandoned"`), and `PlayerGame.status`, a `CharField(max_length=9, choices=PlayerGameStatus, default=PlayerGameStatus.UNPLAYED)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_projection_model.py`:

```python
#: Every constant a projection column starts at. A rebuild reproduces these,
#: so an edit here rewrites rows no event has touched.
PINNED_DEFAULTS: dict[str, dict[str, object]] = {
    "games.PlayerGame": {"status": "unplayed"},
}


def test_every_projection_default_is_pinned():
    found = {
        model._meta.label: {
            field.name: field.default
            for field in model._meta.concrete_fields
            if field.has_default()
        }
        for model in global_apps.get_models()
        if issubclass(model, ProjectionModel) and model._meta.managed
    }

    assert found == PINNED_DEFAULTS
```

Add `from django.apps import apps as global_apps` to the imports.

Append to `tests/test_playergame_projection.py`:

```python
def test_a_tracked_game_starts_unplayed():
    """The creation event states no status."""
    assert PlayerGame().status == PlayerGameStatus.UNPLAYED
```

Add `PlayerGameStatus` to the existing `from games.models import ...` line.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_projection_model.py::test_every_projection_default_is_pinned tests/test_playergame_projection.py::test_a_tracked_game_starts_unplayed"`
Expected: FAIL — `ImportError: cannot import name 'PlayerGameStatus'`.

- [ ] **Step 3: Add the enum and the column**

In `games/models.py`, directly above `class PlayerGame(ProjectionModel):`:

```python
class PlayerGameStatus(models.TextChoices):
    """What a library says about a game it tracks.

    The charter's six, not the five of `Game.Status`: a recorded payload
    cannot be upcast, so an event recording `f` would mean Completed forever.
    """

    UNPLAYED = "unplayed", "Unplayed"
    PLAYED = "played", "Played"
    COMPLETED = "completed", "Completed"
    RETIRED = "retired", "Retired"
    SHELVED = "shelved", "Shelved"
    ABANDONED = "abandoned", "Abandoned"
```

Inside `PlayerGame`, after `tracked_at`:

```python
    #: No event states it at creation, so it carries a constant.
    status = models.CharField(
        max_length=9,
        choices=PlayerGameStatus,
        default=PlayerGameStatus.UNPLAYED,
    )
```

- [ ] **Step 4: Generate the migration**

Run: `make makemigrations ARGS="games"`
Expected: writes `games/migrations/0029_playergame_status.py` with one `AddField`. Read it and confirm it holds `default=PlayerGameStatus.UNPLAYED` (or the literal `"unplayed"`) and no `db_default`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_projection_model.py tests/test_playergame_projection.py"`
Expected: PASS, both files. `test_playergame_is_a_pure_projection` must stay green — it asserts no check complains about `PlayerGame`, which is what proves E007 accepts the constant.

- [ ] **Step 6: Commit**

```bash
git add games/models.py games/migrations/0029_playergame_status.py \
        tests/test_projection_model.py tests/test_playergame_projection.py
git commit -m "Give a tracked game a status to start from"
```

---

### Task 4: The event

**Files:**
- Modify: `games/events/playergame.py`
- Test: `tests/test_playergame_events.py`

**Interfaces:**
- Consumes: `PlayerGameStatus` (Task 3).
- Produces: `games.events.playergame.PLAYERGAME_STATUS_CHANGED`, an `EventSpec` over `PlayerGameStatusChangedPayload`, event type `"library.playergame.status_changed"`, aggregate type `"playergame"`. The payload has one key, `status`, typed `StatusValue` — a PEP 695 alias for `Literal["unplayed", "played", "completed", "retired", "shelved", "abandoned"]`, exported from the same module so Task 5's `cast` has a name.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_events.py`:

```python
def test_the_status_payload_names_every_status():
    """The Literal and the choices are one vocabulary."""
    #: __value__ reads through the PEP 695 alias.
    assert sorted(get_args(StatusValue.__value__)) == sorted(PlayerGameStatus.values)


def test_a_recorded_status_validates_as_the_plain_string_it_is_read_back_as():
    """Strict pydantic refuses an enum member's value for an enum field."""
    validated = DEFAULT_EVENT_TYPES.validate(
        PLAYERGAME_STATUS_CHANGED.event_type, {"status": "completed"}
    )

    assert validated == {"status": "completed"}


def test_an_unknown_status_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PLAYERGAME_STATUS_CHANGED.event_type, {"status": "finished"}
        )


def test_the_status_payload_carries_no_reference():
    """The creation event holds this aggregate's one reference."""
    assert (
        DEFAULT_EVENT_TYPES.reference_fields_for(
            PLAYERGAME_STATUS_CHANGED.event_type
        )
        == {}
    )
```

Add to the imports: `from typing import get_args`, `import pytest`, `from games.events.playergame import PLAYERGAME_STATUS_CHANGED, StatusValue`, `from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid`, `from games.models import PlayerGameStatus` — keeping whatever the file already imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_events.py"`
Expected: FAIL — `ImportError: cannot import name 'PLAYERGAME_STATUS_CHANGED'`.

- [ ] **Step 3: Declare the event**

Append to `games/events/playergame.py`:

```python
#: A Literal, not PlayerGameStatus: strict pydantic refuses a plain string for
#: an enum field, and a recorded payload is read back as one. A test pins these
#: arguments equal to PlayerGameStatus.values.
type StatusValue = Literal[
    "unplayed", "played", "completed", "retired", "shelved", "abandoned"
]


@with_config(STRICT_SCHEMA)
class PlayerGameStatusChangedPayload(TypedDict):
    """The status this library now gives the game."""

    status: StatusValue


PLAYERGAME_STATUS_CHANGED = EventSpec(
    "library.playergame.status_changed",
    aggregate_type="playergame",
    payload=PlayerGameStatusChangedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_STATUS_CHANGED)
```

Add `Literal` to the `from typing import ...` line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_events.py"`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add games/events/playergame.py tests/test_playergame_events.py
git commit -m "Name the fact that a status changed"
```

---

### Task 5: The command

**Files:**
- Modify: `games/events/dispatch.py:78` (`CommandName`)
- Modify: `games/commands/playergame.py`
- Test: `tests/test_playergame_command.py`

**Interfaces:**
- Consumes: `PLAYERGAME_STATUS_CHANGED` (Task 4), `PlayerGameStatus` (Task 3), `Command`, `CommandContext`, `CommandRejected` (existing).
- Produces: `games.commands.playergame.SetPlayerGameStatus(game_id: uuid.UUID, status: PlayerGameStatus)`, named `CommandName.PLAYERGAME_SET_STATUS = "library.playergame.set_status"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_command.py`:

```python
def track(user, library, game):
    dispatch(
        TrackGame(game_id=game.pk),
        actor=user,
        library=library,
        idempotency_key=f"track-{game.pk}",
    )


@pytest.mark.django_db(transaction=True)
def test_setting_a_status_records_it_and_folds_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="complete-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.status_changed")
    assert event.payload == {"status": "completed"}
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert row.status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_a_status_leaves_the_rest_of_the_row_alone(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    before = PlayerGame.objects.get()

    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.PLAYED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="play-outer-wilds",
    )

    after = PlayerGame.objects.get()
    assert (after.pk, after.game_id, after.tracked_at) == (
        before.pk,
        before.game_id,
        before.tracked_at,
    )


@pytest.mark.django_db(transaction=True)
def test_an_untracked_game_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.PLAYED),
            actor=owned_user,
            library=owned_library,
            idempotency_key="play-untracked",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.status_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameStatus(
                game_id=shared_game.pk, status=PlayerGameStatus.PLAYED
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="play-theirs",
        )

    assert PlayerGame.objects.get().status == PlayerGameStatus.UNPLAYED


@pytest.mark.django_db(transaction=True)
def test_the_status_a_game_already_has_is_refused(owned_user, owned_library):
    """One convention for #906 to change in one place."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.UNPLAYED),
            actor=owned_user,
            library=owned_library,
            idempotency_key="unplay-outer-wilds",
        )


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_status_change(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    command = SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED)

    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="complete"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="complete"
    )

    assert (first.replayed, second.replayed) == (False, True)
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playergame.status_changed"
        ).count()
        == 1
    )
```

Add `SetPlayerGameStatus` to the `from games.commands.playergame import ...` line and `PlayerGameStatus` to the `from games.models import ...` line.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_command.py"`
Expected: FAIL — `ImportError: cannot import name 'SetPlayerGameStatus'`.

- [ ] **Step 3: Add the command name**

In `games/events/dispatch.py`, in `class CommandName`, after `PLAYERGAME_TRACK`:

```python
    PLAYERGAME_SET_STATUS = "library.playergame.set_status"
```

- [ ] **Step 4: Write the command**

Append to `games/commands/playergame.py`:

```python
@dataclass(frozen=True, slots=True)
class SetPlayerGameStatus(Command):
    """Give a game this library tracks a new status."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_SET_STATUS
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    #: A TextChoices member is a str, so json canonicalizes it as its value.
    status: PlayerGameStatus

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = self._tracked(context)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.status == self.status:
            raise CommandRejected(
                f"This library already gives game {self.game_id} the status "
                f"{self.status.value!r}. Whether a repeat should instead "
                "succeed as a no-op is EV-23 (#906)."
            )
        return [
            PLAYERGAME_STATUS_CHANGED.new(
                aggregate_id=tracked.pk,
                #: The Literal and the choices are pinned equal by a test.
                payload={"status": cast("StatusValue", self.status.value)},
            )
        ]

    def _tracked(self, context: CommandContext) -> PlayerGame:
        """The projection row, never the catalog.

        A library that tracks a game may set its status, whatever became of
        the catalog row. A game of another library resolves to nothing here,
        so the refusal tells the caller nothing about it.
        """
        try:
            return PlayerGame.objects.get(
                library=context.library, game_id=self.game_id
            )
        except PlayerGame.DoesNotExist:
            raise CommandRejected(
                f"This library tracks no game {self.game_id}. A status "
                "belongs to a tracked game, and #676 backfills one for every "
                "game a library has."
            ) from None
```

Add to the imports of that module: `from typing import ClassVar, cast`, `from games.events.playergame import PLAYERGAME_CREATED, PLAYERGAME_STATUS_CHANGED, StatusValue`, and `from games.models import Game, PlayerGame, PlayerGameStatus`. `StatusValue` is Task 4's alias; the `cast` to it is the one place the enum's `str` value meets the payload's `Literal`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_command.py tests/test_playergame_events.py"`
Expected: PASS, both files.

- [ ] **Step 6: Type check**

Run: `make typecheck`
Expected: clean. The `cast` is the one place the enum's `str` value meets the payload's `Literal`.

- [ ] **Step 7: Commit**

```bash
git add games/events/dispatch.py games/events/playergame.py \
        games/commands/playergame.py tests/test_playergame_command.py
git commit -m "Let a library say a game's status changed"
```

---

### Task 6: The fold, and its parity

**Files:**
- Modify: `games/projectors/playergame.py`
- Test: `tests/test_playergame_projection.py`

**Interfaces:**
- Consumes: `Projector.amend()` (Task 1), `PLAYERGAME_STATUS_CHANGED` (Task 4), `SetPlayerGameStatus` (Task 5).
- Produces: nothing new; `PlayerGames.handles` gains the new spec.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_projection.py`:

```python
def append_status(library, actor, identity, status, *, key="status"):
    """Append one status change, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [
                PLAYERGAME_STATUS_CHANGED.new(
                    aggregate_id=identity,
                    payload={"status": status},
                )
            ],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


@pytest.mark.django_db(transaction=True)
def test_the_status_event_writes_the_status(owned_user, owned_library, tracked_game):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)

    append_status(owned_library, owned_user, identity, "completed")

    assert PlayerGame.objects.get(pk=identity).status == "completed"


@pytest.mark.django_db(transaction=True)
def test_folding_the_creation_event_again_keeps_a_later_status(
    owned_user, owned_library, tracked_game
):
    """The default keeps status out of DO UPDATE."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_status(owned_library, owned_user, identity, "completed")
    created = RecordedEvent.from_row(
        LibraryEvent.objects.get(event_type="library.playergame.created")
    )

    DEFAULT_REGISTRY.apply(created)

    assert PlayerGame.objects.get(pk=identity).status == "completed"


@pytest.mark.django_db(transaction=True)
def test_folding_the_status_event_costs_one_statement(
    owned_user, owned_library, tracked_game
):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_status(owned_library, owned_user, identity, "completed")
    event = RecordedEvent.from_row(
        LibraryEvent.objects.get(event_type="library.playergame.status_changed")
    )

    with transaction.atomic(), CaptureQueriesContext(connection) as queries:
        DEFAULT_REGISTRY.apply(event)

    assert [query["sql"].split(maxsplit=1)[0] for query in queries] == ["UPDATE"]


@pytest.mark.django_db(transaction=True)
def test_a_replay_reproduces_the_status(owned_user, owned_library, tracked_game):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_status(owned_library, owned_user, identity, "completed")
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert PlayerGame.objects.get(pk=identity).status == "completed"


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_the_status(owned_user, owned_library, tracked_game):
    """Replay parity over an amended row."""
    dispatch(
        TrackGame(game_id=tracked_game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    dispatch(
        SetPlayerGameStatus(
            game_id=tracked_game.pk, status=PlayerGameStatus.COMPLETED
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="complete",
    )

    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)
    drift = [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [(0, 0, 0)]

    rebuilt = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert rebuilt.swapped is True
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED
```

Add `PLAYERGAME_STATUS_CHANGED` to the `from games.events.playergame import ...` line and `SetPlayerGameStatus` to the `from games.commands.playergame import ...` line.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_projection.py -k status"`
Expected: FAIL — the status event has no handler, so `PlayerGame.status` stays `"unplayed"`.

- [ ] **Step 3: Add the handler**

In `games/projectors/playergame.py`:

```python
    def _status_changed(self, event: RecordedEvent) -> None:
        #: From the event, so a replay writes what was recorded.
        self.amend(PlayerGame, event.aggregate_id, status=event.payload["status"])

    handles: ClassVar[HandlerMap] = {
        PLAYERGAME_CREATED: _created,
        PLAYERGAME_STATUS_CHANGED: _status_changed,
    }
```

Add `PLAYERGAME_STATUS_CHANGED` to the module's import from `games.events.playergame`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_projection.py"`
Expected: PASS, whole file.

- [ ] **Step 5: Commit**

```bash
git add games/projectors/playergame.py tests/test_playergame_projection.py
git commit -m "Fold a status onto the row that has one"
```

---

### Task 7: The gate

**Files:** none — verification only.

- [ ] **Step 1: Run the full gate**

Run: `make check`
Expected: green. Lint, format-check, mypy, ts-check, vitest, and the whole pytest suite including `e2e/`.

- [ ] **Step 2: Run the benchmark**

Run: `make bench`
Expected: completes. The workload seeds creation events only; the new column fills from its default, so no scenario changes. If it fails on a `PlayerGame` row built directly in `games/events/benchmark_workload.py`, that row needs no edit — the default supplies the column — so investigate rather than patch around it.

- [ ] **Step 3: Commit anything the gate changed**

```bash
git status --short
```

Expected: clean. Commit any formatter output if not.
