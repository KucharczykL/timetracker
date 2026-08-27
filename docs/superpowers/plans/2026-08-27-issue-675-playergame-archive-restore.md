# PlayerGame archive and restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a library two commands that hide a tracked game and show it again, recorded as two events and projected onto one column.

**Architecture:** The fifth slice of the PlayerGame vertical, and the fourth to repeat one shape: an `EventSpec` in `games/events/playergame.py`, a handler in `games/projectors/playergame.py` that calls `amend()`, a `Command` in `games/commands/playergame.py` that validates under the stream-head lock, and a column on `PlayerGame`. Nothing reads the column yet; #677 switches the writes and #678 moves the reads.

**Tech Stack:** Django 6 on Python 3.14, PostgreSQL 18, pydantic `TypeAdapter` payload validation, pytest with `pytest-django`.

**Spec:** `docs/superpowers/specs/2026-08-27-issue-675-playergame-archive-restore-design.md`

## Global Constraints

- Run everything through `make`. Never `uv run`, never a bare `pytest`, never `direnv exec .`.
- Iterate with `make check-fast`; the gate before you call the work done is the full `make check`.
- Focused runs: `make test ARGS="tests/test_playergame_command.py -k archive"`.
- Python 3.14 only. A `SyntaxError` in an `except A, B:` means the wrong interpreter, not broken code.
- Never write to a `GeneratedField`, and never write a projection row outside its projector.
- Name variables with complete words: `element`, not `el`; `event`, not `e`.
- The column is `archived_at`. It is **not** `archived_at`: that name belongs to retention, where it marks a gutted catalog row. A hidden `PlayerGame` keeps every fact.
- The event types are `library.playergame.archived` and `library.playergame.restored`. The charter fixes those names and a recorded event type is permanent.
- Every rejection message that stands in for an undecided no-op names `#906`, as the three sibling commands do.

---

### Task 1: The column

**Files:**
- Modify: `games/models.py` (class `PlayerGame`, after `excluded_from_unfinished`)
- Create: `games/migrations/0032_playergame_archived_at.py` (generated, not hand-written)
- Test: `tests/test_playergame_projection.py`, `tests/test_projection_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PlayerGame.archived_at`, a `DateTimeField` that is `None` on a new row and holds the archive event's `recorded_at` once set.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_playergame_projection.py`, directly after `test_a_tracked_game_starts_in_unfinished_lists`:

```python
def test_a_tracked_game_starts_live():
    """The creation event archives nothing."""
    assert PlayerGame().archived_at is None
```

In `tests/test_projection_model.py`, add the entry to `PINNED_DEFAULTS`:

```python
#: Every constant a projection column starts at.
PINNED_DEFAULTS: dict[str, dict[str, object]] = {
    "games.PlayerGame": {
        "status": "unplayed",
        "mastered": False,
        "excluded_from_unfinished": False,
        "archived_at": None,
    },
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_projection.py::test_a_tracked_game_starts_shown tests/test_projection_model.py::test_every_projection_default_is_pinned"`

Expected: FAIL. The first with `AttributeError: 'PlayerGame' object has no attribute 'archived_at'`, the second with an assertion diff whose right side carries `archived_at` and whose left side does not.

- [ ] **Step 3: Add the column**

In `games/models.py`, at the end of `PlayerGame`'s field list:

```python
class PlayerGame(ProjectionModel):
    ...

    #: An explicit preference, never inferred from status.
    excluded_from_unfinished = models.BooleanField(default=False)
    #: The archive event's recorded_at; null means live.
    #: The player's own act, not retention's tombstoned_at.
    archived_at = models.DateTimeField(null=True, default=None, editable=False)
```

Two short lines, as the columns above it have. The full argument for the name is the spec's own section; the comment only has to stop the next reader from "fixing" the inconsistency.

`editable=False` matches `tracked_at`, the other column a projector writes. `default=None` is explicit rather than omitted so that `has_default()` is true and the start value has to pass through `PINNED_DEFAULTS`.

- [ ] **Step 4: Generate the migration**

Run: `make makemigrations`

Take the target bare. It passes no `ARGS` (`Makefile:140-141` runs `manage.py makemigrations --noinput` and nothing else), so it regenerates for every app; check that this one field is all that appeared.

Expected: `games/migrations/0032_playergame_archived_at.py`. Django names a single-operation migration after the operation, so `AddField` on `PlayerGame.archived_at` produces that filename without being told. Read the file and confirm it holds one `AddField`, adds nothing else, and carries no `RunPython`:

```python
class Migration(migrations.Migration):
    dependencies = [
        ("games", "0031_playergame_excluded_from_unfinished"),
    ]

    operations = [
        migrations.AddField(
            model_name="playergame",
            name="archived_at",
            field=models.DateTimeField(default=None, editable=False, null=True),
        ),
    ]
```

There is no data step. No event hides a game, so every existing row is `NULL`, which is what a rebuild must reproduce.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_projection.py tests/test_projection_model.py"`

Expected: PASS. `test_playergame_is_a_pure_projection` passing is the check that matters most here: it runs `check_projection_models()`, and E004 to E007 would fire on a database default or a callable one. `None` is neither.

- [ ] **Step 6: Commit**

```bash
git add games/models.py games/migrations/0032_playergame_archived_at.py tests/test_playergame_projection.py tests/test_projection_model.py
git commit -m "Give a tracked game a hidden column"
```

---

### Task 2: The two events

**Files:**
- Modify: `games/events/playergame.py` (append at the end)
- Test: `tests/test_playergame_events.py` (append at the end)

**Interfaces:**
- Consumes: `PlayerGame.archived_at` from Task 1 only as motivation; no code dependency.
- Produces: `PLAYERGAME_ARCHIVED` and `PLAYERGAME_RESTORED`, both `EventSpec` values with `aggregate_type="playergame"` and an empty payload. Build one with `PLAYERGAME_ARCHIVED.new(aggregate_id=identity, payload={})`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_events.py`, and add `PLAYERGAME_ARCHIVED` and `PLAYERGAME_RESTORED` to the existing `from games.events.playergame import (...)` block:

```python
def test_the_archive_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playergame.archived")

    assert registered is PLAYERGAME_ARCHIVED
    assert registered.aggregate_type == "playergame"


def test_the_archive_payload_states_nothing_but_its_type():
    """Two facts take two types, so no key states a direction."""
    assert DEFAULT_EVENT_TYPES.validate(PLAYERGAME_ARCHIVED.event_type, {}) == {}


def test_an_archive_payload_stating_a_direction_is_refused():
    """A key nobody declared could disagree with the type."""
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYERGAME_ARCHIVED.event_type, {"archived": True})


def test_the_archive_payload_carries_no_reference():
    """The creation event holds the one reference."""
    assert (
        DEFAULT_EVENT_TYPES.reference_fields_for(PLAYERGAME_ARCHIVED.event_type) == {}
    )


def test_the_restore_event_is_in_the_application_vocabulary():
    registered = DEFAULT_EVENT_TYPES.spec_for("library.playergame.restored")

    assert registered is PLAYERGAME_RESTORED
    assert registered.aggregate_type == "playergame"


def test_the_restore_payload_states_nothing_but_its_type():
    assert DEFAULT_EVENT_TYPES.validate(PLAYERGAME_RESTORED.event_type, {}) == {}


def test_a_restore_payload_stating_a_direction_is_refused():
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(PLAYERGAME_RESTORED.event_type, {"restored": True})
```

Seven tests, not eight: a test that the two `event_type` strings differ would be two adjacent literals asserting about each other, and `EventTypeRegistry.register` already refuses a name it holds.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_events.py"`

Expected: FAIL at import with `ImportError: cannot import name 'PLAYERGAME_ARCHIVED'`.

- [ ] **Step 3: Add the two specs**

Append to `games/events/playergame.py`:

```python
@with_config(STRICT_SCHEMA)
class PlayerGameArchivedPayload(TypedDict):
    """The library now archives the game."""


PLAYERGAME_ARCHIVED = EventSpec(
    "library.playergame.archived",
    aggregate_type="playergame",
    payload=PlayerGameArchivedPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_ARCHIVED)


@with_config(STRICT_SCHEMA)
class PlayerGameRestoredPayload(TypedDict):
    """The library restores the game."""


PLAYERGAME_RESTORED = EventSpec(
    "library.playergame.restored",
    aggregate_type="playergame",
    payload=PlayerGameRestoredPayload,
)

DEFAULT_EVENT_TYPES.register(PLAYERGAME_RESTORED)
```

An empty `TypedDict` is a real schema here, not a placeholder: `STRICT_SCHEMA` is `extra="forbid"`, so the adapter accepts `{}` and refuses every key. The time is not in the payload because the event row carries `recorded_at`, exactly as the creation event does for `tracked_at`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_events.py"`

Expected: PASS, all seven new tests plus the existing ones.

- [ ] **Step 5: Commit**

```bash
git add games/events/playergame.py tests/test_playergame_events.py
git commit -m "Record hiding and showing as two events"
```

---

### Task 3: The two handlers

**Files:**
- Modify: `games/projectors/playergame.py`
- Test: `tests/test_playergame_projection.py` (append at the end)

**Interfaces:**
- Consumes: `PLAYERGAME_ARCHIVED` and `PLAYERGAME_RESTORED` from Task 2; `PlayerGame.archived_at` from Task 1.
- Produces: `PlayerGames._archived` and `PlayerGames._restored`, both registered in `PlayerGames.handles`. After this task an appended archive event writes `archived_at`; no command exists yet, so the tests append through `lock_stream` as the sibling tests do.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_projection.py`. Add `PLAYERGAME_ARCHIVED` and `PLAYERGAME_RESTORED` to the existing `from games.events.playergame import (...)` block:

```python
def append_archived(library, actor, identity, *, key="archive"):
    """Append one archive event, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [PLAYERGAME_ARCHIVED.new(aggregate_id=identity, payload={})],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


def append_restored(library, actor, identity, *, key="restore"):
    """Append one restore event, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [PLAYERGAME_RESTORED.new(aggregate_id=identity, payload={})],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


@pytest.mark.django_db(transaction=True)
def test_the_archive_event_writes_its_own_time(owned_user, owned_library, tracked_game):
    """The row takes recorded_at, not the clock."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)

    append_archived(owned_library, owned_user, identity)

    recorded = LibraryEvent.objects.get(event_type="library.playergame.archived")
    assert PlayerGame.objects.get(pk=identity).archived_at == recorded.recorded_at


@pytest.mark.django_db(transaction=True)
def test_the_restore_event_states_the_way_back(owned_user, owned_library, tracked_game):
    """Two types, and the second clears the first."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_archived(owned_library, owned_user, identity)

    append_restored(owned_library, owned_user, identity)

    assert PlayerGame.objects.get(pk=identity).archived_at is None


@pytest.mark.django_db(transaction=True)
def test_replaying_the_creation_event_again_keeps_a_later_archive(
    owned_user, owned_library, tracked_game
):
    """A default is absent from DO UPDATE."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_archived(owned_library, owned_user, identity)
    created = RecordedEvent.from_row(
        LibraryEvent.objects.get(event_type="library.playergame.created")
    )

    DEFAULT_REGISTRY.apply(created)

    assert PlayerGame.objects.get(pk=identity).archived_at is not None


@pytest.mark.django_db(transaction=True)
def test_replaying_the_archive_event_costs_one_statement(
    owned_user, owned_library, tracked_game
):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_archived(owned_library, owned_user, identity)
    event = RecordedEvent.from_row(
        LibraryEvent.objects.get(event_type="library.playergame.archived")
    )

    with CaptureQueriesContext(connection) as queries:
        DEFAULT_REGISTRY.apply(event)

    assert [query["sql"].split(maxsplit=1)[0] for query in queries] == ["UPDATE"]


@pytest.mark.django_db(transaction=True)
def test_a_replay_reproduces_the_archive(owned_user, owned_library, tracked_game):
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_archived(owned_library, owned_user, identity)
    archived_at = PlayerGame.objects.get(pk=identity).archived_at
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert PlayerGame.objects.get(pk=identity).archived_at == archived_at


@pytest.mark.django_db(transaction=True)
def test_a_replay_reproduces_an_archive_and_its_undoing(
    owned_user, owned_library, tracked_game
):
    """Order decides, so the pair must replay in sequence."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_archived(owned_library, owned_user, identity)
    append_restored(owned_library, owned_user, identity)
    append_archived(owned_library, owned_user, identity, key="archive-again")
    archived_at = PlayerGame.objects.get(pk=identity).archived_at
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert PlayerGame.objects.get(pk=identity).archived_at == archived_at


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_the_archive(owned_user, owned_library, tracked_game):
    """Replay parity over a nullable column."""
    identity = uuid.uuid7()
    append_created(owned_library, owned_user, tracked_game, identity=identity)
    append_archived(owned_library, owned_user, identity)

    checked = rebuild_projections(owned_library, mode=RebuildMode.CHECK)

    drift = [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in checked.tables
    ]
    assert drift == [(0, 0, 0)]

    rebuilt = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert rebuilt.swapped is True
    assert PlayerGame.objects.get(pk=identity).archived_at is not None
```

`test_a_rebuild_reproduces_the_hide` is the one that earns its keep beyond the sibling pattern: `archived_at` is the first nullable column on a projection, and the rebuild compares rows with `IS DISTINCT FROM` (`games/events/rebuild.py:221`). If that ever became a plain `=`, every `NULL` would read as drift and this test would catch it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_projection.py -k 'hide or archive or restore'"`

Expected: FAIL, on the assertions rather than on the append. An event type no family claims is a silent no-op: `ProjectorRegistry.apply` iterates the handlers registered for the type and finds none (`games/events/projection.py:181`), and the append path calls nothing else (`games/events/append.py:211`). So the appends succeed, `archived_at` stays `None`, and each test reports `None != <timestamp>` or `None is not None` — except the statement-count one, which reports `[] != ["UPDATE"]`.

- [ ] **Step 3: Add the two handlers**

In `games/projectors/playergame.py`, add both methods after `_excluded_from_unfinished_changed`, add the two specs to the import block, and add both entries to `handles`:

```python
class PlayerGames(Projector):
    ...

    def _archived(self, event: RecordedEvent) -> None:
        #: The event's own time, so replays agree.
        self.amend(PlayerGame, event.aggregate_id, archived_at=event.recorded_at)

    def _restored(self, event: RecordedEvent) -> None:
        self.amend(PlayerGame, event.aggregate_id, archived_at=None)

    handles: ClassVar[HandlerMap] = {
        PLAYERGAME_CREATED: _created,
        PLAYERGAME_STATUS_CHANGED: _status_changed,
        PLAYERGAME_MASTERED_CHANGED: _mastered_changed,
        PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED: _excluded_from_unfinished_changed,
        PLAYERGAME_ARCHIVED: _archived,
        PLAYERGAME_RESTORED: _restored,
    }
```

`amend()` and not `project()`: an event that changes one column knows nothing of the columns the creation event wrote, and a missing row must raise `ProjectionRowMissing` rather than insert a part-row a rebuild could not reproduce.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_projection.py"`

Expected: PASS, the whole file.

- [ ] **Step 5: Commit**

```bash
git add games/projectors/playergame.py tests/test_playergame_projection.py
git commit -m "Hide and show the row an event names"
```

---

### Task 4: The two commands

**Files:**
- Modify: `games/events/dispatch.py` (class `CommandName`)
- Modify: `games/commands/playergame.py` (append at the end)
- Test: `tests/test_playergame_command.py` (append at the end)

**Interfaces:**
- Consumes: `PLAYERGAME_ARCHIVED`, `PLAYERGAME_RESTORED` (Task 2), the handlers (Task 3), and the module-level `_tracked_game(context, game_id)` helper already in `games/commands/playergame.py`.
- Produces: `ArchivePlayerGame(game_id=...)` and `RestorePlayerGame(game_id=...)`, both frozen slotted dataclasses taking one `uuid.UUID`; `CommandName.PLAYERGAME_ARCHIVE` and `CommandName.PLAYERGAME_RESTORE`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_command.py`, adding `ArchivePlayerGame` and `RestorePlayerGame` to the existing `from games.commands.playergame import (...)` block:

```python
@pytest.mark.django_db(transaction=True)
def test_archiving_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.archived")
    assert event.payload == {}
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert row.archived_at == event.recorded_at


@pytest.mark.django_db(transaction=True)
def test_restoring_a_game_returns_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )

    dispatch(
        RestorePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restore-outer-wilds",
    )

    assert LibraryEvent.objects.get(event_type="library.playergame.restored")
    assert PlayerGame.objects.get().archived_at is None


@pytest.mark.django_db(transaction=True)
def test_archiving_a_game_leaves_the_rest_of_the_row_alone(owned_user, owned_library):
    """A restore gives back the game the library had."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.PLAYED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="play-outer-wilds",
    )
    dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=True),
        actor=owned_user,
        library=owned_library,
        idempotency_key="master-outer-wilds",
    )
    before = PlayerGame.objects.get()

    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
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
def test_archiving_an_untracked_game_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            ArchivePlayerGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="archive-untracked",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.archived"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_archiving_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            ArchivePlayerGame(game_id=shared_game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="archive-theirs",
        )

    assert PlayerGame.objects.get().archived_at is None


@pytest.mark.django_db(transaction=True)
def test_archiving_a_game_the_library_already_archives_is_refused(
    owned_user, owned_library
):
    """One convention for #906 to change."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            ArchivePlayerGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="archive-outer-wilds-again",
        )

    assert (
        LibraryEvent.objects.filter(event_type="library.playergame.archived").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restoring_a_game_the_library_does_not_archive_is_refused(
    owned_user, owned_library
):
    """One convention for #906 to change."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            RestorePlayerGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="restore-outer-wilds",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.restored"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_archive(owned_user, owned_library):
    """The key answers before the state check does."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    command = ArchivePlayerGame(game_id=game.pk)

    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="archive"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="archive"
    )

    assert (first.replayed, second.replayed) == (False, True)
    assert (
        LibraryEvent.objects.filter(event_type="library.playergame.archived").count()
        == 1
    )
```

The last one repeats what the three sibling slices each pin, and `dispatch` hands `build` to `idempotent_append` as a callback (`games/events/dispatch.py:278-291`), so the ordering it depends on is already proven. It is here for symmetry with them, not because it covers new ground.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_command.py"`

Expected: FAIL at import with `ImportError: cannot import name 'ArchivePlayerGame'`.

- [ ] **Step 3: Add the two command names**

In `games/events/dispatch.py`, extend `CommandName`:

```python
class CommandName(CommandVocabulary):
    ...

    PLAYERGAME_ARCHIVE = "library.playergame.archive"
    PLAYERGAME_RESTORE = "library.playergame.restore"
```

- [ ] **Step 4: Add the two commands**

Append to `games/commands/playergame.py`, and add `PLAYERGAME_ARCHIVED` and `PLAYERGAME_RESTORED` to the existing `from games.events.playergame import (...)` block:

```python
@dataclass(frozen=True, slots=True)
class ArchivePlayerGame(Command):
    """Archive a tracked game."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_ARCHIVE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.archived_at is not None:
            raise CommandRejected(
                f"This library already archives game {self.game_id}. Whether a "
                "repeat should instead succeed as a no-op is EV-23 (#906)."
            )
        return [PLAYERGAME_ARCHIVED.new(aggregate_id=tracked.pk, payload={})]


@dataclass(frozen=True, slots=True)
class RestorePlayerGame(Command):
    """Restore a game this library archived.

    The catalog is not consulted. A delete of a tracked game tombstones the
    catalog row and keeps this one, so an archived game may outlive the row it
    names; refusing would leave the library a game it can neither see nor
    recover.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_RESTORE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.archived_at is None:
            raise CommandRejected(
                f"This library does not archive game {self.game_id}. Whether a "
                "repeat should instead succeed as a no-op is EV-23 (#906)."
            )
        return [PLAYERGAME_RESTORED.new(aggregate_id=tracked.pk, payload={})]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_command.py"`

Expected: PASS, the whole file.

- [ ] **Step 6: Commit**

```bash
git add games/events/dispatch.py games/commands/playergame.py tests/test_playergame_command.py
git commit -m "Add commands that hide and show a tracked game"
```

---

### Task 5: The message that names the restore

**Files:**
- Modify: `games/commands/playergame.py` (`TrackGame.build`, the duplicate rejection)
- Test: `tests/test_playergame_command.py`

**Interfaces:**
- Consumes: `ArchivePlayerGame` and `RestorePlayerGame` from Task 4.
- Produces: nothing new. The rejection text changes; the behaviour does not.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_playergame_command.py`, and add `Retirement` and `tombstone_or_delete` to the existing `from games.retention import purging_library` line so it reads `from games.retention import Retirement, purging_library, tombstone_or_delete`:

```python
@pytest.mark.django_db(transaction=True)
def test_tracking_an_archived_game_names_the_restore(owned_user, owned_library):
    """The message a person reads must match what they see."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )

    with pytest.raises(CommandRejected, match="restored, not tracked again"):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-again",
        )

    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_tracking_a_live_game_twice_still_says_the_library_tracks_it(
    owned_user, owned_library
):
    """The rare case may not blunt the common one."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="already tracks Outer Wilds"):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-again",
        )


@pytest.mark.django_db(transaction=True)
def test_a_game_whose_catalog_row_is_tombstoned_is_still_restored(
    owned_user, owned_library
):
    """The projection answers, not the catalog."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )
    #: A delete of a tracked game keeps the projection row.
    assert tombstone_or_delete(game) is Retirement.TOMBSTONED

    dispatch(
        RestorePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restore-outer-wilds",
    )

    assert PlayerGame.objects.get().archived_at is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_playergame_command.py -k 'names_the_restore or says_the_library_tracks_it or catalog_row_is_archived'"`

Expected: the first FAILS, because the current message says "already tracks" and the `match=` does not find "restored, not tracked again". The other two PASS already. `test_tracking_a_shown_game_twice_still_says_the_library_tracks_it` is a regression guard written before the change it guards against: it pins the wording this task must *not* damage. `test_a_game_whose_catalog_row_is_archived_is_still_restored` characterises behaviour Task 4 delivered, and is here because the spec commits to it and nothing else pins it.

- [ ] **Step 3: Branch the message**

In `games/commands/playergame.py`, in `TrackGame.build`, replace the existing duplicate rejection:

```python
def build(self, context: CommandContext) -> Sequence[NewEvent]:
    game = self._visible_game(context)
    #: Under dispatch's lock: no concurrent duplicate.
    tracked = PlayerGame.objects.filter(library=context.library, game=game).first()
    if tracked is not None:
        if tracked.archived_at is not None:
            raise CommandRejected(
                f"This library hides {game.name} rather than tracking it. A "
                "hidden game is restored, not tracked again."
            )
        raise CommandRejected(
            f"This library already tracks {game.name}. Whether a repeat "
            "should instead succeed as a no-op is EV-23 (#906)."
        )
    return [
        PLAYERGAME_CREATED.new(
            aggregate_id=uuid.uuid7(),
            payload={"game": capture_reference(game)},
        )
    ]
```

Two messages rather than one amended message. A single text would have to describe hiding to somebody whose game is not hidden, and the shown case is the common one. `.exists()` becomes `.first()`, which is the same one query.

The `#906` citation stays on the shown branch only. There it is honest: EV-23 may decide that a repeat succeeds as a no-op. On the hidden branch it would be wrong — tracking a hidden game is not a repeat of anything, and the remedy is `RestorePlayerGame`, which exists.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_playergame_command.py"`

Expected: PASS. `test_tracking_the_same_game_twice_is_refused` asserts only the exception type, so it keeps passing.

- [ ] **Step 5: Commit**

```bash
git add games/commands/playergame.py tests/test_playergame_command.py
git commit -m "Send a repeat track to the restore"
```

---

### Task 6: The gate and the record

**Files:**
- Delete: `docs/superpowers/plans/2026-08-27-issue-675-playergame-archive-restore.md`

**Interfaces:**
- Consumes: every task above.
- Produces: nothing the code imports.

`CLAUDE.md` needs no edit. #673 changed the `PlayerGame` bullet to say the row is "written only by the `PlayerGames` projector", which stays true with a sixth event type, and #674 added its column without touching the bullet. `docs/STATUSES.md` and `docs/event-retention.md` also stay as they are: the first describes the purchase-based unfinished list, and the second describes retention's `archived_at`, which this issue deliberately does not touch.

- [ ] **Step 1: Delete this plan**

The spec stays; the plan does not outlive the work. Delete it before the gate rather than after, so `format-check` never has to be right about these fences.

```bash
git rm docs/superpowers/plans/2026-08-27-issue-675-playergame-archive-restore.md
```

- [ ] **Step 2: Run the full gate**

Run: `make check`

Expected: green. It runs lint, format check, mypy, the TypeScript checks, vitest, the migration drift guard (`check-migrations`, which fails if the model and `0032` disagree), and the whole pytest suite including `e2e/`.

A hand-picked subset is not the gate. If the formatter rewraps a line, commit that with the rest. If `make check` is red before you start, check `python --version` first: it must be 3.14.x.

- [ ] **Step 3: Commit**

```bash
git commit -m "Retire the plan for the archive and restore slice"
```

- [ ] **Step 4: Report**

State the result plainly, with the output if anything failed.

---

## Notes for the reviewer

- **Six commits, one per task**, matching the four sibling slices. Nothing in Tasks 1 to 3 is reachable from a view, so a partial merge is inert rather than broken.
- **What is deliberately absent:** no manager or queryset that filters `archived_at`, no read, no UI. #678 owns the reads and decides what a hidden game means to each list. Adding a `live()` manager here would be a read-path decision taken in the wrong issue.
- **What the spec forbids:** naming the column `archived_at`. `games/retention.py` uses that name for a row a delete gutted and kept, and `tests/test_retention.py::test_a_tracked_game_archives_and_keeps_its_projection_row` proves both columns can be set on one row at once.
